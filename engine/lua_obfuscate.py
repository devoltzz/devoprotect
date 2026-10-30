# Obfuscates a Lua map script: names renamed, strings encoded, loaded by small loader layers.
import base64
import hashlib
import os
import random
import re
import sys
import time

import lua_ast


ALPHABET_B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
LEHMER = 65537
KEY_LEN_MIN, KEY_LEN_MAX = 17, 61
LOADER = (
    'local %(K)s={} local %(S)s=%(seed)d '
    'for %(I)s=1,%(hash_key)d do %(S)s=(%(S)s*75+74)%%65537 local %(B)s=%(S)s%%256 if %(B)s==0 then %(B)s=1 end'
    ' %(K)s[%(I)s]=%(B)s end '
    'local %(P)s="%(payload)s" '
    'local %(A)s="%(alphabet)s" '
    'local %(X)s={} for %(J)s=1,64 do %(X)s[string.byte(%(A)s,%(J)s)]=%(J)s-1 end '
    'local %(D)s={} local %(M)s=0 local %(Q)s=1 '
    'while %(Q)s<=#%(P)s do local %(a)s=%(X)s[string.byte(%(P)s,%(Q)s)]'
    ' local %(b)s=%(X)s[string.byte(%(P)s,%(Q)s+1)]'
    ' local %(c)s=%(X)s[string.byte(%(P)s,%(Q)s+2)]'
    ' local %(d)s=%(X)s[string.byte(%(P)s,%(Q)s+3)]'
    ' %(Q)s=%(Q)s+4 %(M)s=%(M)s+1 %(D)s[%(M)s]=%(a)s*4+math.floor(%(b)s/16)'
    ' if %(c)s~=nil then %(M)s=%(M)s+1 %(D)s[%(M)s]=(%(b)s%%16)*16+math.floor(%(c)s/4)'
    ' if %(d)s~=nil then %(M)s=%(M)s+1 %(D)s[%(M)s]=(%(c)s%%4)*64+%(d)s end end end '
    'local %(W)s={} '
    'for %(E)s=1,%(M)s do %(W)s[%(E)s]=string.char((%(D)s[%(E)s]-%(K)s[((%(E)s-1)%%%(hash_key)d)+1])%%256) end '
    'local %(F)s=assert((loadstring or load)(table.concat(%(W)s),nil,nil,_ENV)) '
    'return %(F)s(...)')
DECIPHERER = (
    'local %(R)s\n'
    'do\n'
    'local %(C)s,%(H)s,%(Y)s,%(T)s={},string.char,string.byte,table.concat\n'
    'function %(R)s(%(i)s,%(s)s)\n'
    'local %(c)s=%(C)s[%(i)s]\n'
    'if %(c)s==nil then\n'
    'local %(x)s,%(t)s,%(n)s=(%(i)s*%(a_num)d+%(b_num)d)%%32749,{},0\n'
    'for %(k)s=1,#%(s)s,3 do\n'
    'local %(a)s,%(b)s,%(d)s=%(Y)s(%(s)s,%(k)s,%(k)s+2)\n'
    '%(n)s=%(n)s+1\n'
    '%(t)s[%(n)s]=%(H)s(((%(a)s-48)*100+(%(b)s-48)*10+%(d)s-148-%(x)s%%256)%%256)\n'
    'local %(q)s=%(x)s*%(x)s%%32749\n'
    '%(x)s=(%(q)s+%(a_num)d*%(x)s+%(b_num)d)%%32749\n'
    'end\n'
    '%(c)s=%(T)s(%(t)s)\n'
    '%(C)s[%(i)s]=%(c)s\n'
    'end\n'
    'return %(c)s\n'
    'end\n'
    'end')
DECIPHERER_NAMES = ('H', 'Y', 'T', 'i', 's', 'c', 'x', 't', 'n', 'k', 'a', 'b', 'd', 'q')
RX_LAYER = re.compile(
    r'local (\w+)=\{\} local (\w+)=(\d+) '
    r'for (\w+)=1,(\d+) do \2=\(\2\*75\+74\)%65537 local (\w+)=\2%256 if \6==0 then \6=1 end \1\[\4\]=\6 end '
    r'local (\w+)="([A-Za-z0-9+/]*)"')
_RX_ID = re.compile(r'[A-Za-z_]\w*')
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
_ENGINE_API = {}
_RX_DECL_J = re.compile(
    r'^[ \t]*(?:constant[ \t]+)?(native|function)[ \t]+(\w+)[ \t]+takes[ \t].*?[ \t]returns[ \t]+(\w+)', re.M
)
_RX_TYPE_J = re.compile(r'^[ \t]*type[ \t]+(\w+)', re.M)
_RX_GLOBALS_J = re.compile(r'^[ \t]*globals\b(.*?)^[ \t]*endglobals\b', re.M | re.S)
_RX_GLOBAL_J = re.compile(r'^[ \t]*(?:constant[ \t]+)?\w+[ \t]+(?:array[ \t]+)?(\w+)', re.M)
LUA_LIBRARY = frozenset((
    '_G', '_ENV', '_VERSION', 'arg', 'assert', 'bit32', 'collectgarbage', 'coroutine', 'debug', 'dofile', 'error',
    'gcinfo', 'getfenv', 'getmetatable', 'io', 'ipairs', 'load', 'loadfile', 'loadstring', 'math', 'module',
    'newproxy', 'next', 'os', 'package', 'pairs', 'pcall', 'print', 'rawequal', 'rawget', 'rawlen', 'rawset',
    'require', 'select', 'setfenv', 'setmetatable', 'string', 'table', 'tonumber', 'tostring', 'type', 'unpack',
    'utf8', 'xpcall'))
LUA_ENGINE_NAMES = frozenset(('main', 'config', 'FourCC', '__jarray', 'JDiv', 'JCat', 'JEq'))
BY_NAME = {'ExecuteFunc': (0, 'fun'), 'TriggerRegisterVariableEvent': (1, 'var')}
LOADERS = frozenset(('load', 'loadstring', 'dofile', 'loadfile'))


class Names(object):
    def __init__(self, reserved, rng):
        self.reserved = set(reserved)
        self.rng = rng
        self.stack = []
        self.done_list = 0
        self.next_k = 0
        self.in_use = set()

    def _batch(self):
        batch = []
        k0, k1 = self.next_k, self.next_k + 4096
        self.next_k = k1
        for k in range(k0, k1):
            s = 'l' if k % 2 == 0 else 'I'
            k //= 2
            while k:
                k, r = divmod(k, 3)
                s += 'lI1'[r]
            if s not in self.reserved and s not in self.in_use:
                batch.append(s)
        self.rng.shuffle(batch)
        self.stack.extend(batch)

    def new(self):
        while True:
            while not self.stack:
                self._batch()
            s = self.stack.pop()
            if s not in self.reserved and s not in self.in_use:
                self.in_use.add(s)
                self.done_list += 1
                return s


def lehmer_key(seed, n):
    x = seed
    out = []
    for _ in range(n):
        x = (x * 75 + 74) % LEHMER
        b = x % 256
        out.append(b if b else 1)
    return out


_RX_ONLY_B64 = re.compile(r'[A-Za-z0-9+/]*')
_ADD_TABLES = {}


def _add_table(k):
    t = _ADD_TABLES.get(k)
    if t is None:
        t = _ADD_TABLES[k] = bytes((v + k) & 0xFF for v in range(256))
    return t


def add_key(data_bytes, hash_key, sign=1):
    n = len(hash_key)
    out = bytearray(data_bytes)
    for j in range(min(n, len(out))):
        out[j::n] = out[j::n].translate(_add_table((sign * hash_key[j]) & 0xFF))
    return bytes(out)


def b64_encode(data_bytes):
    return base64.b64encode(bytes(data_bytes)).decode('ascii').rstrip('=')


def b64_decode(s):
    if not _RX_ONLY_B64.fullmatch(s):
        return _b64_decode_py(s)
    cut = len(s) - len(s) % 4 if len(s) % 4 == 1 else len(s)
    return base64.b64decode(s[:cut] + '=' * (-cut % 4))


def _b64_decode_py(s):
    x = dict((ord(ch), i) for i, ch in enumerate(ALPHABET_B64))
    out = bytearray()
    for i in range(0, len(s), 4):
        a = x.get(ord(s[i])) if i < len(s) else None
        b = x.get(ord(s[i + 1])) if i + 1 < len(s) else None
        c = x.get(ord(s[i + 2])) if i + 2 < len(s) else None
        d = x.get(ord(s[i + 3])) if i + 3 < len(s) else None
        if a is None or b is None:
            break
        out.append((a * 4 + b // 16) & 0xff)
        if c is not None:
            out.append(((b % 16) * 16 + c // 4) & 0xff)
            if d is not None:
                out.append(((c % 4) * 64 + d) & 0xff)
    return bytes(out)


def wrap_layers(data_bytes, rng, log=print):
    g = Names(set(lua_ast.KEYWORDS) | {'self'}, rng)
    n = rng.randint(KEY_LEN_MIN, KEY_LEN_MAX)
    seed = rng.randint(1, LEHMER - 1)
    hash_key = lehmer_key(seed, n)
    encrypted_count = add_key(data_bytes, hash_key)
    body_text = LOADER % {
        'K': g.new(), 'S': g.new(), 'I': g.new(), 'B': g.new(), 'P': g.new(), 'A': g.new(),
        'X': g.new(), 'J': g.new(), 'D': g.new(), 'M': g.new(), 'Q': g.new(),
        'a': g.new(), 'b': g.new(), 'c': g.new(), 'd': g.new(),
        'W': g.new(), 'E': g.new(), 'F': g.new(),
        'seed': seed, 'hash_key': n, 'payload': b64_encode(encrypted_count), 'alphabet': ALPHABET_B64}
    return body_text.encode('utf-8'), {'seed': seed, 'hash_key': n, 'bytes': len(data_bytes)}


def unwrap(body_text):
    m = RX_LAYER.search(body_text)
    if not m:
        raise ValueError('cannot find the shape of a layer (is it a loader?): %r...' % body_text[:80])
    seed, n, payload = int(m.group(3)), int(m.group(5)), m.group(8)
    data_bytes = b64_decode(payload)
    hash_key = lehmer_key(seed, n)
    return add_key(data_bytes, hash_key, -1), {'seed': seed, 'hash_key': n}


_SAL = (75, 74)
STRING_MOD = 32749


def digits(index_, field_value):
    a, b = _SAL
    x = (index_ * a + b) % STRING_MOD
    out = []
    for ch in field_value.encode('utf-8', 'surrogateescape'):
        out.append('%03d' % ((ch + x % 256) % 256 + 100))
        q = (x * x) % STRING_MOD
        x = (q + a * x + b) % STRING_MOD
    return ''.join(out)


def value_of(index_, digits_str):
    a, b = _SAL
    x = (index_ * a + b) % STRING_MOD
    out = bytearray()
    for i in range(0, len(digits_str), 3):
        out.append((int(digits_str[i:i + 3]) - 100 - x % 256) % 256)
        q = (x * x) % STRING_MOD
        x = (q + a * x + b) % STRING_MOD
    return bytes(out).decode('utf-8', 'surrogateescape')


def renomeia(chunk, g, keep_names, log=print):
    reverse = {}
    globals_block = set()
    local_vars = set()
    scopes = [{}]
    label_set = [{}]

    def resolve(fname):
        for e in reversed(scopes):
            if fname in e:
                return e[fname]
        return None

    def declare(fname):
        local_vars.add(fname)
        if fname in keep_names:
            scopes[-1][fname] = fname
            return fname
        new = g.new()
        scopes[-1][fname] = new
        reverse[new] = fname
        return new

    def expr(e):
        t = type(e)
        if t is lua_ast.Name:
            new = resolve(e.name)
            if new is not None:
                e.name = new
            else:
                globals_block.add(e.name)
        elif t is lua_ast.Index:
            expr(e.base)
            expr(e.key)
        elif t is lua_ast.Call:
            expr(e.func)
            for a in e.args:
                expr(a)
        elif t is lua_ast.Unary:
            expr(e.operand)
        elif t is lua_ast.Binary:
            expr(e.left)
            expr(e.right)
        elif t is lua_ast.Paren:
            expr(e.inner)
        elif t is lua_ast.Table:
            for k, v in e.fields:
                if k is not None and type(k) is not str:
                    expr(k)
                expr(v)
        elif t is lua_ast.FunctionExpr:
            scopes.append({})
            label_set.append({})
            for i, p in enumerate(e.params):
                e.params[i] = declare(p)
            block_entry(e.body)
            scopes.pop()
            label_set.pop()

    def label_text(fname):
        if fname not in label_set[-1]:
            if fname in keep_names:
                label_set[-1][fname] = fname
            else:
                new = g.new()
                label_set[-1][fname] = new
                reverse[new] = fname
                local_vars.add(fname)
        return label_set[-1][fname]

    def block_entry(b):
        for s in b:
            t = type(s)
            if t is lua_ast.LocalStmt:
                for v in s.values:
                    expr(v)
                for i, n in enumerate(s.names):
                    s.names[i] = declare(n)
            elif t is lua_ast.AssignStmt:
                for x in s.targets:
                    expr(x)
                for v in s.values:
                    expr(v)
            elif t is lua_ast.CallStmt:
                expr(s.call)
            elif t is lua_ast.ReturnStmt:
                for v in s.values:
                    expr(v)
            elif t is lua_ast.FunctionStmt:
                if s.is_local:
                    s.name = declare(s.name)
                else:
                    base = re.split(r'[.:]', s.name, maxsplit=1)[0]
                    if base != s.name:
                        new = resolve(base)
                        if new is not None:
                            s.name = new + s.name[len(base):]
                        else:
                            globals_block.add(base)
                    else:
                        new = resolve(s.name)
                        if new is not None:
                            s.name = new
                        else:
                            globals_block.add(s.name)
                scopes.append({})
                label_set.append({})
                if ':' in s.name:
                    scopes[-1]['self'] = 'self'
                for i, p in enumerate(s.params):
                    s.params[i] = declare(p)
                block_entry(s.body)
                scopes.pop()
                label_set.pop()
            elif t is lua_ast.IfStmt:
                for cond, block_body in s.branches:
                    if cond is not None:
                        expr(cond)
                    scopes.append({})
                    block_entry(block_body)
                    scopes.pop()
            elif t is lua_ast.WhileStmt:
                expr(s.cond)
                scopes.append({})
                block_entry(s.body)
                scopes.pop()
            elif t is lua_ast.NumericForStmt:
                expr(s.start)
                expr(s.stop)
                if s.step is not None:
                    expr(s.step)
                scopes.append({})
                s.var = declare(s.var)
                block_entry(s.body)
                scopes.pop()
            elif t is lua_ast.GenericForStmt:
                for x in s.exprs:
                    expr(x)
                scopes.append({})
                for i, n in enumerate(s.names):
                    s.names[i] = declare(n)
                block_entry(s.body)
                scopes.pop()
            elif t is lua_ast.RepeatStmt:
                scopes.append({})
                block_entry(s.body)
                expr(s.cond)
                scopes.pop()
            elif t is lua_ast.DoStmt:
                scopes.append({})
                block_entry(s.body)
                scopes.pop()
            elif t is lua_ast.GotoStmt:
                s.label = label_text(s.label)
            elif t is lua_ast.LabelStmt:
                s.name = label_text(s.name)

    block_entry(chunk.body)
    return reverse, globals_block, local_vars


def engine_api(ref=None):
    folder = ref or DEFAULT_REF
    if folder in _ENGINE_API:
        return _ENGINE_API[folder]
    texts = {}
    try:
        for n in os.listdir(folder):
            if n.lower() in ('common.j', 'blizzard.j', 'common.ai'):
                with open(os.path.join(folder, n), encoding='utf-8', errors='replace') as f:
                    texts[n.lower()] = f.read()
    except OSError:
        pass
    if 'common.j' not in texts or 'blizzard.j' not in texts:
        _ENGINE_API[folder] = None
        return None
    name_list, retorno = set(), {}
    for t in texts.values():
        for _kind, fname, ret in _RX_DECL_J.findall(t):
            name_list.add(fname)
            retorno[fname] = ret
        name_list.update(_RX_TYPE_J.findall(t))
        for block_entry in _RX_GLOBALS_J.findall(t):
            name_list.update(_RX_GLOBAL_J.findall(block_entry))
    _ENGINE_API[folder] = (frozenset(name_list), retorno)
    return _ENGINE_API[folder]


def _return_kind(jass_type):
    if jass_type in ('integer', 'real'):
        return 'num'
    return {'string': 'str', 'boolean': 'bool', 'nothing': 'nil', 'code': 'fun'}.get(jass_type, 'hdl')


def _is_text(e):
    return type(e) is lua_ast.Literal and e.kind == 'string' and e.value is not None


def _concat_pieces(e):
    while type(e) is lua_ast.Paren:
        e = e.inner
    if type(e) is lua_ast.Binary and e.op == '..':
        return _concat_pieces(e.left) + _concat_pieces(e.right)
    if type(e) is lua_ast.Call and e.method is None and type(e.func) is lua_ast.Name and e.func.name == 'JCat':
        return [p for a in e.args for p in _concat_pieces(a)]
    return [e]


def plan_globals(chunk, generated, keep_names=(), api=None, log=print):
    api_names = api[0] if api else frozenset()
    retorno = api[1] if api else {}
    defs = {}
    texts = set()
    name_literals = []
    at_target = set()
    patterns = []
    opaque_uses = []

    def define(fname, types):
        defs.setdefault(fname, set()).update(types)

    def type_of(e):
        t = type(e)
        if t is lua_ast.Literal:
            return {'nil': {'nil'}, 'boolean': {'bool'}, 'number': {'num'}, 'string': {'str'}}.get(e.kind, {'any'})
        if t is lua_ast.Table:
            return {'tab'}
        if t is lua_ast.FunctionExpr:
            return {'fun'}
        if t is lua_ast.Paren:
            return type_of(e.inner)
        if t is lua_ast.Unary:
            return {'bool'} if e.op == 'not' else {'num'}
        if t is lua_ast.Binary:
            if e.op == '..':
                return {'str'}
            if e.op in ('==', '~=', '<', '<=', '>', '>='):
                return {'bool'}
            if e.op in ('and', 'or'):
                return type_of(e.left) | type_of(e.right)
            return {'num'}
        if t is lua_ast.Name and e.name not in generated:
            return {('ref', e.name)}
        if t is lua_ast.Call and e.method is None and type(e.func) is lua_ast.Name and e.func.name not in generated:
            n = e.func.name
            if n == 'FourCC':
                return {'num'}
            if n == '__jarray':
                return {'tab'}
            if n in retorno and n not in defs:
                return {_return_kind(retorno[n])}
        return {'any'}

    def name_of(e, type_name, where):
        if _is_text(e) and _RX_ID.fullmatch(e.value):
            name_literals.append(e)
            at_target.add(id(e))
            return
        ps = _concat_pieces(e)
        pre = ps[0].value if len(ps) > 1 and _is_text(ps[0]) else ''
        suf = ps[-1].value if len(ps) > 1 and _is_text(ps[-1]) else ''
        if _is_text(e):
            return
        if pre or suf:
            patterns.append((pre, suf, type_name))
        else:
            opaque_uses.append((type_name, where))

    def words(s):
        texts.update(_RX_ID.findall(s))

    def expr(e):
        t = type(e)
        if t is lua_ast.Literal:
            if _is_text(e) and id(e) not in at_target:
                words(e.value)
        elif t is lua_ast.Name:
            n = e.name
            if n in generated:
                return
            if n in ('_G', '_ENV'):
                opaque_uses.append(('all', '%s used as a value (line %d)' % (n, e.line)))
            elif n in BY_NAME:
                opaque_uses.append((BY_NAME[n][1], '%s stored/passed as a value (line %d)' % (n, e.line)))
            elif n in LOADERS:
                opaque_uses.append(('all', '%s stored/passed as a value (line %d)' % (n, e.line)))
        elif t is lua_ast.Index:
            b = e.base
            if type(b) is lua_ast.Name and b.name not in generated and b.name in ('_G', '_ENV', 'package', 'debug'):
                if _is_text(e.key):
                    k = e.key.value
                    if b.name in ('_G', '_ENV'):
                        if k in BY_NAME:
                            opaque_uses.append((BY_NAME[k][1], '%s.%s (line %d)' % (b.name, k, e.line)))
                        elif k in LOADERS or k in ('_G', '_ENV'):
                            opaque_uses.append(('all', '%s.%s (line %d)' % (b.name, k, e.line)))
                    elif (b.name, k) in (('package', 'loaded'), ('debug', 'getregistry')):
                        opaque_uses.append(('all', '%s.%s (line %d)' % (b.name, k, e.line)))
                elif b.name in ('_G', '_ENV'):
                    name_of(e.key, 'all', '%s[...] (line %d)' % (b.name, e.line))
                else:
                    opaque_uses.append(('all', '%s[...] (line %d)' % (b.name, e.line)))
                expr(e.key)
                return
            expr(b)
            expr(e.key)
        elif t is lua_ast.Call:
            f = e.func
            if e.method is None and type(f) is lua_ast.Name and f.name not in generated and \
                    (f.name in BY_NAME or f.name in LOADERS):
                if f.name in BY_NAME:
                    pos, type_name = BY_NAME[f.name]
                    if len(e.args) > pos:
                        name_of(e.args[pos], type_name, '%s (line %d)' % (f.name, e.line))
                elif e.args and not _is_text(e.args[0]):
                    opaque_uses.append(('all', '%s of a built text (line %d)' % (f.name, e.line)))
            else:
                expr(f)
            if e.method is not None:
                words(e.method)
            for a in e.args:
                expr(a)
        elif t is lua_ast.Unary:
            expr(e.operand)
        elif t is lua_ast.Binary:
            expr(e.left)
            expr(e.right)
        elif t is lua_ast.Paren:
            expr(e.inner)
        elif t is lua_ast.Table:
            for k, v in e.fields:
                if type(k) is str:
                    words(k)
                elif k is not None:
                    expr(k)
                expr(v)
        elif t is lua_ast.FunctionExpr:
            if '_ENV' in e.params:
                opaque_uses.append(('all', 'parameter _ENV (line %d)' % e.line))
            block_entry(e.body)

    def block_entry(b):
        for s in b:
            t = type(s)
            if t is lua_ast.LocalStmt:
                if '_ENV' in s.names:
                    opaque_uses.append(('all', 'local _ENV (line %d)' % s.line))
                for v in s.values:
                    expr(v)
            elif t is lua_ast.AssignStmt:
                for i, x in enumerate(s.targets):
                    if type(x) is lua_ast.Name and x.name not in generated:
                        if i < len(s.values):
                            define(x.name, type_of(s.values[i]))
                        else:
                            last_pos = s.values[-1] if s.values else None
                            define(x.name, {'any'} if type(last_pos) is lua_ast.Call or (
                                type(last_pos) is lua_ast.Literal and last_pos.kind == 'vararg') else {'nil'})
                        if x.name in ('_G', '_ENV'):
                            opaque_uses.append(('all', '%s assigned (line %d)' % (x.name, s.line)))
                    else:
                        expr(x)
                for v in s.values:
                    expr(v)
            elif t is lua_ast.CallStmt:
                expr(s.call)
            elif t is lua_ast.ReturnStmt:
                for v in s.values:
                    expr(v)
            elif t is lua_ast.FunctionStmt:
                pieces = re.split(r'[.:]', s.name)
                if not s.is_local and pieces[0] not in generated:
                    if len(pieces) == 1:
                        define(s.name, {'fun'})
                    elif pieces[0] in ('_G', '_ENV'):
                        pass
                for p in pieces[1:]:
                    words(p)
                if '_ENV' in s.params:
                    opaque_uses.append(('all', 'parameter _ENV (line %d)' % s.line))
                block_entry(s.body)
            elif t is lua_ast.IfStmt:
                for cond, block_body in s.branches:
                    if cond is not None:
                        expr(cond)
                    block_entry(block_body)
            elif t is lua_ast.WhileStmt:
                expr(s.cond)
                block_entry(s.body)
            elif t is lua_ast.NumericForStmt:
                for x in (s.start, s.stop) + ((s.step,) if s.step is not None else ()):
                    expr(x)
                block_entry(s.body)
            elif t is lua_ast.GenericForStmt:
                if '_ENV' in s.names:
                    opaque_uses.append(('all', 'for _ENV (line %d)' % s.line))
                for x in s.exprs:
                    expr(x)
                block_entry(s.body)
            elif t is lua_ast.RepeatStmt:
                block_entry(s.body)
                expr(s.cond)
            elif t is lua_ast.DoStmt:
                block_entry(s.body)

    block_entry(chunk.body)

    for _ in range(64):
        changed = False
        for n, ts in defs.items():
            for r in [x for x in ts if type(x) is tuple]:
                other = defs.get(r[1])
                if other is None or r[1] == n:
                    ts.discard(r)
                    if other is None:
                        ts.add('any')
                    changed = True
                    continue
                new_ones = set(x for x in other if type(x) is not tuple)
                if not new_ones <= ts:
                    ts |= new_ones
                    changed = True
                if not any(type(x) is tuple for x in other):
                    ts.discard(r)
                    changed = True
        if not changed:
            break
    for ts in defs.values():
        if any(type(x) is tuple for x in ts):
            ts.difference_update([x for x in ts if type(x) is tuple])
            ts.add('any')

    fixed_ones = set(api_names) | LUA_LIBRARY | LUA_ENGINE_NAMES | {'self', '_ENV', '_G'}

    def can_reach(type_name, ts):
        if type_name == 'all':
            return True
        if type_name == 'fun':
            return bool(ts & {'fun', 'any'})
        return bool(ts & {'num', 'any'})

    kept = {}
    candidates = []
    for n, ts in defs.items():
        if n in keep_names:
            kept[n] = 'keep_names'
        elif n in fixed_ones:
            kept[n] = 'engine'
        elif n in texts:
            kept[n] = 'body_text'
        elif any(can_reach(python_time, ts) for python_time, _where in opaque_uses):
            kept[n] = 'opaque'
        elif any(
            n.startswith(pre) and n.endswith(suf) and can_reach(python_time, ts) for pre, suf, python_time in patterns
        ):
            kept[n] = 'default_value'
        else:
            candidates.append(n)
    return {'candidates': candidates, 'kept': kept, 'name_literals': name_literals,
            'opaque_uses': [where for _tp, where in opaque_uses], 'patterns': sorted(set(patterns))}


def rename_globals(chunk, gmap, name_literals):
    for e in name_literals:
        if e.value in gmap:
            e.value, e.text = gmap[e.value], None

    def expr(e):
        t = type(e)
        if t is lua_ast.Name:
            if e.name in gmap:
                e.name = gmap[e.name]
        elif t is lua_ast.Index:
            expr(e.base)
            expr(e.key)
        elif t is lua_ast.Call:
            expr(e.func)
            for a in e.args:
                expr(a)
        elif t is lua_ast.Unary:
            expr(e.operand)
        elif t is lua_ast.Binary:
            expr(e.left)
            expr(e.right)
        elif t is lua_ast.Paren:
            expr(e.inner)
        elif t is lua_ast.Table:
            for k, v in e.fields:
                if k is not None and type(k) is not str:
                    expr(k)
                expr(v)
        elif t is lua_ast.FunctionExpr:
            for x in e.body:
                decl(x)

    def decl(s):
        t = type(s)
        if t is lua_ast.FunctionStmt:
            if not s.is_local:
                base = re.split(r'[.:]', s.name, maxsplit=1)[0]
                if base in gmap:
                    s.name = gmap[base] + s.name[len(base):]
            for x in s.body:
                decl(x)
            return
        for e in _exprs_of(s):
            expr(e)
        if t is lua_ast.IfStmt:
            for _cond, block_body in s.branches:
                for x in block_body:
                    decl(x)
        elif t in (lua_ast.WhileStmt, lua_ast.NumericForStmt, lua_ast.GenericForStmt, lua_ast.RepeatStmt,
                   lua_ast.DoStmt):
            for x in s.body:
                decl(x)

    for s in chunk.body:
        decl(s)


def encrypt_strings(chunk, r_name, log=print):
    def index_(field_value):
        if field_value not in index_by_value:
            index_by_value[field_value] = len(index_by_value) + 1
        return index_by_value[field_value]

    def called(field_value):
        i = index_(field_value)
        return lua_ast.Call(
            lua_ast.Name(r_name),
            [
                lua_ast.Literal('number', str(i), i),
                lua_ast.Literal('string', '"%s"' % digits(i, field_value), field_value),
            ],
            None,
            0,
        )

    index_by_value = {}

    def expr(e):
        t = type(e)
        if t is lua_ast.Literal:
            if e.kind == 'string' and e.value is not None:
                return called(e.value)
            return e
        if t is lua_ast.Name:
            return e
        if t is lua_ast.Index:
            e.base = expr(e.base)
            e.key = expr(e.key)
            return e
        if t is lua_ast.Call:
            e.func = expr(e.func)
            e.args = [expr(a) for a in e.args]
            return e
        if t is lua_ast.Unary:
            e.operand = expr(e.operand)
            return e
        if t is lua_ast.Binary:
            e.left = expr(e.left)
            e.right = expr(e.right)
            return e
        if t is lua_ast.Paren:
            e.inner = expr(e.inner)
            return e
        if t is lua_ast.Table:
            field_list = []
            for k, v in e.fields:
                if type(k) is str:
                    k = called(k)
                elif k is not None:
                    k = expr(k)
                field_list.append((k, expr(v)))
            e.fields[:] = field_list
            return e
        if t is lua_ast.FunctionExpr:
            for s in e.body:
                decl(s)
            return e
        return e

    def decl(s):
        t = type(s)
        if t is lua_ast.LocalStmt or t is lua_ast.AssignStmt or t is lua_ast.ReturnStmt:
            s.values = [expr(v) for v in s.values]
            if t is lua_ast.AssignStmt:
                s.targets = [expr(v) for v in s.targets]
        elif t is lua_ast.CallStmt:
            s.call = expr(s.call)
        elif t is lua_ast.FunctionStmt:
            for x in s.body:
                decl(x)
        elif t is lua_ast.IfStmt:
            for n, (cond, block_body) in enumerate(s.branches):
                if cond is not None:
                    s.branches[n] = (expr(cond), block_body)
                for x in block_body:
                    decl(x)
        elif t is lua_ast.WhileStmt:
            s.cond = expr(s.cond)
            for x in s.body:
                decl(x)
        elif t is lua_ast.NumericForStmt:
            s.start, s.stop = expr(s.start), expr(s.stop)
            if s.step is not None:
                s.step = expr(s.step)
            for x in s.body:
                decl(x)
        elif t is lua_ast.GenericForStmt:
            s.exprs = [expr(x) for x in s.exprs]
            for x in s.body:
                decl(x)
        elif t is lua_ast.RepeatStmt:
            for x in s.body:
                decl(x)
            s.cond = expr(s.cond)
        elif t is lua_ast.DoStmt:
            for x in s.body:
                decl(x)

    for s in chunk.body:
        decl(s)
    return index_by_value


def _strip_decipherer(chunk, r_name, c_name):
    if len(chunk.body) < 2:
        raise ValueError('the chunk does not even have 2 declarations (the decryptor?)')
    first, second_one = chunk.body[0], chunk.body[1]
    if not (type(first) is lua_ast.LocalStmt and list(first.names) == [r_name] and not first.values):
        raise ValueError('the 1st declaration is not the decryptor `local` (%r)' % (first,))
    block_body = second_one.body if type(second_one) is lua_ast.DoStmt else []
    if not (
        len(block_body) == 2
        and type(block_body[0]) is lua_ast.LocalStmt
        and list(block_body[0].names[:1]) == [c_name]
        and type(block_body[1]) is lua_ast.FunctionStmt
        and not block_body[1].is_local
        and block_body[1].name == r_name
        and len(block_body[1].params) == 2
    ):
        raise ValueError('the 2nd declaration is not the decryptor (%r)' % (second_one,))
    del chunk.body[0:2]


def _restore_decl(s, r_name):
    t = type(s)
    if t is lua_ast.LocalStmt or t is lua_ast.AssignStmt or t is lua_ast.ReturnStmt:
        s.values = [_restore_expr(v, r_name) for v in s.values]
        if t is lua_ast.AssignStmt:
            s.targets = [_restore_expr(v, r_name) for v in s.targets]
    elif t is lua_ast.CallStmt:
        s.call = _restore_expr(s.call, r_name)
    elif t is lua_ast.FunctionStmt:
        for x in s.body:
            _restore_decl(x, r_name)
    elif t is lua_ast.IfStmt:
        for n, (cond, block_body) in enumerate(s.branches):
            if cond is not None:
                s.branches[n] = (_restore_expr(cond, r_name), block_body)
            for x in block_body:
                _restore_decl(x, r_name)
    elif t is lua_ast.WhileStmt:
        s.cond = _restore_expr(s.cond, r_name)
        for x in s.body:
            _restore_decl(x, r_name)
    elif t is lua_ast.NumericForStmt:
        s.start, s.stop = _restore_expr(s.start, r_name), _restore_expr(s.stop, r_name)
        if s.step is not None:
            s.step = _restore_expr(s.step, r_name)
        for x in s.body:
            _restore_decl(x, r_name)
    elif t is lua_ast.GenericForStmt:
        s.exprs = [_restore_expr(x, r_name) for x in s.exprs]
        for x in s.body:
            _restore_decl(x, r_name)
    elif t is lua_ast.RepeatStmt:
        for x in s.body:
            _restore_decl(x, r_name)
        s.cond = _restore_expr(s.cond, r_name)
    elif t is lua_ast.DoStmt:
        for x in s.body:
            _restore_decl(x, r_name)


def _restore_expr(e, r_name):
    t = type(e)
    if t is lua_ast.Call:
        if type(e.func) is lua_ast.Name and e.func.name == r_name and len(e.args) == 2 \
                and type(e.args[0]) is lua_ast.Literal and e.args[0].kind == 'number' \
                and type(e.args[1]) is lua_ast.Literal and e.args[1].kind == 'string':
            return lua_ast.Literal('string', None, value_of(int(e.args[0].value), e.args[1].value))
        e.func = _restore_expr(e.func, r_name)
        e.args = [_restore_expr(a, r_name) for a in e.args]
        return e
    if t is lua_ast.Index:
        e.base = _restore_expr(e.base, r_name)
        e.key = _restore_expr(e.key, r_name)
        return e
    if t is lua_ast.Unary:
        e.operand = _restore_expr(e.operand, r_name)
        return e
    if t is lua_ast.Binary:
        e.left = _restore_expr(e.left, r_name)
        e.right = _restore_expr(e.right, r_name)
        return e
    if t is lua_ast.Paren:
        e.inner = _restore_expr(e.inner, r_name)
        return e
    if t is lua_ast.Table:
        field_list = []
        for k, v in e.fields:
            if k is not None and type(k) is not str:
                k = _restore_expr(k, r_name)
            field_list.append((k, _restore_expr(v, r_name)))
        e.fields[:] = field_list
        return e
    if t is lua_ast.FunctionExpr:
        for x in e.body:
            _restore_decl(x, r_name)
        return e
    return e


def _restore_names(chunk, reverse):
    def swap(fname):
        return reverse.get(fname, fname)

    def expr(e):
        t = type(e)
        if t is lua_ast.Name:
            e.name = swap(e.name)
        elif t is lua_ast.Index:
            expr(e.base)
            expr(e.key)
        elif t is lua_ast.Call:
            expr(e.func)
            for a in e.args:
                expr(a)
            if e.method is None and type(e.func) is lua_ast.Name and e.func.name in BY_NAME:
                pos = BY_NAME[e.func.name][0]
                if len(e.args) > pos and _is_text(e.args[pos]) and e.args[pos].value in reverse:
                    e.args[pos].value = reverse[e.args[pos].value]
        elif t is lua_ast.Unary:
            expr(e.operand)
        elif t is lua_ast.Binary:
            expr(e.left)
            expr(e.right)
        elif t is lua_ast.Paren:
            expr(e.inner)
        elif t is lua_ast.Table:
            for k, v in e.fields:
                if k is not None and type(k) is not str:
                    expr(k)
                expr(v)
        elif t is lua_ast.FunctionExpr:
            for i, p in enumerate(e.params):
                e.params[i] = swap(p)
            for x in e.body:
                decl(x)

    def decl(s):
        t = type(s)
        if t is lua_ast.LocalStmt:
            for i, n in enumerate(s.names):
                s.names[i] = swap(n)
            for v in s.values:
                expr(v)
        elif t is lua_ast.AssignStmt:
            for x in s.targets:
                expr(x)
            for v in s.values:
                expr(v)
        elif t is lua_ast.CallStmt:
            expr(s.call)
        elif t is lua_ast.FunctionStmt:
            if s.is_local or not ('.' in s.name or ':' in s.name):
                s.name = swap(s.name)
            else:
                base = re.split(r'[.:]', s.name, maxsplit=1)[0]
                if base in reverse:
                    s.name = reverse[base] + s.name[len(base):]
            for i, p in enumerate(s.params):
                s.params[i] = swap(p)
            for x in s.body:
                decl(x)
        elif t is lua_ast.IfStmt:
            for cond, block_body in s.branches:
                if cond is not None:
                    expr(cond)
                for x in block_body:
                    decl(x)
        elif t is lua_ast.WhileStmt:
            expr(s.cond)
            for x in s.body:
                decl(x)
        elif t is lua_ast.NumericForStmt:
            s.var = swap(s.var)
            expr(s.start)
            expr(s.stop)
            if s.step is not None:
                expr(s.step)
            for x in s.body:
                decl(x)
        elif t is lua_ast.GenericForStmt:
            for i, n in enumerate(s.names):
                s.names[i] = swap(n)
            for x in s.exprs:
                expr(x)
            for x in s.body:
                decl(x)
        elif t is lua_ast.RepeatStmt:
            for x in s.body:
                decl(x)
            expr(s.cond)
        elif t is lua_ast.DoStmt:
            for x in s.body:
                decl(x)
        elif t is lua_ast.ReturnStmt:
            for v in s.values:
                expr(v)
        elif t is lua_ast.GotoStmt:
            s.label = swap(s.label)
        elif t is lua_ast.LabelStmt:
            s.name = swap(s.name)

    for s in chunk.body:
        decl(s)


def _normalize(tree):
    for s in tree.body:
        _norm_decl(s)


def _norm_decl(s):
    t = type(s)
    if t in (lua_ast.LocalStmt, lua_ast.AssignStmt, lua_ast.ReturnStmt):
        for v in s.values:
            _norm_expr(v)
        if t is lua_ast.AssignStmt:
            for v in s.targets:
                _norm_expr(v)
    elif t is lua_ast.CallStmt:
        _norm_expr(s.call)
    elif t is lua_ast.FunctionStmt:
        for x in s.body:
            _norm_decl(x)
    elif t is lua_ast.IfStmt:
        for cond, block_body in s.branches:
            if cond is not None:
                _norm_expr(cond)
            for x in block_body:
                _norm_decl(x)
    elif t is lua_ast.WhileStmt:
        _norm_expr(s.cond)
        for x in s.body:
            _norm_decl(x)
    elif t is lua_ast.NumericForStmt:
        for e in (s.start, s.stop) + ((s.step,) if s.step is not None else ()):
            _norm_expr(e)
        for x in s.body:
            _norm_decl(x)
    elif t is lua_ast.GenericForStmt:
        for e in s.exprs:
            _norm_expr(e)
        for x in s.body:
            _norm_decl(x)
    elif t is lua_ast.RepeatStmt:
        for x in s.body:
            _norm_decl(x)
        _norm_expr(s.cond)
    elif t is lua_ast.DoStmt:
        for x in s.body:
            _norm_decl(x)


def _norm_expr(e):
    t = type(e)
    if t is lua_ast.Literal:
        if e.kind == 'string':
            e.text = None
        return
    if t is lua_ast.Index:
        _norm_expr(e.base)
        _norm_expr(e.key)
        if e.dot and type(e.key) is lua_ast.Literal and e.key.kind == 'string':
            e.dot = False
        return
    if t is lua_ast.Call:
        _norm_expr(e.func)
        for a in e.args:
            _norm_expr(a)
        return
    if t is lua_ast.Unary:
        _norm_expr(e.operand)
        return
    if t is lua_ast.Binary:
        _norm_expr(e.left)
        _norm_expr(e.right)
        return
    if t is lua_ast.Paren:
        _norm_expr(e.inner)
        return
    if t is lua_ast.Table:
        field_list = []
        for k, v in e.fields:
            if type(k) is str:
                k = lua_ast.Literal('string', None, k)
            elif k is not None:
                _norm_expr(k)
            _norm_expr(v)
            field_list.append((k, v))
        e.fields[:] = field_list
        return
    if t is lua_ast.FunctionExpr:
        for x in e.body:
            _norm_decl(x)


def _declared_names(chunk):
    out = []

    def expr(e):
        t = type(e)
        if t is lua_ast.FunctionExpr:
            for p in e.params:
                out.append((p, e.line))
            for s in e.body:
                decl(s)

    def decl(s):
        t = type(s)
        if t is lua_ast.LocalStmt:
            for n in s.names:
                out.append((n, s.line))
        elif t is lua_ast.FunctionStmt:
            if s.is_local:
                out.append((s.name, s.line))
            for p in s.params:
                out.append((p, s.line))
            for x in s.body:
                decl(x)
        elif t is lua_ast.IfStmt:
            for cond, block_body in s.branches:
                for x in block_body:
                    decl(x)
        elif t is lua_ast.WhileStmt or t is lua_ast.DoStmt:
            for x in s.body:
                decl(x)
        elif t is lua_ast.NumericForStmt:
            out.append((s.var, s.line))
            for x in s.body:
                decl(x)
        elif t is lua_ast.GenericForStmt:
            for n in s.names:
                out.append((n, s.line))
            for x in s.body:
                decl(x)
        elif t is lua_ast.RepeatStmt:
            for x in s.body:
                decl(x)
        elif t is lua_ast.LabelStmt:
            out.append((s.name, s.line))
        for e in _exprs_of(s):
            expr(e)

    for s in chunk.body:
        decl(s)
    return out


def _exprs_of(s):
    t = type(s)
    out = []
    if t in (lua_ast.LocalStmt, lua_ast.AssignStmt, lua_ast.ReturnStmt):
        out += list(s.values)
        if t is lua_ast.AssignStmt:
            out += list(s.targets)
    elif t is lua_ast.CallStmt:
        out.append(s.call)
    elif t is lua_ast.IfStmt:
        out += [c for c, _ in s.branches if c is not None]
    elif t is lua_ast.WhileStmt:
        out.append(s.cond)
    elif t is lua_ast.NumericForStmt:
        out += [s.start, s.stop] + ([s.step] if s.step is not None else [])
    elif t is lua_ast.GenericForStmt:
        out += list(s.exprs)
    elif t is lua_ast.RepeatStmt:
        out.append(s.cond)
    return out


class _Links(lua_ast._Parser):
    def __init__(self, body_text):
        lua_ast._Parser.__init__(self, body_text)
        self.n_decl = 0
        self.links = []

    def _new_localvar(self, name, attrib=None):
        lua_ast._Parser._new_localvar(self, name, attrib)
        self.n_decl += 1
        self.fs.actvar[-1].append(self.n_decl)

    def _singlevar(self, name):
        fs = self.fs
        stack = fs.vars.get(name)
        var = fs.actvar[stack[-1]] if stack else self._resolve(fs, name)
        ln = self.l[self.i - 1]
        if var is lua_ast._GLOBAL:
            env = self._resolve(fs, '_ENV')
            self.links.append(('global', name, env[2] if len(env) > 2 else 0, ln))
        else:
            self.links.append(('local', var[2] if len(var) > 2 else 0, ln))


class _BindingsOnly(object):
    __slots__ = ('links', 'n_decl')

    def __init__(self, links, n_decl):
        self.links, self.n_decl = links, n_decl


def _link(body_text):
    old = sys.getrecursionlimit()
    if old < lua_ast._RECURSION:
        sys.setrecursionlimit(lua_ast._RECURSION)
    try:
        p = _Links(body_text)
        script_tree = p.chunk()
        return script_tree, _BindingsOnly(p.links, p.n_decl)
    finally:
        if old < lua_ast._RECURSION:
            sys.setrecursionlimit(old)


def _links_diff(orig, output, k_dec=0, n_dec=0, inverse_g=None):
    inverse_g = inverse_g or {}

    def hash_key(link_ref, n, inv):
        if link_ref[0] == 'local':
            return ('local', link_ref[1] - n if link_ref[1] else 0)
        return ('global', inv.get(link_ref[1], link_ref[1]), link_ref[2] - n if link_ref[2] else 0)
    s = [hash_key(link_ref, n_dec, inverse_g) for link_ref in output.links[k_dec:]
         if not (link_ref[0] == 'local' and 0 < link_ref[1] <= n_dec)]
    o = [hash_key(link_ref, 0, {}) for link_ref in orig.links]
    for j, (a, b) in enumerate(zip(o, s)):
        if a != b:
            return 'line %d of the original: %r became %r' % (orig.links[j][-1], a, b)
    if len(o) != len(s):
        return '%d names in the original, %d in the output' % (len(o), len(s))
    return None


def compile_lua53(data_bytes):
    try:
        from lupa import lua53
    except ImportError:
        return None, 'no lupa'
    rt = lua53.LuaRuntime(encoding=None)
    f = rt.eval(b'function(t) local f, e = load(t, "=war3map.lua", "t") if f then return true end return e end')
    r = f(data_bytes)
    if r is True:
        return True, None
    return False, r.decode('utf-8', 'replace') if isinstance(r, bytes) else str(r)


def obfuscate(source, seed=None, keep_names=(), layers=2, no_names=False, no_strings=False, marker=None,
              log=print, no_globals=False, ref=None):
    keep_names = set(keep_names) | {'_ENV'}
    try:
        layers = int(layers)
    except (TypeError, ValueError):
        raise SystemExit('ABORT: layers is not an integer (%r)' % (layers,))
    if layers < 0:
        raise SystemExit('ABORT: layers is negative (%d): 0 is just the minified one' % layers)
    if marker and ('\n' in marker or '\r' in marker):
        raise SystemExit('ABORT: the marker cannot have a line break (%r)' % marker)
    if isinstance(source, bytes):
        source = source.decode('utf-8', 'surrogateescape')
    t0 = time.time()
    try:
        chunk = lua_ast.parse(source)
    except lua_ast.LuaSyntaxError as e:
        raise SystemExit('ABORT: the original does not parse (line %d): %s' % (e.line, e.message))
    rng = random.Random(seed if seed is not None else
                        int(hashlib.sha256(source.encode('utf-8', 'surrogateescape')).hexdigest()[:16], 16))
    global _SAL
    _SAL = (rng.randrange(2, STRING_MOD), rng.randrange(1, STRING_MOD))
    reserved = set(_RX_ID.findall(source)) | set(lua_ast.KEYWORDS) | {'self', '_ENV'} | set(keep_names)
    g = Names(reserved, rng)
    details = {'ok': False, 'bytes_before': len(source.encode('utf-8', 'surrogateescape')), 'gates': {},
               'string_key': {'a': _SAL[0], 'b': _SAL[1]}}

    if no_names:
        reverse, globals_block, local_vars = {}, set(), set()
        details['names_swapped'] = 0
    else:
        reverse, globals_block, local_vars = renomeia(chunk, g, keep_names, log=log)
        details['names_swapped'] = len(reverse)

    gmap, plain_name = {}, None
    details['globals_renamed'], details['globals_kept'], details['globals_opaque'] = 0, {}, []
    if not (no_names or no_globals):
        api = engine_api(ref)
        if api is None:
            raise SystemExit('ABORTS: no common.j and blizzard.j in %s (the engine names, which the map globals '
                             'cannot take): --ref=<folder> or --no-globals' % (ref or DEFAULT_REF))
        plain_name = plan_globals(chunk, set(reverse), keep_names, api, log=log)
        for n in plain_name['candidates']:
            gmap[n] = g.new()
        rename_globals(chunk, gmap, plain_name['name_literals'])
        for n, new in gmap.items():
            reverse[new] = n
        details['globals_renamed'] = len(gmap)
        for why in plain_name['kept'].values():
            details['globals_kept'][why] = details['globals_kept'].get(why, 0) + 1
        details['globals_opaque'] = plain_name['opaque_uses'][:10]
        details['names_swapped'] = len(reverse)
    inverse_g = dict((new, n) for n, new in gmap.items())

    if no_strings:
        idx_by_value = {}
        details['strings_encrypted'] = 0
    else:
        r_name, c_name = g.new(), g.new()
        idx_by_value = encrypt_strings(chunk, r_name, log=log)
        dec_names = dict((k, g.new()) for k in DECIPHERER_NAMES)
        dec_names.update(R=r_name, C=c_name, a_num=_SAL[0], b_num=_SAL[1])
        dec = DECIPHERER % dec_names
        chunk.body[0:0] = lua_ast.parse(dec).body
        details['strings_encrypted'] = len(idx_by_value)

    body_text = lua_ast.canonical(chunk)
    details['bytes_minified'] = len(body_text.encode('utf-8', 'surrogateescape'))

    leftovers = [(n, where) for n, where in _declared_names(chunk) if n in local_vars and n not in keep_names]
    details['gates']['G3 names'] = 'ok (%d swapped, 0 forgotten declarations)' % (len(reverse) - len(gmap)) \
        if not leftovers else 'FAILED: %s' % leftovers[:5]
    if leftovers:
        raise SystemExit('ABORT (G3): local declarations without the new name: %s' % leftovers[:5])
    del chunk, plain_name

    data_bytes = body_text.encode('utf-8', 'surrogateescape')
    phases = []
    layers_meta = []
    for n in range(layers):
        data_bytes, meta = wrap_layers(data_bytes, rng, log=log)
        layers_meta.append(meta)
        phases.append(('the layer %d' % (n + 1), data_bytes))
    prefix = ('-- %s\n' % marker) if marker else ''
    output = prefix + data_bytes.decode('utf-8', 'surrogateescape')
    details['layers'] = layers_meta
    details['output'] = output
    details['bytes_after'] = len(output.encode('utf-8', 'surrogateescape'))

    try:
        tree, link_out = _link(body_text)
    except lua_ast.LuaSyntaxError as e:
        raise SystemExit('ABORT (G1): the inner chunk does not parse (line %d): %s%s' % (
            e.line, e.message, '' if no_strings else
            ' (the decryptor takes 1 local of the main chunk and each string becomes a call)'))
    if gmap:
        leftover_g = sorted(
            set(link_ref[1] for link_ref in link_out.links if link_ref[0] == 'global' and link_ref[1] in gmap)
        )
        if leftover_g:
            raise SystemExit('ABORTS (G3): renamed globals that kept the original name: %s' % leftover_g[:5])
        details['gates']['G3 names'] = 'ok (%d locals and %d globals renamed, 0 declarations missed, 0 globals with ' \
                                     'the original name)' % (len(reverse) - len(gmap), len(gmap))
    for fname, d in phases[:-1] + ([('the layer %d' % layers, output.encode('utf-8', 'surrogateescape'))]
                                   if layers else []):
        try:
            lua_ast.parse(d.decode('utf-8', 'surrogateescape'))
        except lua_ast.LuaSyntaxError as e:
            raise SystemExit('ABORT (G1): %s does not parse (line %d): %s' % (fname, e.line, e.message))
    details['gates']['G1 parse'] = 'ok (the inner chunk and %d layer(s) parse)' % layers
    compiles, err = compile_lua53(body_text.encode('utf-8', 'surrogateescape'))
    if compiles is None:
        details['gates']['G1 compiles'] = 'skipped (%s)' % err
    elif compiles:
        details['gates']['G1 compiles'] = 'ok (the inner chunk compiles in Lua 5.3)'
    else:
        compiled_o, error_o = compile_lua53(source.encode('utf-8', 'surrogateescape'))
        if compiled_o:
            raise SystemExit('ABORT (G1): the inner chunk does not compile in Lua 5.3 and the original does (%s)%s' % (
                err, '' if no_strings else ' (each encrypted string needs 2 more registers)'))
        details['gates']['G1 compiles'] = 'the original does not compile in Lua 5.3 either (%s)' % error_o

    inner_part = output[len(prefix):]
    for _ in layers_meta:
        plaintext, _meta = unwrap(inner_part)
        inner_part = plaintext.decode('utf-8', 'surrogateescape')
    if inner_part != body_text:
        raise SystemExit('ABORT (G2): the peeled layers do not return the inner chunk (%d/%d bytes)'
                         % (len(inner_part), len(body_text)))
    k_dec = n_dec = 0
    if not no_strings:
        _, link_dec = _link(dec)
        k_dec, n_dec = len(link_dec.links), link_dec.n_decl
        _strip_decipherer(tree, r_name, c_name)
        for s in tree.body:
            _restore_decl(s, r_name)
    if not no_names:
        _restore_names(tree, reverse)
    _normalize(tree)
    a = lua_ast.canonical(tree)
    del tree
    origin, link_source = _link(source)
    _normalize(origin)
    b = lua_ast.canonical(origin)
    del origin
    if a != b:
        where = [i for i, (x, y) in enumerate(zip(a, b)) if x != y][:1]
        raise SystemExit('ABORT (G2): the way back does not return the original (1st difference at byte %s of %d/%d)'
                         % (where, len(a), len(b)))
    diff = _links_diff(link_source, link_out, k_dec, n_dec, inverse_g)
    if diff:
        raise SystemExit('ABORT (G2): a name came to bind to another declaration (%s)' % diff)
    details['gates']['G2 round trip'] = ('ok (layers peeled, strings put back, names reverted; canonical equal; '
                                         '%d names bound to the same declarations)' % len(link_source.links))

    details['reverse'] = reverse
    details['inverse_globals'] = inverse_g
    details['strings'] = idx_by_value
    details['ok'] = True
    details['seconds'] = round(time.time() - t0, 1)
    log(
        'LUA_OBFUSCATE %d -> %d B (%d layer(s)) in %.1fs: %s'
        % (
            details['bytes_before'],
            details['bytes_after'],
            len(layers_meta),
            details['seconds'],
            '; '.join(details['gates'].values()),
        )
    )
    return details
