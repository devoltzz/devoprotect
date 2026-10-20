# Converts a JASS map script to Lua with the same behavior, and sets the Lua flag of the map.
import os
import re

import jass_ast
import lua_ast


DEFAULT_REF = next(
    (
        p
        for p in (
            os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref', '3.0')),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ref', '3.0'),
        )
        if os.path.isfile(os.path.join(p, 'common.j'))
    ),
    os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref', '3.0')),
)
LOLER = {'!=': '~='}
HELPERS = frozenset(('FourCC', 'JDiv', 'JCat', 'JEq', '__jarray'))
LIBRARY = frozenset(('_G', '_ENV', '_VERSION', 'assert', 'collectgarbage', 'coroutine', 'debug', 'dofile', 'error',
                     'getmetatable', 'io', 'ipairs', 'load', 'loadfile', 'math', 'next', 'os', 'package', 'pairs',
                     'pcall', 'print', 'rawequal', 'rawget', 'rawlen', 'rawset', 'require', 'select',
                     'setmetatable', 'string', 'table', 'tonumber', 'tostring', 'type', 'utf8', 'xpcall'))
FORBIDDEN = lua_ast.KEYWORDS | HELPERS | LIBRARY
LOCALS_LIMIT = 150
CONCAT_GROUP = 32
NEVER_NULL = frozenset(('I2S', 'R2S', 'R2SW'))
ZEROS = {'integer': '0', 'real': '0.0', 'boolean': 'false'}
REAL_TOLERANCE = '0.001'
COMPARISONS = ('==', '!=', '<', '<=', '>', '>=')
def signatures(paths, strict=False):
    ret, glob, params, native_params = {}, {}, {}, {}
    for c in paths:
        if not (c and os.path.isfile(c)):
            if strict:
                raise SystemExit(
                    'ABORT: %s is missing (the reference folder must have common.j and blizzard.j from the game)' % c
                )
            continue
        try:
            s = jass_ast.parse(open(c, 'r', encoding='utf-8', errors='surrogateescape').read())
        except Exception as e:
            if strict:
                raise SystemExit('ABORT: %s does not parse (%s)' % (c, str(e)[:120]))
            continue
        for f in s.function_index.values():
            ret[f.name] = f.return_type
        for f in s.functions:
            params[f.name] = [t for t, _n in f.params]
        for f in s.natives:
            native_params[f.name] = [t for t, _n in f.params]
        for d in s.globals:
            glob[d.name] = d.type
    return ret, glob, params, native_params


def ref_file(folder, fname):
    try:
        for n in os.listdir(folder):
            if n.lower() == fname:
                return os.path.join(folder, n)
    except OSError:
        pass
    return os.path.join(folder, fname)


def renomeia(script, ref_names=()):
    defined = set(d.name for d in script.globals)
    for f in script.functions:
        defined.add(f.name)
        defined.update(n for _t, n in f.params)
        defined.update(d.name for d in f.locals)
    in_use = defined | set(ref_names) | FORBIDDEN
    out = {}
    for n in sorted(defined & FORBIDDEN):
        new = n + '_'
        while new in in_use:
            new += '_'
        in_use.add(new)
        out[n] = new
    return out


class Types(object):
    def __init__(self, script, ref_signatures):
        if not isinstance(ref_signatures, tuple):
            ref_signatures = (ref_signatures, {}, {})
        ref_ret, ref_glob = ref_signatures[:2]
        ref_params = ref_signatures[2] if len(ref_signatures) > 2 else {}
        self.native_params = dict(ref_signatures[3] if len(ref_signatures) > 3 else {})
        for f in script.natives:
            self.native_params[f.name] = [t for t, _n in f.params]
        self.ret = dict(ref_ret)
        for f in script.function_index.values():
            self.ret[f.name] = f.return_type
        self.params = dict(ref_params)
        for f in script.function_index.values():
            if f.is_native:
                self.params.pop(f.name, None)
            else:
                self.params[f.name] = [t for t, _n in f.params]
        self.globals_block = dict(ref_glob)
        self.globals_block.update((d.name, d.type) for d in script.globals)
        self.script = script

    def of_function(self, func):
        local_vars = dict((d.name, d.type) for d in func.locals)
        for t, n in func.params:
            local_vars[n] = t
        return local_vars

    def expr_node(self, e, local_vars):
        t = type(e)
        if t is jass_ast.Literal:
            if e.kind in ('string',):
                return 'string'
            if e.kind in ('integer', 'real'):
                return e.kind
            if e.kind == 'null':
                return 'null'
            if e.kind == 'boolean':
                return 'boolean'
            if e.kind == 'rawcode':
                return 'integer'
            return 'handle'
        if t is jass_ast.Name:
            if e.name in local_vars:
                return local_vars[e.name]
            return self.globals_block.get(e.name)
        if t is jass_ast.Index:
            return self.expr_node(e.base, local_vars)
        if t is jass_ast.Call:
            return self.ret.get(e.name)
        if t is jass_ast.FuncRef:
            return 'code'
        if t is jass_ast.Unary:
            return 'boolean' if e.op == 'not' else self.expr_node(e.operand, local_vars)
        if t is jass_ast.Binary:
            if e.op in ('and', 'or'):
                return 'boolean'
            if e.op in ('==', '!=', '<', '<=', '>', '>='):
                return 'boolean'
            lhs, dir = self.expr_node(e.left, local_vars), self.expr_node(e.right, local_vars)
            for type_name in ('string', 'real'):
                if type_name in (lhs, dir):
                    return type_name
            return lhs or dir
        if t is jass_ast.Paren:
            return self.expr_node(e.inner, local_vars)
        return None


def _quote(field_value):
    out = ['"']
    for ch in field_value:
        o = ord(ch)
        if ch == '"' or ch == '\\':
            out.append('\\' + ch)
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif 32 <= o < 127:
            out.append(ch)
        else:
            b = ch.encode('utf-8', 'surrogateescape') if o > 127 else ch.encode('latin-1')
            for x in b:
                out.append('\\%03d' % x)
    out.append('"')
    return ''.join(out)


class Translator(object):
    def __init__(self, types, name_list=None):
        self.types = types
        self.name_list = name_list or {}
        self.func_list = set(f.name for f in types.script.functions)
        self.local_vars = {}
        self.retorno = None
        self.in_table = set()
        self.concatenations = 0
        self.numerics = 0
        self.integer_divisions = 0
        self.real_blocks = 0
        self.without_type = []
        self.fourcc = False
        self.jarray = False
        self.jcat = False
        self.mid_returns = 0
        self.unary_pluses = 0
        self.real_eqs = 0
        self.jeq = False
        self.numeric_nulls = 0
        self.debugs = 0

    def fname(self, n):
        if n in self.in_table:
            return '__l.' + self.name_list.get(n, n)
        return self.name_list.get(n, n)

    def as_real(self, e):
        if self.types.expr_node(e, self.local_vars) != 'integer':
            return self.expr(e)
        self.real_blocks += 1
        if type(e) is jass_ast.Literal and e.kind in ('integer', 'rawcode'):
            v = e.value
            return ('%d.0' % v) if v >= 0 else '(%d.0)' % v
        return '(%s + 0.0)' % self.child(e, lua_ast.BINARY_PRIORITY['+'][0], True)

    def field_value(self, e, type_name):
        if type_name in ZEROS and self.types.expr_node(e, self.local_vars) == 'null':
            self.numeric_nulls += 1
            return ZEROS[type_name]
        if type_name == 'real':
            return self.as_real(e)
        return self.expr(e)

    def comparison(self, e):
        types = [self.types.expr_node(e.left, self.local_vars), self.types.expr_node(e.right, self.local_vars)]
        if None in types:
            other = types[1] if types[0] is None else types[0]
            if other in ('integer', 'real', 'null', None):
                self.without_type.append(e.line or 0)
            return None
        texts = [None, None]
        for i in (0, 1):
            if types[i] == 'null' and types[1 - i] in ZEROS:
                self.numeric_nulls += 1
                texts[i] = ZEROS[types[1 - i]]
                types[i] = types[1 - i]
        sides = (e.left, e.right)
        if e.op == '==' and 'real' in types and set(types) <= {'real', 'integer'}:
            self.real_eqs += 1
            self.jeq = True
            return 'JEq(%s, %s)' % tuple(self.expr(sides[i]) if texts[i] is None else texts[i] for i in (0, 1))
        if texts == [None, None]:
            return None
        op = LOLER.get(e.op, e.op)
        lp, rp = lua_ast.BINARY_PRIORITY[op]
        return '%s %s %s' % (self.child(e.left, lp, True) if texts[0] is None else texts[0], op,
                             self.child(e.right, rp, False) if texts[1] is None else texts[1])

    def _is_concat(self, e):
        if type(e) is not jass_ast.Binary or e.op != '+':
            return False
        lhs, dir = self.types.expr_node(e.left, self.local_vars), self.types.expr_node(e.right, self.local_vars)
        return lhs is not None and dir is not None and 'string' in (lhs, dir)

    def _terms(self, e):
        out, stack = [], [e]
        while stack:
            x = stack.pop()
            y = x
            while type(y) is jass_ast.Paren:
                y = y.inner
            if self._is_concat(y):
                self.concatenations += 1
                stack.append(y.right)
                stack.append(y.left)
            else:
                out.append(x)
        return out

    @staticmethod
    def _never_nil(e):
        while type(e) is jass_ast.Paren:
            e = e.inner
        t = type(e)
        return (t is jass_ast.Literal and e.kind == 'string') or (t is jass_ast.Call and e.name in NEVER_NULL)

    def concat(self, e):
        terms = self._terms(e)
        if any(self._never_nil(t) for t in terms):
            pieces = []
            for t in terms:
                if self._never_nil(t):
                    pieces.append(self.expr(t))
                elif type(t) is jass_ast.Literal and t.kind == 'null':
                    pieces.append('""')
                else:
                    pieces.append('(%s or "")' % self.expr(t))
            while len(pieces) > CONCAT_GROUP:
                pieces = ['(%s)' % ' .. '.join(pieces[i:i + CONCAT_GROUP]) for i in range(0, len(pieces), CONCAT_GROUP)]
            return ' .. '.join(pieces)
        self.jcat = True
        pieces = [self.expr(t) for t in terms]
        while len(pieces) > CONCAT_GROUP:
            pieces = ['JCat(%s)' % ', '.join(pieces[i:i + CONCAT_GROUP]) for i in range(0, len(pieces), CONCAT_GROUP)]
        return 'JCat(%s)' % ', '.join(pieces)

    @staticmethod
    def _integer(v):
        if v >= 0:
            return str(v)
        if v == -2 ** 31:
            return '(-2147483647 - 1)'
        return '(%d)' % v

    def array_value(self, type_name):
        default_value = {'integer': '0', 'real': '0.0', 'boolean': 'false'}.get(type_name)
        if default_value is None:
            return '{}'
        self.jarray = True
        return '__jarray(%s)' % default_value

    def expr(self, e, level=0):
        t = type(e)
        if t is jass_ast.Name:
            return self.fname(e.name)
        if t is jass_ast.Index:
            return '%s[%s]' % (self.expr(e.base), self.expr(e.index))
        if t is jass_ast.Call:
            python_time = self.types.params.get(e.name)
            tn = () if python_time is not None else (self.types.native_params.get(e.name) or ())
            args = []
            for i, a in enumerate(e.args):
                if python_time is not None and i < len(python_time):
                    args.append(self.field_value(a, python_time[i]))
                elif i < len(tn) and tn[i] in ZEROS and self.types.expr_node(a, self.local_vars) == 'null':
                    self.numeric_nulls += 1
                    args.append(ZEROS[tn[i]])
                else:
                    args.append(self.expr(a))
            if e.name == 'ExecuteFunc' and len(e.args) == 1 and type(e.args[0]) is jass_ast.Literal \
                    and e.args[0].kind == 'string' and e.args[0].value in self.func_list \
                    and e.args[0].value in self.name_list:
                args = [_quote(self.name_list[e.args[0].value])]
            if e.name == 'TriggerRegisterVariableEvent' and len(e.args) > 1 and type(e.args[1]) is jass_ast.Literal \
                    and e.args[1].kind == 'string' and e.args[1].value in self.name_list:
                args[1] = _quote(self.name_list[e.args[1].value])
            return '%s(%s)' % (self.name_list.get(e.name, e.name), ', '.join(args))
        if t is jass_ast.FuncRef:
            return self.name_list.get(e.name, e.name)
        if t is jass_ast.Literal:
            if e.kind == 'string':
                return _quote(e.value)
            if e.kind == 'rawcode':
                block_body = e.text[1:-1]
                if len(block_body) == 4 and all(32 <= ord(c) < 127 and c not in '\\\'' for c in block_body):
                    self.fourcc = True
                    return 'FourCC(%s)' % _quote(block_body)
                return self._integer(e.value)
            if e.kind == 'null':
                return 'nil'
            if e.kind == 'boolean':
                return e.text
            if e.kind == 'integer':
                return self._integer(e.value)
            return e.text
        if t is jass_ast.Unary:
            if e.op == 'not':
                return 'not ' + self.child(e.operand, 12, True)
            if e.op == '+':
                self.unary_pluses += 1
                return self.child(e.operand, 12, True)
            return '- ' + self.child(e.operand, 12, True)
        if t is jass_ast.Binary:
            op = LOLER.get(e.op, e.op)
            if e.op == '+':
                lhs, dir = self.types.expr_node(e.left, self.local_vars), self.types.expr_node(e.right, self.local_vars)
                if lhs is None or dir is None:
                    self.without_type.append(e.line or 0)
                elif lhs == 'string' or dir == 'string':
                    return self.concat(e)
                else:
                    self.numerics += 1
            elif e.op in COMPARISONS:
                cmp = self.comparison(e)
                if cmp is not None:
                    return cmp
            elif e.op == '/':
                lhs, dir = self.types.expr_node(e.left, self.local_vars), self.types.expr_node(e.right, self.local_vars)
                if lhs is None or dir is None:
                    self.without_type.append(e.line or 0)
                elif lhs == 'integer' and dir == 'integer':
                    self.integer_divisions += 1
                    return 'JDiv(%s, %s)' % (self.expr(e.left), self.expr(e.right))
            lp, rp = lua_ast.BINARY_PRIORITY[op]
            return '%s %s %s' % (self.child(e.left, lp, True), op, self.child(e.right, rp, False))
        if t is jass_ast.Paren:
            return '(' + self.expr(e.inner) + ')'
        raise TypeError('in JASS: %r' % (e,))

    def child(self, e, precedence, left_operand):
        s = self.expr(e)
        t = type(e)
        if t is jass_ast.Binary:
            lp, rp = lua_ast.BINARY_PRIORITY[LOLER.get(e.op, e.op)]
            if lp < precedence or (not left_operand and rp <= precedence):
                return '(' + s + ')'
        elif t is jass_ast.Unary and precedence > 12:
            return '(' + s + ')'
        return s

    def block_body(self, stmts, level):
        out = []
        real_blocks = [i for i, s in enumerate(stmts) if type(s) is not jass_ast.CommentStmt]
        last = real_blocks[-1] if real_blocks else -1
        for i, s in enumerate(stmts):
            line_list = self.decl(s, level)
            if type(s) is jass_ast.ReturnStmt and i != last:
                evidence = '    ' * level
                line_list = [evidence + 'do ' + line_list[0][len(evidence):] + ' end']
                self.mid_returns += 1
            out.extend(line_list)
        return out

    def decl(self, s, level=0):
        evidence = '    ' * level
        t = type(s)
        if t is jass_ast.CommentStmt:
            return [evidence + '-- ' + s.text[2:].strip()]
        if t is jass_ast.SetStmt:
            tgt = self.expr(s.target)
            return [
                evidence + '%s = %s' % (tgt, self.field_value(s.value, self.types.expr_node(s.target, self.local_vars)))
            ]
        if t is jass_ast.CallStmt:
            return [evidence + self.expr(s.call)]
        if t is jass_ast.IfStmt:
            out = []
            for i, (cond, block_body) in enumerate(s.branches):
                if cond is None:
                    head_line = 'else'
                else:
                    head_line = ('elseif %s then' if i else 'if %s then') % self.expr(cond)
                out.append(evidence + head_line)
                out.extend(self.block_body(block_body, level + 1))
            out.append(evidence + 'end')
            return out
        if t is jass_ast.LoopStmt:
            out = [evidence + 'while true do']
            out.extend(self.block_body(s.body, level + 1))
            out.append(evidence + 'end')
            return out
        if t is jass_ast.ExitWhenStmt:
            return [evidence + 'if %s then break end' % self.expr(s.cond)]
        if t is jass_ast.ReturnStmt:
            if s.value is None:
                return [evidence + 'return']
            return [evidence + 'return ' + self.field_value(s.value, self.retorno)]
        if t is jass_ast.DebugStmt:
            self.debugs += 1
            return [evidence + 'if _DEBUG then'] + self.decl(s.stmt, level + 1) + [evidence + 'end']
        raise TypeError('in JASS: %r' % (s,))


MAP_OWN_FILES = ('Scripts\\Blizzard.j', 'Scripts\\common.j')
RX_NATIVE_DECL = re.compile(r'(?m)^\s*(?:constant\s+)?native\s+(\w+)')
WAITS = frozenset(('TriggerSleepAction', 'PolledWait', 'TriggerWaitForSound', 'WaitForSoundBJ'))
NOT_CALLBACK = frozenset(('TriggerAddAction', 'ExecuteFunc'))
NULLABLE_TYPES = frozenset(('boolexpr', 'conditionfunc', 'filterfunc', 'code'))
GAME_CASES = (
    ('variable_event', 'TriggerRegisterVariableEvent (in Lua the event fires only on a write through `globals.<name>`; '
                       'this conversion writes the plain global)'),
    ('null_string_to_native', 'null literal passed to a string native (JASS reads ""; the Lua natives raise "string '
                              'expected, got nil")'),
    ('null_handle_to_native', 'null literal passed to a handle native (JASS returns the default; in Lua some do, '
                              'others may stop the thread)'),
    ('substring', 'SubString (past the end, and of "": null in JASS, "" in Lua)'),
    ('r2i_of_real_math', 'R2I of real math with a real literal (the Lua real rounds differently: '
                         'R2I(5 * (1 - (6.0 * 0.1))) is 1 in JASS and 2 in Lua)'),
)


def map_blizzard(ler):
    for fname in MAP_OWN_FILES:
        try:
            if ler(fname):
                return fname
        except Exception:
            pass
    return None


def game_natives(ref):
    out = set()
    for fname in ('common.j', 'common.ai'):
        p = ref_file(ref, fname)
        if os.path.isfile(p):
            with open(p, encoding='utf-8', errors='replace') as f:
                out |= set(RX_NATIVE_DECL.findall(f.read()))
    return out


def waits_in_callbacks(script):
    called, expect, passed_to = {}, set(), {}
    for f in script.functions:
        tgt = called.setdefault(f.name, set())
        for n in jass_ast.walk(f):
            if type(n) is not jass_ast.Call:
                continue
            if n.name in WAITS:
                expect.add(f.name)
            tgt.add(n.name)
            if n.name not in NOT_CALLBACK:
                for x in n.args:
                    while type(x) is jass_ast.Paren:
                        x = x.inner
                    if type(x) is jass_ast.FuncRef:
                        passed_to.setdefault(x.name, set()).add(n.name)
    changed = True
    while changed:
        changed = False
        for f, targets in called.items():
            if f not in expect and targets & expect:
                expect.add(f)
                changed = True
    return dict((f, sorted(v)) for f, v in sorted(passed_to.items()) if f in expect)


def game_cases(script, types):
    out = dict((k, 0) for k, _t in GAME_CASES)
    event_names = set()
    for f in script.functions:
        loc = types.of_function(f)
        for n in jass_ast.walk(f):
            if type(n) is not jass_ast.Call:
                continue
            if n.name in types.native_params and n.name not in types.params:
                for t, a in zip(types.native_params[n.name], n.args):
                    if types.expr_node(a, loc) != 'null':
                        continue
                    if t == 'string':
                        out['null_string_to_native'] += 1
                    elif t not in ZEROS and t not in NULLABLE_TYPES:
                        out['null_handle_to_native'] += 1
            if n.name == 'SubString':
                out['substring'] += 1
            elif n.name == 'TriggerRegisterVariableEvent':
                out['variable_event'] += 1
                x = n.args[1] if len(n.args) > 1 else None
                while type(x) is jass_ast.Paren:
                    x = x.inner
                if type(x) is jass_ast.Literal and x.kind == 'string':
                    event_names.add(x.value)
            elif n.name == 'R2I' and n.args:
                nodes = list(jass_ast.walk(n.args[0]))
                if any(type(m) is jass_ast.Binary and m.op in ('+', '-', '*', '/') for m in nodes) and \
                        any(type(m) is jass_ast.Literal and m.kind == 'real' for m in nodes):
                    out['r2i_of_real_math'] += 1
    out['event_variables'] = sorted(event_names)
    return out


def waits_warning(waits):
    if not waits:
        return ''
    return (
        '%d function(s) with a wait (TriggerSleepAction/PolledWait) called back outside the trigger thread: '
        '%s. In JASS the wait there ends the thread; in Lua the callback cannot yield and the wait raises an error: in both, the code '
        'after it does not run'
        % (len(waits), ', '.join('%s (by %s)' % (f, '/'.join(v)) for f, v in list(waits.items())[:6]))
    )


def game_cases_warning(cases):
    pieces = ['%d %s' % (cases[k], t) for k, t in GAME_CASES if cases.get(k)]
    if not pieces:
        return ''
    return 'what only the game decides (the in-game probe measures it; none of it was changed): ' + '; '.join(pieces)


def converte(body_text, ref=None, log=print):
    script = jass_ast.parse(body_text)
    ref = ref or DEFAULT_REF
    game = game_natives(ref)
    outside = sorted(set(f.name for f in script.natives) - game)
    if outside:
        raise SystemExit(
            'ABORT: the script declares %d native(s) the game does not have (platform ones: %s%s); in Lua they '
            'do not exist and the map would break'
            % (len(outside), ', '.join(outside[:8]), '...' if len(outside) > 8 else '')
        )
    sig = signatures([ref_file(ref, 'common.j'), ref_file(ref, 'blizzard.j')], strict=True)
    types = Types(script, sig)
    name_list = renomeia(script, set(sig[0]) | set(sig[1]))
    tr = Translator(types, name_list)
    line_list = []
    n_table = 0

    n_globals = 0
    for d in script.globals:
        n_globals += 1
        fname = tr.fname(d.name)
        if d.is_array:
            line_list.append('%s = %s' % (fname, tr.array_value(d.type)))
        elif d.initializer is not None:
            tr.local_vars = {}
            line_list.append('%s = %s' % (fname, tr.field_value(d.initializer, d.type)))
        elif d.type in ('integer', 'real'):
            line_list.append('%s = %s' % (fname, '0.0' if d.type == 'real' else '0'))
        elif d.type == 'boolean':
            line_list.append('%s = false' % fname)
    n_funcs = 0
    for item in script.functions:
        n_funcs += 1
        tr.in_table = set()
        params = ', '.join(tr.fname(n) for _t, n in item.params)
        line_list.append('function %s(%s)' % (tr.fname(item.name), params))
        tr.local_vars = types.of_function(item)
        tr.retorno = item.return_type
        if len(item.params) + len(item.locals) > LOCALS_LIMIT:
            tr.in_table = set(d.name for d in item.locals) - set(n for _t, n in item.params)
            n_table += 1
            line_list.append('    local __l = {}')
        for d in item.locals:
            if d.is_array:
                field_value = tr.array_value(d.type)
            elif d.initializer is not None:
                field_value = tr.field_value(d.initializer, d.type)
            else:
                field_value = None
            if d.name in tr.in_table:
                if field_value is not None:
                    line_list.append('    %s = %s' % (tr.fname(d.name), field_value))
            else:
                line_list.append(
                    '    local %s' % tr.fname(d.name) + ('' if field_value is None else ' = ' + field_value)
                )
        line_list.extend(tr.block_body(item.body, 1))
        line_list.append('end')
        line_list.append('')
    tr.in_table = set()
    if tr.jcat:
        line_list.insert(
            0,
            'JCat = JCat or function(...) local r for i = 1, select("#", ...) do local v = select(i, ...)'
            ' if v ~= nil then r = (r or "") .. v end end return r end',
        )
    if tr.jeq:
        line_list.insert(0, 'JEq = JEq or function(a, b) return math.abs(a - b) < %s end' % REAL_TOLERANCE)
    if tr.integer_divisions:
        line_list.insert(0, 'JDiv = JDiv or function(a, b) local q = a // b if q < 0 and q * b ~= a then q = q + 1 end'
                            ' return q end')
    if tr.jarray:
        line_list.insert(0, '__jarray = __jarray or function(d) return setmetatable({}, {__index = function() return d'
                            ' end}) end')
    if tr.fourcc:
        line_list.insert(0, 'FourCC = FourCC or function(s) local n = 0 for i = 1, 4 do'
                            ' n = n * 256 + string.byte(s, i) end return n end')
    output = '\n'.join(line_list).rstrip('\n') + '\n'
    details = {'ok': False, 'func_list': n_funcs, 'globals_block': n_globals, 'natives': len(script.natives),
               'concatenations': tr.concatenations, 'numerics': tr.numerics,
               'integer_divisions': tr.integer_divisions, 'rawcode': tr.fourcc, 'arrays_with_default': tr.jarray,
               'mid_returns': tr.mid_returns, 'integers_as_real': tr.real_blocks, 'concat_with_null': tr.jcat,
               'renamed': dict(name_list), 'functions_with_table_locals': n_table,
               'unary_pluses': tr.unary_pluses, 'real_equalities': tr.real_eqs, 'numeric_nulls': tr.numeric_nulls,
               'debugs': tr.debugs,
               'without_type': tr.without_type[:5], 'gates': {'G0 ref': 'ok (common.j and blizzard.j from %s)' % ref}}
    details['waits_in_callbacks'] = waits_in_callbacks(script)
    if details['waits_in_callbacks']:
        log('WARNING: ' + waits_warning(details['waits_in_callbacks']))
    details['game_cases'] = game_cases(script, types)
    if game_cases_warning(details['game_cases']):
        log('WARNING: ' + game_cases_warning(details['game_cases']))
    try:
        lua_ast.parse(output)
    except lua_ast.LuaSyntaxError as e:
        raise SystemExit('ABORT (G1): the output does not parse as Lua (line %d): %s' % (e.line, e.message))
    details['gates']['G1 parse'] = 'ok (the output parses as Lua 5.3)'
    if tr.without_type:
        raise SystemExit(
            'ABORT (G2): %d `+`/`/`/comparison without a resolved type (a native without a signature? a name that'
            ' nobody declares?): lines %s' % (len(tr.without_type), tr.without_type[:5])
        )
    details['gates']['G2 types'] = 'ok (%d string `..`, %d number `+`, %d integer JDiv, %d real JEq)' % (
        tr.concatenations, tr.numerics, tr.integer_divisions, tr.real_eqs)
    details['ok'] = True
    log('JASS_TO_LUA: %d function(s), %d globals, %d native(s); %d `..`, %d `+`, %d JDiv, %d JEq, %d integer(s) as'
        ' real, %d numeric null(s), %d unary `+`, %d debug, %d name(s) renamed, %d function(s) with their'
        ' locals in a table; %s' % (
            n_funcs, n_globals, len(script.natives), tr.concatenations, tr.numerics, tr.integer_divisions, tr.real_eqs,
            tr.real_blocks, tr.numeric_nulls, tr.unary_pluses, tr.debugs, len(name_list), n_table,
            '; '.join(details['gates'].values())))
    return output, details


def w3i_lua(data_bytes):
    import w3i
    if data_bytes is None:
        raise SystemExit('ABORT: the map has no war3map.w3i (the game picks the script by its flag)')
    try:
        m, deviations = w3i.parse_lossless(data_bytes)
    except Exception as e:
        raise SystemExit('ABORT: war3map.w3i does not read (%s): the Lua flag cannot be set' % str(e)[:80])
    ver = max(m['version'], 28)
    before = (m['version'], m.get('script_language'))
    m['script_language'] = 1
    if 'game_version' not in m:
        m['game_version'] = [1, 31, 1, 12173]
    new = w3i.write(m, ver)
    m2 = w3i.parse(new)
    if m2.get('script_language') != 1 or m2['version'] != ver:
        raise SystemExit('ABORT: the rewritten w3i did not get the Lua flag (%s)' % m2.get('script_language'))
    return new, 'version %d -> %d, script_language %s -> 1%s' % (
        before[0],
        ver,
        before[1],
        ('; the cut end of the w3i (%s) comes back with the counts at 0' % ', '.join(deviations)) if deviations else '',
    )
