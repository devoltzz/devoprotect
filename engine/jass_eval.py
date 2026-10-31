# Runs a small part of a JASS script to compute values the script only builds at run time.
import math
import random
import re
import sys
import time

import jass_ast


DEFAULTS = {'integer': 0, 'real': 0.0, 'boolean': False, 'string': None}
MAX_ARRAY = 32768
EXIT, RETURN = 1, 2


class JassError(Exception):
    pass


class Crash(JassError):
    def __init__(self, message, global_name=None):
        JassError.__init__(self, message)
        self.global_name = global_name


class Budget(JassError):
    pass


_MATH_ERRORS = (ArithmeticError, ValueError, TypeError, OverflowError)


class _Unset(object):
    __slots__ = ()

    def __repr__(self):
        return 'UNSET'


UNSET = _Unset()


class Code(object):
    __slots__ = ('name',)

    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return isinstance(other, Code) and other.name == self.name

    def __hash__(self):
        return hash(('code', self.name))


class Handle(object):
    __slots__ = ('kind', 'data', '__weakref__')

    def __init__(self, kind, data=None):
        self.kind = kind
        self.data = data


def _wrap(v):
    return ((v + 0x80000000) & 0xFFFFFFFF) - 0x80000000


def _bytes_text(s):
    return None if s is None else s.encode('latin-1', 'replace').decode('utf-8', 'replace')


def _script_bytes(text):
    if isinstance(text, bytes):
        return text.decode('latin-1')
    return text.encode('utf-8', 'surrogateescape').decode('latin-1')


def _literal_text(node):
    k = node.kind
    if k == 'string':
        return jass_ast._unescape(node.text[1:-1])
    if k == 'rawcode':
        v = 0
        for b in jass_ast._unescape(node.text[1:-1]).encode('latin-1', 'replace'):
            v = (v * 256 + (b - 256 if b >= 128 else b)) & 0xFFFFFFFF
        return _wrap(v)
    return jass_ast.literal_value(k, node.text)


def _truthy(v):
    if v is UNSET:
        raise Crash('read of an uninitialized variable')
    return bool(v)


MAX_STRING = 1 << 20
MAX_KEPT = 512 << 20


def _concat_or_add(a, b):
    if isinstance(a, str) or isinstance(b, str):
        r = (a or '') + (b or '')
        if len(r) > MAX_STRING:
            raise Crash('a string longer than %d characters' % MAX_STRING)
        return r
    if a is None and b is None:
        return None
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        raise Crash('+ on %r and %r' % (a, b))
    if isinstance(a, int) and isinstance(b, int):
        return _wrap(a + b)
    return float(a) + float(b)


def _num(a):
    if isinstance(a, bool) or not isinstance(a, (int, float)):
        raise Crash('arithmetic on %r' % (a,))
    return a


def _sub(a, b):
    a, b = _num(a), _num(b)
    return _wrap(a - b) if isinstance(a, int) and isinstance(b, int) else float(a) - float(b)


def _mul(a, b):
    a, b = _num(a), _num(b)
    return _wrap(a * b) if isinstance(a, int) and isinstance(b, int) else float(a) * float(b)


def _div(a, b):
    a, b = _num(a), _num(b)
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            raise Crash('integer division by zero')
        q = abs(a) // abs(b)
        return _wrap(q if (a < 0) == (b < 0) else -q)
    if b == 0:
        raise Crash('real division by zero')
    return float(a) / float(b)


def _null_as(a, b):
    if a is None and isinstance(b, (int, float)):
        return type(b)(0), b
    if b is None and isinstance(a, (int, float)):
        return a, type(a)(0)
    return a, b


def _real_pair(a, b):
    return (isinstance(a, float) or isinstance(b, float)) and not isinstance(a, bool) and not isinstance(b, bool) \
        and isinstance(a, (int, float)) and isinstance(b, (int, float))


def _cmp(op):
    def f(a, b):
        if a is UNSET or b is UNSET:
            raise Crash('read of an uninitialized variable')
        a, b = _null_as(a, b)
        if op == '==' and _real_pair(a, b):
            return abs(float(a) - float(b)) < 0.001
        if op == '==':
            return a == b if not (isinstance(a, Handle) or isinstance(b, Handle)) else a is b
        if op == '!=':
            return a != b if not (isinstance(a, Handle) or isinstance(b, Handle)) else a is not b
        a, b = _num(a), _num(b)
        return {'<': a < b, '<=': a <= b, '>': a > b, '>=': a >= b}[op]
    return f


_BINARY = {'+': _concat_or_add, '-': _sub, '*': _mul, '/': _div}
for _op in ('==', '!=', '<', '<=', '>', '>='):
    _BINARY[_op] = _cmp(_op)


def _coerce(type_, v):
    if v is None and type_ in ('integer', 'real', 'boolean'):
        return DEFAULTS[type_]
    if type_ == 'real' and isinstance(v, int) and not isinstance(v, bool):
        return float(v)
    return v


def _expr_ops(e):
    if e is None:
        return 0
    if isinstance(e, (jass_ast.Literal, jass_ast.Name, jass_ast.FuncRef)):
        return 1
    if isinstance(e, jass_ast.Index):
        return 1 + _expr_ops(e.index)
    if isinstance(e, jass_ast.Call):
        return sum(_expr_ops(a) for a in e.args)
    if isinstance(e, jass_ast.Paren):
        return _expr_ops(e.inner)
    if isinstance(e, jass_ast.Unary):
        return 1 + _expr_ops(e.operand)
    if isinstance(e, jass_ast.Binary):
        return 1 + _expr_ops(e.left) + _expr_ops(e.right)
    return 1


def _stmt_ops(s):
    if isinstance(s, jass_ast.SetStmt):
        t = s.target
        return 1 + _expr_ops(s.value) + (0 if isinstance(t, jass_ast.Name) else _expr_ops(t.index))
    if isinstance(s, jass_ast.CallStmt):
        return _expr_ops(s.call)
    if isinstance(s, jass_ast.ExitWhenStmt):
        return 1 + _expr_ops(s.cond)
    if isinstance(s, jass_ast.ReturnStmt):
        return 1 + _expr_ops(s.value)
    return 0


class Interpreter(object):
    def __init__(self, script, libraries=(), budget=3000000, seconds=30.0, seed=0, natives=None):
        self.overrides = dict(natives or {})
        self.chat_registrations = []
        self.chat_string = None
        self.chat_matched = None
        self.recorded = {}
        self.budget = budget
        self.deadline = None
        self.seconds = seconds
        self.steps = 0
        self.ops = 0
        self.thread_costs = {}
        self.thread_budget = set()
        self.kept_chars = 0
        self._frames = []
        self.early = 0.0
        self.early_timers = []
        self.unknown = {}
        self.inert_calls = 0
        self.last_inert = None
        self.crashes = []
        self.chat_events = []
        self.timers = []
        self.functions = {}
        self.native_types = {}
        self.globals = {}
        self.global_types = {}
        self._compiled = {}
        self._handle_ids = {}
        self._players = {}
        self.enum_player = None
        self.player_trigger = None
        self.random = random.Random(seed)
        trees = []
        for lib in libraries:
            if lib:
                try:
                    trees.append(jass_ast.parse(_script_bytes(lib)))
                except jass_ast.JassSyntaxError:
                    pass
        self.script = jass_ast.parse(_script_bytes(script))
        trees.append(self.script)
        for t in trees:
            for n in t.natives:
                self.native_types[n.name] = n.return_type
            for f in t.functions:
                self.functions[f.name] = f
        self._trees = trees

    def hold(self, old, new):
        n = (len(new) if isinstance(new, str) else 0) - (len(old) if isinstance(old, str) else 0)
        if n:
            self.kept_chars += n
            if self.kept_chars > MAX_KEPT:
                raise Budget('the strings kept passed %d characters' % MAX_KEPT)

    def tick(self, n=1):
        self.steps += n
        if self.steps > self.budget:
            raise Budget('the step budget (%d) ran out' % self.budget)
        if not self.steps & 0x3FFF and self.deadline and time.time() > self.deadline:
            raise Budget('the time limit (%.0f s) ran out' % self.seconds)

    def init_globals(self):
        for t in self._trees:
            for g in t.globals:
                self.global_types[g.name] = g.type
                if g.is_array:
                    self.globals[g.name] = {}
                    continue
                if g.initializer is None:
                    self.globals[g.name] = UNSET
                    continue
                try:
                    self.globals[g.name] = _coerce(g.type, self._expr(g.initializer, {})({}))
                except (Crash,) + _MATH_ERRORS as e:
                    self.globals[g.name] = UNSET
                    self.crashes.append('global %s: %s' % (g.name, e))
                except RecursionError:
                    self.globals[g.name] = UNSET
                    self.crashes.append('global %s: too deep' % g.name)

    def thread(self, name, args=()):
        frame = [self.ops, 0, name]
        self._frames.append(frame)
        try:
            return self._thread(name, args)
        except Budget:
            self.thread_budget.add(name)
            raise
        finally:
            self._frames.pop()
            spent = self.ops - frame[0]
            if name not in self.thread_budget:
                self._close(frame)
            if self._frames:
                self._frames[-1][1] += spent

    def _close(self, frame):
        own = self.ops - frame[0] - frame[1]
        if own > self.thread_costs.get(frame[2], -1):
            self.thread_costs[frame[2]] = own

    def sleep(self):
        if self._frames:
            frame = self._frames[-1]
            self._close(frame)
            frame[0], frame[1] = self.ops, 0

    def _thread(self, name, args=()):
        try:
            return self.call(name, list(args))
        except Budget:
            raise
        except Crash as e:
            if len(self.crashes) < 200:
                self.crashes.append('%s: %s' % (name, e))
            return None
        except RecursionError:
            self.crashes.append('%s: too deep' % name)
            return None
        except _MATH_ERRORS as e:
            if len(self.crashes) < 200:
                self.crashes.append('%s: %s' % (name, e))
            return None

    def start(self, entries=('config', 'main')):
        self.deadline = time.time() + self.seconds
        self.init_globals()
        for name in entries:
            if name in self.functions:
                self.thread(name)
        for _round in range(4):
            pending, self.timers = self.timers, []
            if not pending:
                break
            for x in pending:
                if isinstance(x, Code):
                    self.thread(x.name)
                elif _trigger_evaluate(self, x):
                    _trigger_execute(self, x)

    def run_early(self):
        pending = sorted(self.early_timers)
        self.early_timers = []
        for _t, _n, x in pending:
            if isinstance(x, Code):
                self.thread(x.name)
            elif _trigger_evaluate(self, x):
                _trigger_execute(self, x)
        for _round in range(4):
            now, self.timers = self.timers, []
            if not now:
                break
            for x in now:
                if isinstance(x, Code):
                    self.thread(x.name)
                elif _trigger_evaluate(self, x):
                    _trigger_execute(self, x)

    def chat(self, player_id, message):
        self.overrides.setdefault('GetEventPlayerChatString', lambda it: it.chat_string)
        self.overrides.setdefault('GetEventPlayerChatStringMatched', lambda it: it.chat_matched)
        msg = message.encode('utf-8', 'surrogateescape').decode('latin-1')
        p = self.player(player_id)
        ran = 0
        for t, who, text, exact in list(self.chat_registrations):
            text = _s(text)
            if who is not p or t is None or not (msg == text if exact else text in msg):
                continue
            saved = self.player_trigger, self.chat_string, self.chat_matched
            self.player_trigger, self.chat_string, self.chat_matched = p, msg, text
            try:
                if _trigger_evaluate(self, t):
                    _trigger_execute(self, t)
                    ran += 1
            finally:
                self.player_trigger, self.chat_string, self.chat_matched = saved
        return ran

    def record(self, name):
        f = self.functions.get(name)
        if f is None or f.is_native:
            raise JassError('no function %s in the script' % name)
        inner = self._function(f)
        calls = self.recorded.setdefault(name, [])

        def run(args):
            calls.append(list(args))
            return inner(args)
        self._compiled[name] = run
        return calls

    def call(self, name, args):
        f = self.functions.get(name)
        if f is None:
            impl = self.overrides.get(name) if self.overrides else None
            if impl is None:
                impl = NATIVES.get(name)
            if impl is not None:
                return impl(self, *args)
            if name in self.native_types:
                self.unknown[name] = self.unknown.get(name, 0) + 1
                self.inert_calls += 1
                self.last_inert = name
                return DEFAULTS.get(self.native_types[name])
            raise Crash('call to a missing function %s' % name)
        body = self._compiled.get(name)
        if body is None:
            body = self._compiled[name] = self._function(f)
        self.tick()
        self.ops += 2 + len(args)
        return body(args)

    def _function(self, f):
        params = [(t, n) for t, n in f.params]
        local_names = dict((n, t) for t, n in params)
        local_names.update((d.name, d.type) for d in f.locals)
        init_calls = []
        for d in f.locals:
            if d.is_array:
                init_calls.append((d.name, None, True, d.type))
            else:
                init_calls.append((d.name, None if d.initializer is None else self._expr(d.initializer, local_names),
                                   False, d.type))
        body = self._block(f.body, local_names)
        rtype = f.return_type
        arrays = [n for n, _i, is_array, _t in init_calls if is_array]
        if arrays:
            inner, it = body, self

            def body(env):
                try:
                    return inner(env)
                finally:
                    for n in arrays:
                        a = env.get(n)
                        if a:
                            it.kept_chars -= sum(len(v) for v in a.values() if type(v) is str)

        def run(args):
            env = {}
            if len(args) < len(params):
                raise Crash('%s called with %d of %d arguments' % (f.name, len(args), len(params)))
            for (t, n), v in zip(params, args):
                env[n] = _coerce(t, v)
            for n, init, is_array, t in init_calls:
                env[n] = {} if is_array else (UNSET if init is None else _coerce(t, init(env)))
            r = body(env)
            if r == RETURN:
                v = env['\0ret']
                if v is UNSET:
                    raise Crash('read of an uninitialized variable')
                return _coerce(rtype, v)
            return None
        return run

    def _block(self, stmts, local_names):
        pairs = [(self._stmt(s, local_names), _stmt_ops(s)) for s in stmts
                 if not isinstance(s, jass_ast.CommentStmt)]
        pairs = [(f, w) for f, w in pairs if f is not None]
        it = self

        def run(env):
            for f, w in pairs:
                it.ops += w
                r = f(env)
                if r:
                    return r
            return 0
        return run

    def _stmt(self, s, local_names):
        if isinstance(s, jass_ast.DebugStmt):
            return None
        if isinstance(s, jass_ast.SetStmt):
            return self._set(s, local_names)
        if isinstance(s, jass_ast.CallStmt):
            call = self._expr(s.call, local_names)

            def run_call(env):
                call(env)
                return 0
            return run_call
        if isinstance(s, jass_ast.IfStmt):
            branches = [(None if c is None else self._expr(c, local_names), self._block(b, local_names),
                         0 if c is None else _expr_ops(c) + 1) for c, b in s.branches]
            it = self

            def run_if(env):
                for cond, body, w in branches:
                    it.ops += w
                    if cond is None or _truthy(cond(env)):
                        return body(env)
                return 0
            return run_if
        if isinstance(s, jass_ast.LoopStmt):
            body = self._block(s.body, local_names)
            tick = self.tick
            it = self

            def run_loop(env):
                while True:
                    tick()
                    it.ops += 1
                    r = body(env)
                    if r == EXIT:
                        return 0
                    if r == RETURN:
                        return RETURN
            return run_loop
        if isinstance(s, jass_ast.ExitWhenStmt):
            cond = self._expr(s.cond, local_names)
            return lambda env: EXIT if _truthy(cond(env)) else 0
        if isinstance(s, jass_ast.ReturnStmt):
            value = None if s.value is None else self._expr(s.value, local_names)

            def run_return(env):
                env['\0ret'] = None if value is None else value(env)
                return RETURN
            return run_return
        raise JassError('statement %s' % type(s).__name__)

    def _set(self, s, local_names):
        target = s.target
        value = self._expr(s.value, local_names)
        g = self.globals
        if isinstance(target, jass_ast.Name):
            name = target.name
            if name in local_names:
                ltype = local_names[name] if isinstance(local_names, dict) else None

                def set_local(env):
                    env[name] = _coerce(ltype, value(env))
                    return 0
                return set_local
            types = self.global_types

            hold = self.hold

            def set_global(env):
                v = _coerce(types.get(name), value(env))
                old = g.get(name)
                if type(v) is str or type(old) is str:
                    hold(old, v)
                g[name] = v
                return 0
            return set_global
        name = target.base.name
        index = self._expr(target.index, local_names)
        local = name in local_names
        atype = (local_names[name] if isinstance(local_names, dict) else None) if local else self.global_types.get(name)

        def set_index(env):
            i = index(env)
            if not isinstance(i, int) or i < 0 or i >= MAX_ARRAY:
                raise Crash('array index %r' % (i,))
            arr = env[name] if local else g.get(name)
            if not isinstance(arr, dict):
                raise Crash('%s is not an array' % name)
            v = _coerce(atype, value(env))
            old = arr.get(i)
            if type(v) is str or type(old) is str:
                hold(old, v)
            arr[i] = v
            return 0
        hold = self.hold
        return set_index

    def _expr(self, e, local_names):
        if isinstance(e, jass_ast.Literal):
            v = _literal_text(e)
            return lambda env: v
        if isinstance(e, jass_ast.Name):
            name = e.name
            if name in local_names:
                def get_local(env):
                    v = env[name]
                    if v is UNSET:
                        raise Crash('read of the uninitialized local %s' % name)
                    return v
                return get_local
            g = self.globals

            def get_global(env):
                v = g.get(name, UNSET)
                if v is UNSET:
                    raise Crash('read of the uninitialized global %s' % name, name)
                return v
            return get_global
        if isinstance(e, jass_ast.Index):
            name = e.base.name
            index = self._expr(e.index, local_names)
            local = name in local_names
            g = self.globals
            types = self.global_types

            def get_index(env):
                i = index(env)
                if not isinstance(i, int) or i < 0 or i >= MAX_ARRAY:
                    raise Crash('array index %r' % (i,))
                arr = env[name] if local else g.get(name)
                if not isinstance(arr, dict):
                    raise Crash('%s is not an array' % name)
                v = arr.get(i, UNSET)
                if v is UNSET:
                    return DEFAULTS.get(types.get(name)) if not local else 0
                return v
            if local:
                ltype = DEFAULTS.get(local_names[name])

                def get_local_index(env):
                    i = index(env)
                    if not isinstance(i, int) or i < 0 or i >= MAX_ARRAY:
                        raise Crash('array index %r' % (i,))
                    return env[name].get(i, ltype)
                return get_local_index
            return get_index
        if isinstance(e, jass_ast.Call):
            name = e.name
            args = [self._expr(a, local_names) for a in e.args]
            call = self.call
            return lambda env: call(name, [a(env) for a in args])
        if isinstance(e, jass_ast.FuncRef):
            c = Code(e.name)
            return lambda env: c
        if isinstance(e, jass_ast.Paren):
            return self._expr(e.inner, local_names)
        if isinstance(e, jass_ast.Unary):
            inner = self._expr(e.operand, local_names)
            if e.op == 'not':
                return lambda env: not _truthy(inner(env))
            if e.op == '-':
                def neg(env):
                    v = _num(inner(env))
                    return _wrap(-v) if isinstance(v, int) else -v
                return neg
            return inner
        if isinstance(e, jass_ast.Binary):
            left = self._expr(e.left, local_names)
            right = self._expr(e.right, local_names)
            if e.op == 'and':
                return lambda env: _truthy(left(env)) and _truthy(right(env))
            if e.op == 'or':
                return lambda env: _truthy(left(env)) or _truthy(right(env))
            op = _BINARY[e.op]
            return lambda env: op(left(env), right(env))
        raise JassError('expression %s' % type(e).__name__)

    def evaluate(self, expression):
        p = jass_ast._Parser(_script_bytes(expression))
        try:
            e = p.expression(0)
        except jass_ast.JassSyntaxError as x:
            raise JassError('the expression does not parse: %s' % x)
        if p.toks[p.i] != jass_ast._EOF:
            raise JassError('the expression does not end where it should')
        f = self._expr(e, {})
        saved = self.budget, self.steps
        self.deadline = time.time() + min(self.seconds, 10.0)
        self.budget, self.steps = 500000, 0
        try:
            v = f({})
        except RecursionError:
            raise Crash('too deep')
        except _MATH_ERRORS as x:
            raise Crash(str(x))
        finally:
            self.budget, self.steps = saved
        if v is UNSET:
            raise Crash('read of an uninitialized variable')
        return v

    def text(self, expression, rounds=3):
        tried = set()
        for _r in range(rounds + 1):
            try:
                before = self.inert_calls
                v = self.evaluate(expression)
                if self.inert_calls != before:
                    raise JassError('the value depends on the game (%s)' % self.last_inert)
                break
            except Crash as e:
                name = e.global_name
                if name is None or name in tried or _r == rounds:
                    raise
                tried.add(name)
                writers = self.writers(name)
                if not writers:
                    raise
                saved = self.budget, self.steps
                self.budget, self.steps = 300000, 0
                self.deadline = time.time() + min(self.seconds, 10.0)
                try:
                    for w in writers:
                        self.thread(w)
                except Budget:
                    pass
                finally:
                    self.budget, self.steps = saved
        if not isinstance(v, str):
            raise JassError('not a string: %r' % (v,))
        return _bytes_text(v)

    def writers(self, name):
        if not hasattr(self, '_writers'):
            self._writers = {}
            for t in self._trees:
                for f in t.functions:
                    if f.params:
                        continue
                    for n in jass_ast.walk(f):
                        if isinstance(n, jass_ast.SetStmt):
                            target = n.target.base if isinstance(n.target, jass_ast.Index) else n.target
                            self._writers.setdefault(target.name, [])
                            if f.name not in self._writers[target.name]:
                                self._writers[target.name].append(f.name)
        return self._writers.get(name, [])

    def handle_id(self, h):
        if h is None:
            return 0
        k = id(h)
        if k not in self._handle_ids:
            self._handle_ids[k] = (0x100000 + len(self._handle_ids), h)
        return self._handle_ids[k][0]

    def player(self, i):
        if not isinstance(i, int) or i < 0 or i > 27:
            return None
        if i not in self._players:
            self._players[i] = Handle('player', i)
        return self._players[i]


def _s(v):
    return '' if v is None else v


def _sub_text(it, s, a, b):
    if s is None:
        return None
    a = max(0, a)
    b = min(len(s), b)
    return s[a:b] if b > a else ''


def _string_case(it, s, upper):
    if s is None:
        return None
    return ''.join((chr(ord(c) - 32) if upper and 'a' <= c <= 'z' else
                    chr(ord(c) + 32) if not upper and 'A' <= c <= 'Z' else c) for c in s)


_RX_INT = re.compile(r'\s*([+-]?\d+)')
_RX_REAL = re.compile(r'\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)')


def _s2i(it, s):
    m = _RX_INT.match(_s(s))
    return _wrap(int(m.group(1))) if m else 0


def _s2r(it, s):
    m = _RX_REAL.match(_s(s))
    return float(m.group(1)) if m else 0.0


def _string_hash(it, s):
    import sstrhash
    return sstrhash.signed(sstrhash.sstrhash2_bytes(_s(s).encode('latin-1', 'replace')))


def _r2i(it, r):
    return _wrap(int(r)) if math.isfinite(r) else 0


def _r2sw(it, r, width, precision):
    if width > MAX_STRING or precision > 4096:
        raise Crash('R2SW with a width of %d and a precision of %d' % (width, precision))
    return '%*.*f' % (max(0, width), max(0, precision), r)


def _pow(a, b):
    a, b = float(a), float(b)
    if (a == 0.0 and b < 0.0) or (a < 0.0 and not b.is_integer()):
        return 0.0
    try:
        return a ** b
    except (OverflowError, ZeroDivisionError):
        return 0.0


def _for_force(it, force, code):
    if force is None or not isinstance(code, Code):
        return None
    saved = it.enum_player
    for p in list(force.data):
        it.enum_player = p
        it.thread(code.name)
    it.enum_player = saved
    return None


def _force_add(it, force, p):
    if force is not None and p is not None and p not in force.data:
        force.data.append(p)


def _force_remove(it, force, p):
    if force is not None and p in force.data:
        force.data.remove(p)


def _trigger_add_condition(it, t, be):
    if t is None or be is None:
        return None
    t.data['conditions'].append(be)
    return Handle('triggercondition', be)


def _trigger_evaluate(it, t):
    if t is None:
        return False
    ok = True
    for be in list(t.data['conditions']):
        if isinstance(be.data, Code):
            ok = bool(it.thread(be.data.name)) and ok
    return ok


def _trigger_execute(it, t):
    if t is None:
        return None
    for code in list(t.data['actions']):
        it.thread(code.name)


def _execute_func(it, name):
    f = it.functions.get(_s(name))
    if f is not None and not f.params:
        it.thread(f.name)


def _chat_event(it, t, p, s, exact):
    it.chat_events.append((p.data if p is not None else None, _bytes_text(s), bool(exact)))
    it.chat_registrations.append((t, p, s, bool(exact)))
    return Handle('event')


def _timer_start(it, timer, timeout, periodic, code):
    if isinstance(code, Code) and (timeout or 0) <= 0.0 and not periodic:
        it.timers.append(code)
    elif isinstance(code, Code) and 0.0 < (timeout or 0) <= it.early:
        it.early_timers.append((timeout, len(it.early_timers), code))


def _register_timer_event(it, t, timeout, periodic):
    if t is not None and (timeout or 0) <= 0.0 and not periodic:
        it.timers.append(t)
    elif t is not None and 0.0 < (timeout or 0) <= it.early:
        it.early_timers.append((timeout, len(it.early_timers), t))
    return Handle('event')


def _ht_key(kind):
    def save(it, ht, p, c, v):
        if isinstance(ht, Handle):
            if kind == 's':
                it.hold(ht.data.get((kind, p, c)), v)
            ht.data[(kind, p, c)] = v
    def load(it, ht, p, c):
        if isinstance(ht, Handle):
            return ht.data.get((kind, p, c), DEFAULTS.get({'i': 'integer', 'r': 'real', 'b': 'boolean',
                                                           's': 'string'}.get(kind)))
        return DEFAULTS.get({'i': 'integer', 'r': 'real', 'b': 'boolean', 's': 'string'}.get(kind))
    def have(it, ht, p, c):
        return isinstance(ht, Handle) and (kind, p, c) in ht.data
    def remove(it, ht, p, c):
        if isinstance(ht, Handle):
            it.hold(ht.data.pop((kind, p, c), None), None)
    return save, load, have, remove


def _flush_child(it, ht, p):
    if isinstance(ht, Handle):
        for k in [k for k in ht.data if k[1] == p]:
            it.hold(ht.data.pop(k), None)


def _flush_parent(it, ht):
    if isinstance(ht, Handle):
        it.kept_chars -= sum(len(v) for v in ht.data.values() if type(v) is str)
        ht.data.clear()


def _new_trigger(it):
    return Handle('trigger', {'conditions': [], 'actions': []})


NATIVES = {
    'StringLength': lambda it, s: len(_s(s)),
    'SubString': _sub_text,
    'StringCase': _string_case,
    'S2I': _s2i, 'S2R': _s2r,
    'I2S': lambda it, i: str(i),
    'R2S': lambda it, r: '%.3f' % r,
    'R2SW': _r2sw,
    'I2R': lambda it, i: float(i),
    'R2I': _r2i,
    'StringHash': _string_hash,
    'GetHandleId': lambda it, h: it.handle_id(h),
    'Player': lambda it, i: it.player(i),
    'GetLocalPlayer': lambda it: it.player(0),
    'GetPlayerId': lambda it, p: p.data if isinstance(p, Handle) and p.kind == 'player' else -1,
    'GetEnumPlayer': lambda it: it.enum_player,
    'GetTriggerPlayer': lambda it: it.player_trigger,
    'CreateForce': lambda it: Handle('force', []),
    'ForceAddPlayer': _force_add,
    'ForceRemovePlayer': _force_remove,
    'ForceClear': lambda it, f: f.data.clear() if f is not None else None,
    'IsPlayerInForce': lambda it, p, f: f is not None and p in f.data,
    'ForForce': _for_force,
    'GetBJMaxPlayers': lambda it: 24, 'GetBJPlayerNeutralVictim': lambda it: 25,
    'GetBJPlayerNeutralExtra': lambda it: 26, 'GetBJMaxPlayerSlots': lambda it: 28,
    'GetPlayerNeutralPassive': lambda it: 27, 'GetPlayerNeutralAggressive': lambda it: 24,
    'TriggerSleepAction': lambda it, s: it.sleep(),
    'CountPlayersInForceBJ': None,
    'InitHashtable': lambda it: Handle('hashtable', {}),
    'FlushChildHashtable': _flush_child,
    'FlushParentHashtable': _flush_parent,
    'CreateTrigger': _new_trigger,
    'Condition': lambda it, c: Handle('boolexpr', c) if isinstance(c, Code) else None,
    'Filter': lambda it, c: Handle('boolexpr', c) if isinstance(c, Code) else None,
    'TriggerAddCondition': _trigger_add_condition,
    'TriggerAddAction': lambda it, t, c: t.data['actions'].append(c) if t is not None and isinstance(c, Code) else None,
    'TriggerEvaluate': _trigger_evaluate,
    'TriggerExecute': _trigger_execute,
    'TriggerExecuteWait': _trigger_execute,
    'ExecuteFunc': _execute_func,
    'TriggerRegisterPlayerChatEvent': _chat_event,
    'TimerStart': _timer_start,
    'TriggerRegisterTimerEvent': _register_timer_event,
    'GetRandomInt': lambda it, a, b: it.random.randint(min(a, b), max(a, b)),
    'GetRandomReal': lambda it, a, b: it.random.uniform(min(a, b), max(a, b)),
    'SquareRoot': lambda it, r: math.sqrt(r) if r > 0 else 0.0,
    'Pow': lambda it, a, b: _pow(a, b),
    'Sin': lambda it, r: math.sin(r), 'Cos': lambda it, r: math.cos(r), 'Tan': lambda it, r: math.tan(r),
    'Asin': lambda it, r: math.asin(max(-1.0, min(1.0, r))), 'Acos': lambda it, r: math.acos(max(-1.0, min(1.0, r))),
    'Atan': lambda it, r: math.atan(r), 'Atan2': lambda it, y, x: math.atan2(y, x),
    'Deg2Rad': lambda it, r: math.radians(r), 'Rad2Deg': lambda it, r: math.degrees(r),
    'BlzBitAnd': lambda it, a, b: _wrap(a & b), 'BlzBitOr': lambda it, a, b: _wrap(a | b),
    'BlzBitXor': lambda it, a, b: _wrap(a ^ b),
}
del NATIVES['CountPlayersInForceBJ']
for _kind, _names in (('i', ('Integer', 'Integer')), ('r', ('Real', 'Real')), ('b', ('Boolean', 'Boolean')),
                      ('s', ('Str', 'String'))):
    _save, _load, _have, _remove = _ht_key(_kind)
    NATIVES['Save' + _names[0]] = _save
    NATIVES['Load' + _names[0]] = _load
    NATIVES['HaveSaved' + _names[1]] = _have
    NATIVES['RemoveSaved' + _names[1]] = _remove
_save_h, _load_h, _have_h, _remove_h = _ht_key('h')
NATIVES['HaveSavedHandle'] = _have_h
NATIVES['RemoveSavedHandle'] = _remove_h


def _handle_natives(native_types):
    for name in native_types:
        if name.startswith('Save') and name.endswith('Handle') and name not in NATIVES:
            NATIVES[name] = _save_h
        elif name.startswith('Load') and name.endswith('Handle') and name not in NATIVES:
            NATIVES[name] = _load_h


def libraries():
    try:
        import triggerdata
        return [triggerdata.game_script('common.j'), triggerdata.game_script('blizzard.j')]
    except Exception:
        return []


def run(script, budget=3000000, seconds=30.0, libs=None, entries=('config', 'main'), natives=None):
    if sys.getrecursionlimit() < 20000:
        sys.setrecursionlimit(20000)
    it = Interpreter(script, libraries() if libs is None else libs, budget, seconds, natives=natives)
    _handle_natives(it.native_types)
    it.stopped = None
    try:
        it.start(entries)
    except Budget as e:
        it.stopped = str(e)
    return it
