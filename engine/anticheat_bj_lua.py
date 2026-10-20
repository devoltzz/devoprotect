# The Lua anti-cheat: restores the engine functions a Lua cheat pack replaces and guards main.
import contextlib
import hashlib
import re

import jass_ast
import jass_to_lua
import lua_ast


DEFAULT_REF = jass_to_lua.DEFAULT_REF
DEFAULT_HOOK = 'DevoAC_Acusa'
MARK = '-- DevoAC:bj_lua'
CORE = ('DetectGameStarted', 'MarkGameStarted')
ROOTS = ('main', 'config')
DETAIL_TEXTS = {'main': 'main was replaced after the map script loaded',
                'config': 'config was replaced after the map script loaded'}
TYPES = {'main': 20, 'config': 21}
RESERVED = frozenset(('and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for', 'function', 'goto', 'if',
                      'in', 'local', 'nil', 'not', 'or', 'repeat', 'return', 'then', 'true', 'until', 'while'))
RX_NAME_TOKEN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
RX_PREAMBLE = re.compile(r'^(FourCC|__jarray|JDiv|JCat|JEq) = \1 or ', re.M)
PUT = ('local E, G, rg = _ENV, _G, rawget\n'
       'if type(G) ~= "table" or G == E then G = nil end\n'
       'local function put(n, f)\n'
       '  if rg == nil then if E[n] ~= nil then E[n] = f end return end\n'
       '  local feito = false\n'
       '  if rg(E, n) ~= nil then E[n] = f feito = true end\n'
       '  if G ~= nil and rg(G, n) ~= nil then G[n] = f feito = true end\n'
       '  if not feito and E[n] ~= nil then E[n] = f end\n'
       'end\n')

SENTINEL = ('(function()\n'
            'local m = main\n'
            'if type(m) ~= "function" then return end\n'
            + PUT +
            'local function le(T, n) if T == nil then return nil end if rg ~= nil then return rg(T, n) end '
            'return T[n] end\n'
            'local h0, pc = {gancho}, pcall\n'
            'local function acusa(c, d) local h = h0 or {gancho} if h ~= nil then pc(h, nil, c, d) end end\n'
            'local em, gm, ec, gc\n'
            'local w\n'
            'w = function(...)\n'
            '  if le(E, "main") ~= em or le(G, "main") ~= gm then acusa({tipo_main}, "{det_main}") end\n'
            '  if le(E, "config") ~= ec or le(G, "config") ~= gc then acusa({tipo_config}, "{det_config}") end\n'
            '  return m(...)\n'
            'end\n'
            'put("main", w)\n'
            'em, gm, ec, gc = le(E, "main"), le(G, "main"), le(E, "config"), le(G, "config")\n'
            'end)()\n')

STUB = ('{gancho} = {gancho} or function(p, c, d)\n'
        '  local s = "|cffff4040Anti-cheat:|r this copy of the map was modified"\n'
        '  if p ~= nil then s = "|cffff4040Anti-cheat:|r " .. tostring(GetPlayerName(p)) .. " was flagged" end\n'
        '  if d ~= nil then s = s .. " (" .. tostring(d) .. ")" end\n'
        '  local t = CreateTimer()\n'
        '  TimerStart(t, 1.0, false, function()\n'
        '    DestroyTimer(t)\n'
        '    for i = 0, bj_MAX_PLAYER_SLOTS - 1 do DisplayTimedTextToPlayer(Player(i), 0, 0, 30.0, s) end\n'
        '  end)\n'
        'end\n')

_BLIZ = {}
_VERDICTS = {}


def _nothing(*_a, **_k):
    pass


@contextlib.contextmanager
def _ref_cached():
    a0, n0 = jass_to_lua.signatures, jass_to_lua.game_natives
    ma, mn = {}, {}

    def signatures(paths, strict=False):
        k = (tuple(paths), strict)
        if k not in ma:
            ma[k] = a0(paths, strict)
        r, g = ma[k][:2]
        return (dict(r), dict(g)) + tuple(dict((n, list(t)) for n, t in p.items()) for p in ma[k][2:])

    def game_natives(ref):
        if ref not in mn:
            mn[ref] = n0(ref)
        return set(mn[ref])

    jass_to_lua.signatures, jass_to_lua.game_natives = signatures, game_natives
    try:
        yield
    finally:
        jass_to_lua.signatures, jass_to_lua.game_natives = a0, n0


def _blizzard(ref, blizzard):
    if blizzard is None:
        with open(jass_to_lua.ref_file(ref, 'blizzard.j'), encoding='utf-8', errors='surrogateescape') as f:
            blizzard = f.read()
    sha = hashlib.sha256(blizzard.encode('utf-8', 'surrogateescape')).hexdigest()
    if sha not in _BLIZ:
        s = jass_ast.parse(blizzard)
        fs = dict((f.name, f) for f in s.functions)
        called = {}
        for f in s.functions:
            called[f.name] = set(n.name for n in jass_ast.walk(f)
                                 if type(n) in (jass_ast.Call, jass_ast.FuncRef) and n.name in fs)
        _BLIZ[sha] = {'sha': sha, 'fs': fs, 'line_list': blizzard.split('\n'), 'called': called,
                      'order': dict((f.name, i) for i, f in enumerate(s.functions))}
    return _BLIZ[sha]


def _text_j(bj, fname):
    f = bj['fs'][fname]
    return '\n'.join(bj['line_list'][f.line - 1:f.end_line])


def _verdict(bj, ref, fname):
    k = (bj['sha'], ref, fname)
    if k not in _VERDICTS:
        try:
            _l, r = jass_to_lua.converte(_text_j(bj, fname) + '\n', ref=ref, log=_nothing)
        except SystemExit as e:
            _VERDICTS[k] = 'the conversion refused it (%s)' % str(e)[:120]
        else:
            m = []
            if r['integer_divisions']:
                m.append('integer division')
            if r['concatenations'] or r['concat_with_null']:
                m.append('string concatenation')
            if r['integers_as_real']:
                m.append('integer stored as real')
            if r['real_equalities']:
                m.append('real equality')
            if r['numeric_nulls']:
                m.append('null as a number')
            if fname in r['renamed']:
                m.append('the name is renamed in Lua')
            _VERDICTS[k] = ('not provably the game\'s own conversion: ' + ', '.join(m)) if m else None
    return _VERDICTS[k]


def _names(no, out):
    stack = [no]
    while stack:
        n = stack.pop()
        if isinstance(n, lua_ast.Name):
            out.add(n.name)
        elif isinstance(n, (list, tuple)):
            stack.extend(n)
        elif isinstance(n, lua_ast.Node):
            for field_id in type(n).__slots__:
                v = getattr(n, field_id, None)
                if isinstance(v, (lua_ast.Node, list, tuple)):
                    stack.append(v)
    return out


def compute_closure(chunk, bj):
    mf = chunk.functions
    visited, bjs = set(), set()
    load_of = _names([st for st in chunk.body if not (isinstance(st, lua_ast.FunctionStmt) and not st.is_local)], set())
    pend = [n for n in ROOTS if n in mf] + sorted(n for n in load_of if n in mf)
    bjs.update(n for n in load_of if n in bj['fs'] and n not in mf)
    while pend:
        n = pend.pop()
        if n in visited:
            continue
        visited.add(n)
        for x in _names(mf[n].body, set()):
            if x in mf:
                if x not in visited:
                    pend.append(x)
            elif x in bj['fs']:
                bjs.add(x)
    stack = list(bjs)
    while stack:
        for c in bj['called'][stack.pop()]:
            if c not in bjs and c not in mf:
                bjs.add(c)
                stack.append(c)
    return visited, bjs


def _head(name_list, bj, ref):
    jtext = '\n'.join(_text_j(bj, n) for n in name_list) + '\n'
    lua, details = jass_to_lua.converte(jtext, ref=ref, log=_nothing)
    lua = RX_PREAMBLE.sub(lambda m: 'local %s = %s or ' % (m.group(1), m.group(1)), lua)
    ch = lua_ast.parse(lua)
    pieces, done_names = [], []
    for st in ch.body:
        a, b = st.span
        segment = lua[a:b]
        if isinstance(st, lua_ast.FunctionStmt) and not st.is_local and st.name in bj['fs']:
            head_line = 'function ' + st.name
            if not segment.startswith(head_line):
                raise SystemExit('ABORT: the conversion of %s does not start with "%s"' % (st.name, head_line))
            pieces.append('put("%s", function%s)' % (st.name, segment[len(head_line):]))
            done_names.append(st.name)
        elif isinstance(st, lua_ast.LocalStmt):
            pieces.append(segment)
        else:
            raise SystemExit(
                'ABORT: the blizzard.j conversion gave a command that is not a function (line %d)' % st.line
            )
    if done_names != list(name_list):
        raise SystemExit('ABORT: the conversion returned %d function(s), %d asked' % (len(done_names), len(name_list)))
    return lua_ast.canonical('(function()\n' + PUT + '\n'.join(pieces) + '\nend)()\n') + '\n', details


def inject(body_text, language, hook=DEFAULT_HOOK, stub=False, closure=True, ref=None, blizzard=None, log=None,
           main_kind=TYPES['main'], config_kind=TYPES['config'], **other_entries):
    log = log or _nothing
    ref = ref or DEFAULT_REF
    details = {'piece': 'bj_lua', 'ok': True, 'changed': False, 'language': (language or '').lower(), 'why': None,
               'hook': hook, 'stub': bool(stub), 'restored': [], 'outside': {}, 'closure': {}, 'sentinel': False,
               'bytes': 0, 'gates': {}}
    if other_entries:
        details['ignored_options'] = sorted(other_entries)
    if details['language'] != 'lua':
        details['why'] = ('the map script is %s: the BJ restoration is the Lua piece (a JASS map cannot redefine a '
                          'function; the name decoys cover it there)' % (language or 'unknown'))
        return body_text, details
    if not (isinstance(hook, str) and RX_NAME_TOKEN.match(hook) and hook not in RESERVED):
        raise ValueError('hook: %r is not a Lua name' % (hook,))
    good = '\ufeff' if body_text.startswith('\ufeff') else ''
    block_body = body_text[len(good):]
    if MARK in block_body:
        details['why'] = 'the script already carries the BJ restoration (%s)' % MARK
        return body_text, details
    try:
        chunk = lua_ast.parse(block_body)
    except lua_ast.LuaSyntaxError as e:
        details['ok'] = False
        details['why'] = 'the Lua script does not parse (line %d): %s' % (e.line, e.message)
        return body_text, details
    bj = _blizzard(ref, blizzard)
    with _ref_cached():
        tgt = set(n for n in CORE if n in bj['fs'])
        if closure:
            visited, bjs = compute_closure(chunk, bj)
            details['closure'] = {'map_functions': len(visited), 'bj': len(bjs)}
            tgt |= bjs
        for n in sorted(tgt):
            if n in chunk.functions:
                details['outside'][n] = 'the map defines it (its own definition comes after the restoration)'
                continue
            why = _verdict(bj, ref, n)
            if why:
                details['outside'][n] = why
        name_list = sorted((n for n in tgt if n not in details['outside']), key=bj['order'].get)
        head_text, conv_report = _head(name_list, bj, ref) if name_list else ('', None)
    details['restored'] = name_list
    nl = '\r\n' if '\r\n' in block_body else '\n'
    head = MARK + '\n' + (STUB.replace('{gancho}', hook) if stub else '') + (
        ';' + head_text.rstrip('\n') + ';\n' if head_text else '')
    sentinel_text = SENTINEL.replace('{gancho}', hook).replace('{det_main}', DETAIL_TEXTS['main']).replace(
        '{det_config}', DETAIL_TEXTS['config']).replace('{tipo_main}', '%d' % int(main_kind)).replace(
        '{tipo_config}', '%d' % int(config_kind))
    end_pos = len(block_body)
    if chunk.body and isinstance(chunk.body[-1], lua_ast.ReturnStmt):
        end_pos = chunk.body[-1].span[0]
    before, after_diag = block_body[:end_pos], block_body[end_pos:]
    if before and not before.endswith('\n'):
        before += nl
    new = (
        good
        + head.replace('\n', nl)
        + before
        + (';' + sentinel_text.rstrip('\n') + ';\n').replace('\n', nl)
        + after_diag
    )
    details['sentinel'] = True
    details['main_at_top'] = 'main' in chunk.functions
    try:
        lua_ast.parse(new[len(good):])
    except lua_ast.LuaSyntaxError as e:
        raise SystemExit('ABORT (G1): the injected Lua does not parse (line %d): %s' % (e.line, e.message))
    details['gates']['G1 parse'] = 'ok (the injected script parses as Lua 5.3)'
    details['changed'] = True
    details['bytes'] = len(new) - len(body_text)
    log('ANTICHEAT_BJ_LUA: %d BJ function(s) restored (%d left out), the main sentinel%s; +%d B' % (
        len(name_list), len(details['outside']), ' and the stub hook' if stub else '', details['bytes']))
    return new, details

