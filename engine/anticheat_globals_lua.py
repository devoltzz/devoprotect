# The Lua anti-cheat global watch: reports globals the map script does not create.
import re

import jass_ast
import jass_to_lua
import lua_ast


DEFAULT_REF = jass_to_lua.DEFAULT_REF
DEFAULT_HOOK = 'DevoAC_Acusa'
MARK = '-- DevoAC:globais_lua'
BRIDGE = 'DevoAC_Gw'
INTERVAL = 15.0
PER_PACK = 8
TYPES = {'global': 22, 'signature': 23}
DETAILS = {'after_diag': 'a global was created after the map script: ',
           'foreign': 'a global the map script does not define: ',
           'signature': 'cheat pack signature: '}
RX_NAME_TOKEN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
RESERVED = lua_ast.KEYWORDS
HEAD_CODE = r'''(function()
local E, G = _ENV, _G
local nx, tp, rg, rs, gmt, pc, gm = next, type, rawget, rawset, getmetatable, pcall, string.gmatch
local smt = setmetatable
if tp(G) ~= "table" or G == E then G = nil end
local OK, SIG, seen, queue, once = {}, {}, {}, {}, {}
for n in gm("{permitidos}", "%S+") do OK[n] = true end
for n, p in gm("{assinaturas}", "([^%s=]+)=(%S+)") do SIG[n] = p end
local phase = 1
local function report(c, d)
  if once[c] then return end
  if phase < 3 then queue[#queue + 1] = {c, d} return end
  once[c] = true
  local h = {gancho}
  if h ~= nil then pc(h, nil, c, d) end
end
local function check(k, v)
  if tp(k) ~= "string" or v == nil then return end
  local p = SIG[k]
  if p ~= nil then report({tipo_assinatura}, "{det_assinatura}" .. p .. " (" .. k .. ")") return end
  if phase == 2 then report({tipo}, "{det_depois}" .. k)
  elseif {checa_nomes} and not OK[k] then report({tipo}, "{det_estranho}" .. k) end
end
local function snap(T)
  if tp(T) ~= "table" then return end
  local k, v = nx(T)
  while k ~= nil do
    seen[k] = true
    if tp(k) == "string" and SIG[k] ~= nil and v ~= nil then
      queue[#queue + 1] = {{tipo_assinatura}, "{det_assinatura}" .. SIG[k] .. " (" .. k .. ")"}
    end
    k, v = nx(T, k)
  end
end
snap(E) snap(G)
local mt0 = gmt(E)
if tp(mt0) == "table" then snap(rg(mt0, "__index")) end
local function watch(T)
  if T == nil then return end
  local mt = gmt(T)
  if mt ~= nil and tp(mt) ~= "table" then return end
  local fresh = mt == nil
  if fresh then mt = {} end
  local old = rg(mt, "__newindex")
  local function ni(t, k, v)
    if v ~= nil and not seen[k] then seen[k] = true pc(check, k, v) end
    if old == nil then rs(t, k, v) elseif tp(old) == "function" then return old(t, k, v) else old[k] = v end
  end
  if fresh then
    rs(mt, "__newindex", ni)
    if not pc(smt, T, mt) then return end
  else
    if not pc(rs, mt, "__newindex", ni) then return end
  end
end
watch(E) watch(G)
local function scan()
  local found = {}
  for _, T in nx, {E, G} do
    local k, v = nx(T)
    while k ~= nil do
      if not seen[k] then seen[k] = true found[#found + 1] = {k, v} end
      k, v = nx(T, k)
    end
  end
  for i = 1, #found do pc(check, found[i][1], found[i][2]) end
end
local function finish()
  phase = 2
  local m = E.main
  if tp(m) ~= "function" then return end
  local function w(...)
    phase = 3
    local f = queue
    queue = {}
    for i = 1, #f do pc(report, f[i][1], f[i][2]) end
    if {intervalo} > 0 then
      local t = CreateTimer()
      TimerStart(t, {intervalo}, true, function() pc(scan) end)
    end
    return m(...)
  end
  local done = false
  if rg(E, "main") ~= nil then E.main = w done = true end
  if G ~= nil and rg(G, "main") ~= nil then G.main = w done = true end
  if not done then E.main = w end
end
rs(E, "{ponte}", finish)
seen["{ponte}"] = true
end)()
'''
TAIL_CODE = '(function() local f = {ponte} {ponte} = nil if f then f() end end)()\n'

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

CREATES_BY_NAME = ('rawset',)
READS_ENV = frozenset(('pairs', 'next', 'rawget', 'rawlen', 'getmetatable', 'ipairs', 'type', 'tostring',
                       'rawequal'))
_GAME_SCRIPTS_DIR = {}


def _nothing(*_a, **_k):
    pass


def _literal_text(e):
    return e.value if type(e) is lua_ast.Literal and e.kind == 'string' and isinstance(e.value, str) else None


def _is_env(e):
    return type(e) is lua_ast.Name and e.name in ('_G', '_ENV')


def _children(n):
    for field_id in type(n).__slots__:
        stack = [getattr(n, field_id, None)]
        while stack:
            v = stack.pop()
            if isinstance(v, lua_ast.Node):
                yield field_id, v
            elif isinstance(v, (list, tuple)):
                stack.extend(reversed(v))


def map_names(chunk, max_depth=0):
    name_list, dynamic_fields = set(), []
    stack = [(chunk.body, None)]
    while stack:
        no, parent = stack.pop()
        if isinstance(no, (list, tuple)):
            stack.extend((x, parent) for x in no if isinstance(x, (lua_ast.Node, list, tuple)))
            continue
        if not isinstance(no, lua_ast.Node):
            continue
        t = type(no)
        if t is lua_ast.AssignStmt:
            for tgt in no.targets:
                if type(tgt) is lua_ast.Name:
                    name_list.add(tgt.name)
                elif type(tgt) is lua_ast.Index and _is_env(tgt.base):
                    k = _literal_text(tgt.key)
                    if k is None:
                        dynamic_fields.append('a global is written with a computed name (line %d)' % tgt.line)
                    else:
                        name_list.add(k)
        elif t is lua_ast.FunctionStmt and not no.is_local:
            pieces = re.split(r'[.:]', no.name)
            if len(pieces) == 1:
                name_list.add(pieces[0])
            elif len(pieces) == 2 and pieces[0] in ('_G', '_ENV'):
                name_list.add(pieces[1])
        elif t is lua_ast.Call and type(no.func) is lua_ast.Name:
            f = no.func.name
            if f in CREATES_BY_NAME and no.args and _is_env(no.args[0]):
                k = _literal_text(no.args[1]) if len(no.args) > 1 else None
                if k is None:
                    dynamic_fields.append('%s writes a global with a computed name (line %d)' % (f, no.line))
                else:
                    name_list.add(k)
            elif f == 'setmetatable' and no.args and _is_env(no.args[0]):
                dynamic_fields.append('the map sets a metatable on %s (line %d)' % (no.args[0].name, no.line))
            elif f in ('load', 'loadstring'):
                s = _literal_text(no.args[0]) if no.args else None
                if s is None or max_depth > 3:
                    dynamic_fields.append('%s of a computed text (line %d)' % (f, no.line))
                else:
                    try:
                        n2, d2 = map_names(lua_ast.parse(s), max_depth + 1)
                    except lua_ast.LuaSyntaxError:
                        n2, d2 = set(), []
                    name_list |= n2
                    dynamic_fields += d2
        if _is_env(no) and parent is not None and not _read_only(parent, no):
            dynamic_fields.append('%s is used as a value (line %d)' % (no.name, no.line))
        for _field, child in _children(no):
            stack.append((child, no))
    return name_list, dynamic_fields


def _read_only(parent, no):
    t = type(parent)
    if t is lua_ast.Index and parent.base is no:
        return True
    if t is lua_ast.Call and type(parent.func) is lua_ast.Name and parent.args and parent.args[0] is no:
        return (
            parent.func.name in READS_ENV or parent.func.name in CREATES_BY_NAME or parent.func.name == 'setmetatable'
        )
    if t is lua_ast.Binary and parent.op in ('==', '~='):
        return True
    return False


def game_names(ref=None):
    ref = ref or DEFAULT_REF
    if ref not in _GAME_SCRIPTS_DIR:
        nil, all_items = set(), set()
        for file_ in ('common.j', 'blizzard.j'):
            with open(jass_to_lua.ref_file(ref, file_), encoding='utf-8', errors='surrogateescape') as f:
                s = jass_ast.parse(f.read())
            for g in s.globals:
                all_items.add(g.name)
                if file_ == 'blizzard.j':
                    nil.add(g.name)
            for f in s.functions:
                all_items.add(f.name)
            for n in getattr(s, 'natives', ()):
                all_items.add(n.name)
        _GAME_SCRIPTS_DIR[ref] = (frozenset(nil), frozenset(all_items))
    return _GAME_SCRIPTS_DIR[ref]


def pack_signatures(per_pack=PER_PACK):
    import decoy_names
    out = {}
    for pack, d in sorted(decoy_names.data_bytes().items()):
        k = 0
        for n in d.get('declared') or ():
            if k >= per_pack:
                break
            if RX_NAME_TOKEN.match(n) and n not in out:
                out[n] = pack
                k += 1
    return out


def inject(body_text, language, hook=DEFAULT_HOOK, stub=False, interval=INTERVAL, signatures=True, ref=None,
           log=None, type_name=TYPES['global'], signature_kind=TYPES['signature'], extras=(), **other_entries):
    log = log or _nothing
    details = {'piece': 'globals_lua', 'ok': True, 'changed': False, 'language': (language or '').lower(), 'why': None,
               'hook': hook, 'stub': bool(stub), 'allowed': 0, 'dynamic_fields': [], 'checks_names': False,
               'signatures': 0, 'interval': float(interval), 'bytes': 0, 'gates': {}}
    if other_entries:
        details['ignored_options'] = sorted(other_entries)
    if details['language'] != 'lua':
        details['why'] = ('the map script is %s: the global watch is the Lua piece (a JASS map has no global table to '
                          'watch; the name decoys cover it there)' % (language or 'unknown'))
        return body_text, details
    if not (isinstance(hook, str) and RX_NAME_TOKEN.match(hook) and hook not in RESERVED):
        raise ValueError('hook: %r is not a Lua name' % (hook,))
    if not (0 <= float(interval) <= 3600):
        raise ValueError('intervalo: %r is not 0..3600 seconds' % (interval,))
    good = '﻿' if body_text.startswith('﻿') else ''
    block_body = body_text[len(good):]
    if MARK in block_body:
        details['why'] = 'the script already carries the global watch (%s)' % MARK
        return body_text, details
    try:
        chunk = lua_ast.parse(block_body)
    except lua_ast.LuaSyntaxError as e:
        details['ok'] = False
        details['why'] = 'the Lua script does not parse (line %d): %s' % (e.line, e.message)
        return body_text, details
    map_own, dynamic_fields = map_names(chunk)
    game_nil_globals, game_all_names = game_names(ref)
    allowed = sorted(n for n in (map_own | game_nil_globals | {hook} | set(extras or ())) if RX_NAME_TOKEN.match(n))
    sig = {}
    if signatures:
        sig = dict((n, p) for n, p in pack_signatures().items() if n not in map_own and n not in game_all_names
                   and n != hook and n != BRIDGE)
    details['dynamic_fields'] = sorted(set(dynamic_fields))[:20]
    details['checks_names'] = not dynamic_fields
    details['allowed'] = len(allowed)
    details['signatures'] = len(sig)
    iv = float(interval)
    head_line = (HEAD_CODE.replace('{permitidos}', ' '.join(allowed))
                 .replace('{assinaturas}', ' '.join('%s=%s' % kv for kv in sorted(sig.items())))
                 .replace('{checa_nomes}', 'true' if details['checks_names'] else 'false')
                 .replace('{intervalo}', ('%d' % iv) if iv == int(iv) else repr(iv))
                 .replace('{tipo_assinatura}', '%d' % int(signature_kind)).replace('{tipo}', '%d' % int(type_name))
                 .replace('{det_assinatura}', DETAILS['signature']).replace('{det_depois}', DETAILS['after_diag'])
                 .replace('{det_estranho}', DETAILS['foreign'])
                 .replace('{gancho}', hook).replace('{ponte}', BRIDGE))
    head_line = lua_ast.canonical(head_line) + '\n'
    nl = '\r\n' if '\r\n' in block_body else '\n'
    head = MARK + '\n' + (STUB.replace('{gancho}', hook) if stub else '') + ';' + head_line.rstrip('\n') + ';\n'
    end_pos = len(block_body)
    if chunk.body and isinstance(chunk.body[-1], lua_ast.ReturnStmt):
        end_pos = chunk.body[-1].span[0]
    before, after_diag = block_body[:end_pos], block_body[end_pos:]
    if before and not before.endswith('\n'):
        before += nl
    tail = ';' + TAIL_CODE.replace('{ponte}', BRIDGE).rstrip('\n') + ';\n'
    new = good + head.replace('\n', nl) + before + tail.replace('\n', nl) + after_diag
    try:
        lua_ast.parse(new[len(good):])
    except lua_ast.LuaSyntaxError as e:
        raise SystemExit('ABORT (G1): the injected Lua does not parse (line %d): %s' % (e.line, e.message))
    details['gates']['G1 parse'] = 'ok (the injected script parses as Lua 5.3)'
    details['changed'] = True
    details['bytes'] = len(new) - len(body_text)
    log(
        'ANTICHEAT_GLOBAIS_LUA: %d global name(s) the map may create, %d pack signature(s), names %s; +%d B'
        % (
            len(allowed),
            len(sig),
            'checked' if details['checks_names'] else 'not checked (%s)' % details['dynamic_fields'][0],
            details['bytes'],
        )
    )
    return new, details

