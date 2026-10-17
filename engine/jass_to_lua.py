# Converts a JASS map script to Lua with the same behavior, and sets the Lua flag of the map.
import os

import jass_ast
import lua_ast


DEFAULT_REF = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref', '3.0'))
LOLER = {'!=': '~='}
HELPERS = frozenset(('FourCC', 'JDiv', 'JCat', '__jarray'))
LIBRARY = frozenset(('_G', '_ENV', '_VERSION', 'assert', 'collectgarbage', 'coroutine', 'debug', 'dofile', 'error',
                     'getmetatable', 'io', 'ipairs', 'load', 'loadfile', 'math', 'next', 'os', 'package', 'pairs',
                     'pcall', 'print', 'rawequal', 'rawget', 'rawlen', 'rawset', 'require', 'select',
                     'setmetatable', 'string', 'table', 'tonumber', 'tostring', 'type', 'utf8', 'xpcall'))
FORBIDDEN = lua_ast.KEYWORDS | HELPERS | LIBRARY
LOCALS_LIMIT = 150
CONCAT_GROUP = 32
NEVER_NULL = frozenset(('I2S', 'R2S', 'R2SW'))
def signatures(paths, strict=False):
    ret, glob, params = {}, {}, {}
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
        for d in s.globals:
            glob[d.name] = d.type
    return ret, glob, params


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
            python_time = self.types.params.get(e.name) or ()
            args = [self.as_real(a) if i < len(python_time) and python_time[i] == 'real' else self.expr(a)
                    for i, a in enumerate(e.args)]
            if e.name == 'ExecuteFunc' and len(e.args) == 1 and type(e.args[0]) is jass_ast.Literal \
                    and e.args[0].kind == 'string' and e.args[0].value in self.func_list \
                    and e.args[0].value in self.name_list:
                args = [_quote(self.name_list[e.args[0].value])]
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
            real = self.types.expr_node(s.target, self.local_vars) == 'real'
            return [evidence + '%s = %s' % (tgt, self.as_real(s.value) if real else self.expr(s.value))]
        if t is jass_ast.CallStmt:
            return [evidence + self.expr(s.call)]
        if t is jass_ast.IfStmt:
            out = []
            for i, (cond, block_body) in enumerate(s.branches):
                head_line = ('if %s then' % self.expr(cond)) if cond is not None else 'else'
                if i:
                    head_line = ('elseif %s then' % self.expr(cond)) if cond is not None else 'else'
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
            return [evidence + 'return ' + (self.as_real(s.value) if self.retorno == 'real' else self.expr(s.value))]
        if t is jass_ast.DebugStmt:
            return self.decl(s.stmt, level)
        raise TypeError('in JASS: %r' % (s,))


def converte(body_text, ref=None, log=print):
    script = jass_ast.parse(body_text)
    ref = ref or DEFAULT_REF
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
            field_value = tr.as_real(d.initializer) if d.type == 'real' else tr.expr(d.initializer)
            line_list.append('%s = %s' % (fname, field_value))
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
                field_value = tr.as_real(d.initializer) if d.type == 'real' else tr.expr(d.initializer)
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
               'without_type': tr.without_type[:5], 'gates': {'G0 ref': 'ok (common.j and blizzard.j from %s)' % ref}}
    try:
        lua_ast.parse(output)
    except lua_ast.LuaSyntaxError as e:
        raise SystemExit('ABORT (G1): the output does not parse as Lua (line %d): %s' % (e.line, e.message))
    details['gates']['G1 parse'] = 'ok (the output parses as Lua 5.3)'
    if tr.without_type:
        raise SystemExit(
            'ABORT (G2): %d `+`/`/` without a resolved type (a native without a signature? a name that nobody'
            ' declares?): lines %s' % (len(tr.without_type), tr.without_type[:5])
        )
    details['gates']['G2 types'] = 'ok (%d string `..`, %d number `+`, %d integer JDiv)' % (
        tr.concatenations, tr.numerics, tr.integer_divisions)
    details['ok'] = True
    log(
        'JASS_TO_LUA: %d function(s), %d globals, %d native(s); %d `..`, %d `+`, %d JDiv, %d integer(s) as real,'
        ' %d name(s) renamed, %d function(s) with their locals in a table; %s'
        % (
            n_funcs,
            n_globals,
            len(script.natives),
            tr.concatenations,
            tr.numerics,
            tr.integer_divisions,
            tr.real_blocks,
            len(name_list),
            n_table,
            '; '.join(details['gates'].values()),
        )
    )
    return output, details


def w3i_lua(data_bytes):
    import w3i
    if data_bytes is None:
        raise SystemExit('ABORT: the map has no war3map.w3i (the game picks the script by its flag)')
    try:
        m = w3i.parse(data_bytes)
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
    return new, 'version %d -> %d, script_language %s -> 1' % (before[0], ver, before[1])
