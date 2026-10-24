# The anti-cheat for the game's own cheat codes, armed in single player only.
import os
import re

import jass_ast

HERE = os.path.dirname(os.path.abspath(__file__))

SOURCE = next((p for p in (os.path.normpath(os.path.join(HERE, '..', 'kk', 'compat', 'kk_cheat.j')),
                           os.path.join(HERE, 'kk_cheat.j')) if os.path.isfile(p)),
              os.path.normpath(os.path.join(HERE, '..', 'kk', 'compat', 'kk_cheat.j')))
HOOK = 'DevoAC_Acusa'
PREFIX = 'DevoAC_cc_'
TYPE_CODE = 1
INTERVAL = 2.0
MODES = ('auto', 'humans', 'reload', 'humans+reload')
NATIVES = (('IsNoVictoryCheat', 'itvexesme'), ('IsNoDefeatCheat', 'strengthandhonor'))
SIGNATURE = ['player', 'integer', 'string']
OWN_NAMES = ('arm', 'armed', 'human', 'reported', 'report', 'natives', 'clock')
STUB = '''function {hook} takes player p, integer kind, string detail returns nothing
    local integer i=0
    loop
        exitwhen i>=bj_MAX_PLAYERS
        call DisplayTimedTextToPlayer(Player(i), 0, 0, 20, "|cffff3232Cheat detected:|r " + GetPlayerName(p) + " (" + detail + ")")
        set i=i+1
    endloop
endfunction
'''
BODY = '''function {report} takes player p, integer i returns nothing
    if not {reported}[i] then
        set {reported}[i]=true
        call {hook}(p, {type_name}, {listing}[i])
    endif
endfunction

function {chat} takes nothing returns nothing
    local string s=StringCase(GetEventPlayerChatString(), false)
    local integer i=0
    loop
        exitwhen i>={n}
        if {contains}(s, {listing}[i]) then
            call {report}(GetTriggerPlayer(), i)
            return
        endif
        set i=i+1
    endloop
endfunction

{chat_armer_source}
function {natives} takes nothing returns nothing
{native_calls}endfunction

function {arm} takes nothing returns nothing
    local integer i=0
    local integer n=0
    loop
        exitwhen i>=bj_MAX_PLAYERS
        if GetPlayerController(Player(i))==MAP_CONTROL_USER and GetPlayerSlotState(Player(i))==PLAYER_SLOT_STATE_PLAYING then
            if n==0 then
                set {human}=Player(i)
            endif
            set n=n+1
        endif
        set i=i+1
    endloop
    if {condition} then
        set {armed}=true
        call {chat_armer}()
        set {clock}=CreateTimer()
        call TimerStart({clock}, {interval}, true, function {natives})
    endif
endfunction
'''
CONDITIONS = {'humans': 'n==1', 'reload': 'ReloadGameCachesFromDisk()',
              'humans+reload': 'n==1 and ReloadGameCachesFromDisk()'}
LUA_WRAPPER = '''do
    local map_main = main
    function main()
        {arm}()
        if map_main then map_main() end
    end
end
'''


def _lines_of(body_text, f):
    return '\n'.join(body_text.split('\n')[f.line - 1:f.end_line]) + '\n'


NAMES_EN = {'KK_CH_N': 'KK_CH_N', 'KK_ch_code': 'KK_ch_code', 'KK_ch_trigger': 'KK_ch_trigger',
            'KK_cheat_arm': 'KK_cheat_arm', 'KK_cheat_chat': 'KK_cheat_chat',
            'KK_cheat_contains': 'KK_cheat_contains', 'KK_cheat_detected': 'KK_cheat_detected',
            'KK_cheat_save_free': 'KK_cheat_save_free', 'KK_cheat_used': 'KK_cheat_used', 'end_pos': 'last'}


def in_english(body_text):
    rx = re.compile(r'\b(%s)\b' % '|'.join(re.escape(n) for n in sorted(NAMES_EN, key=len, reverse=True)))
    return rx.sub(lambda m: NAMES_EN[m.group(1)], body_text)


def _call(f, fname):
    return any(isinstance(n, jass_ast.Call) and n.name == fname for n in jass_ast.walk(f))


def read_source(source=None):
    import layer
    import anticheat_ledger
    with open(source or SOURCE, encoding='ascii') as f:
        raw_bytes = in_english(anticheat_ledger.without_comments(f.read(), 'jass'))
    globals_block, rest = layer.split_globals(raw_bytes)
    body_text = 'globals\n' + '\n'.join(globals_block) + '\nendglobals\n' + rest
    tree = jass_ast.parse(body_text)
    funcs = [f for f in tree.functions if not f.is_native]

    def singular(role, matches):
        if len(matches) != 1:
            raise ValueError('kk_cheat.j: %d function(s)/global(s) in the role %s (expected 1): %s'
                             % (len(matches), role, [getattr(x, 'name', x) for x in matches]))
        return matches[0].name
    piece_list = {
        'chat_armer': singular('armer', [f for f in funcs if _call(f, 'TriggerRegisterPlayerChatEvent')]),
        'chat': singular('chat action', [f for f in funcs if _call(f, 'GetEventPlayerChatString')]),
        'contains': singular('substring search', [f for f in funcs if [t for t, _n in f.params] == ['string', 'string']
                                                  and f.return_type == 'boolean']),
        'listing': singular('listing', [g for g in tree.globals if g.is_array and g.type == 'string']),
        'n': singular('tally', [g for g in tree.globals if g.is_constant and g.type == 'integer']),
        'trigger': singular('trigger', [g for g in tree.globals if g.type == 'trigger' and not g.is_array]),
    }
    armer_body = _lines_of(body_text, tree.function_index[piece_list['chat_armer']])
    matches = re.findall(r'set\s+%s\s*\[\s*(\d+)\s*\]\s*=\s*"([^"\\]*)"' % re.escape(piece_list['listing']), armer_body)
    lit = next(g for g in tree.globals if g.name == piece_list['n']).initializer
    n = int(jass_ast.literal_value(lit.kind, lit.text))
    codes = [c for _i, c in sorted((int(i), c) for i, c in matches)]
    if [int(i) for i, _c in sorted(matches, key=lambda x: int(x[0]))] != list(range(n)) or len(set(codes)) != n:
        raise ValueError('kk_cheat.j: the list does not match the count (%d codes, %s=%d)' % (len(codes),
                                                                                                piece_list['n'], n))
    for _nat, code_part in NATIVES:
        if code_part not in codes:
            raise ValueError('kk_cheat.j: the code %s is missing (the one of native %s)' % (code_part, _nat))
    piece_list.update(body_text=body_text, codes=codes,
                      globals_block=dict((g.name, lx.strip()) for g, lx in zip(tree.globals, globals_block)),
                      func_list=dict((f.name, _lines_of(body_text, f)) for f in funcs))
    return piece_list


def _renamer(piece_list, prefix):
    name_list = list(piece_list['globals_block']) + list(piece_list['func_list'])
    return dict((n, prefix + (n[3:] if n.startswith('KK_') else n)) for n in name_list)


def _swap(body_text, map_path):
    rx = re.compile(r'\b(%s)\b' % '|'.join(re.escape(n) for n in sorted(map_path, key=len, reverse=True)))
    return rx.sub(lambda m: map_path[m.group(1)], body_text)


def jass_block(hook=HOOK, stub=False, method='humans+reload', type_name=TYPE_CODE, interval=INTERVAL, prefix=PREFIX,
               source=None):
    if method not in CONDITIONS:
        raise ValueError('mode %r: one of %s' % (method, ', '.join(CONDITIONS)))
    piece_list = read_source(source)
    ren = _renamer(piece_list, prefix)
    own = dict((k, prefix + k) for k in OWN_NAMES)
    if set(own.values()) & set(ren.values()):
        raise ValueError(
            'name of this piece equal to one of the source: %s' % sorted(set(own.values()) & set(ren.values()))
        )
    chat_armer_source = _swap(piece_list['func_list'][piece_list['chat_armer']], ren)
    in_use = set(
        re.findall(r'\b\w+\b', _swap(piece_list['func_list'][piece_list['contains']], ren) + chat_armer_source)
    )
    globals_block = [_swap(lx, ren) for g, lx in piece_list['globals_block'].items()
                     if ren[g] in in_use or g in (piece_list['listing'], piece_list['n'], piece_list['trigger'])]
    globals_block += ['boolean array %s' % own['reported'], 'player %s=null' % own['human'],
                      'boolean %s=false' % own['armed'], 'timer %s=null' % own['clock']]
    native_calls = ''.join('    if %s() then\n        call %s(%s, %d)\n    endif\n' % (
        nat, own['report'], own['human'], piece_list['codes'].index(code_part)) for nat, code_part in NATIVES)
    func_list = (
        (STUB.format(hook=hook) + '\n' if stub else '')
        + _swap(piece_list['func_list'][piece_list['contains']], ren)
        + '\n'
        + BODY.format(
            hook=hook,
            type_name=int(type_name),
            listing=ren[piece_list['listing']],
            n=ren[piece_list['n']],
            contains=ren[piece_list['contains']],
            chat=ren[piece_list['chat']],
            chat_armer=ren[piece_list['chat_armer']],
            chat_armer_source=chat_armer_source,
            native_calls=native_calls,
            condition=CONDITIONS[method],
            interval=repr(float(interval)),
            **own,
        )
    )
    name_list = dict(
        own,
        chat=ren[piece_list['chat']],
        chat_armer_source=ren[piece_list['chat_armer']],
        listing=ren[piece_list['listing']],
        contains=ren[piece_list['contains']],
    )
    return globals_block, func_list, dict(name_list, codes=piece_list['codes'])


def _resolve_mode(method, body_text):
    if method not in MODES:
        raise ValueError('mode %r: one of %s' % (method, ', '.join(MODES)))
    if method != 'auto':
        return method, 'requested'
    return 'humans+reload', 'auto: only the reload tells single player from an online game alone (measured in game)'


def inject(body_text, language, hook=HOOK, stub=False, method='auto', type_name=TYPE_CODE, interval=INTERVAL,
           prefix=PREFIX, source=None, ref=None):
    if language not in ('jass', 'lua'):
        raise ValueError('language %r: jass or lua' % (language,))
    if not re.match(r'^[A-Za-z]\w*$', hook) or not re.match(r'^[A-Za-z]\w*$', prefix):
        raise ValueError('invalid name: hook %r, prefix %r' % (hook, prefix))
    as_bytes = isinstance(body_text, bytes)
    if as_bytes:
        body_text = body_text.decode('latin-1') if language == 'jass' else body_text.decode('utf-8', 'surrogateescape')
    details = {'ok': False, 'piece': 'codes', 'language': language, 'hook': hook, 'type_name': int(type_name),
               'already_injected': False, 'stub': False}
    new = (_inject_jass if language == 'jass' else _inject_lua)(
        body_text, details, hook, stub, method, type_name, interval, prefix, source, ref
    )
    details['ok'] = True
    details['line_list'] = new.count('\n') - body_text.count('\n')
    if as_bytes:
        new = new.encode('latin-1') if language == 'jass' else new.encode('utf-8', 'surrogateescape')
    return new, details


def _shared(details, body_text, method, prefix, existing):
    if existing:
        details.update(already_injected=True, summary='already injected (%sarm in the script)' % prefix)
        return None
    if re.search(r'\b' + re.escape(prefix), body_text):
        raise ValueError(
            'the script already has names with the prefix %s (without the armer): nothing injected' % prefix
        )
    m, why = _resolve_mode(method, body_text)
    details.update(mode_asked=method, method=m, mode_reason=why)
    return m


def _inject_jass(body_text, details, hook, stub, method, type_name, interval, prefix, source, ref):
    import map_rewrite
    tree = jass_ast.parse(body_text)
    m = _shared(details, body_text, method, prefix, prefix + 'arm' in tree.function_index)
    if m is None:
        return body_text
    main = tree.function_index.get('main')
    if main is None or main.is_native:
        raise ValueError('the script has no function main')
    h = tree.function_index.get(hook)
    if h is not None:
        if h.is_native or [t for t, _n in h.params] != SIGNATURE or h.return_type != 'nothing':
            raise ValueError(
                'the hook %s exists with another signature (expected takes player, integer, string returns '
                'nothing)' % hook
            )
        if h.line > main.line:
            raise ValueError('the hook %s comes after main: JASS does not see it from inside the detector' % hook)
    elif not stub:
        raise ValueError('the hook %s is not in the script: inject it first (the integration) or use stub=True' % hook)
    globals_block, func_list, name_list = jass_block(hook, stub and h is None, m, type_name, interval, prefix, source)
    func_list = '// DevoProtect anti-cheat: the game\'s own cheat codes, in single player only\n' + func_list
    new = map_rewrite.insert(body_text, tree, globals_lines=globals_block, functions=func_list,
                             main_top=('    call %s()' % name_list['arm'],))
    jass_ast.parse(new)
    details.update(
        stub=stub and h is None,
        armer=name_list['arm'],
        armed_name=name_list['armed'],
        codes=len(name_list['codes']),
        native_calls=[n for n, _c in NATIVES],
        summary='%d codes by chat and %d natives by a %.1f s timer; armed at the top of main (%s)'
        % (len(name_list['codes']), len(NATIVES), float(interval), m),
    )
    return new


def _defined_in_lua(chunk, fname):
    import lua_ast
    if fname in chunk.functions:
        return True
    return any(isinstance(s, lua_ast.AssignStmt) and any(isinstance(t, lua_ast.Name) and t.name == fname
                                                          for t in s.targets) for s in chunk.body)


def _inject_lua(body_text, details, hook, stub, method, type_name, interval, prefix, source, ref):
    import jass_to_lua
    import lua_ast
    chunk = lua_ast.parse(body_text)
    m = _shared(details, body_text, method, prefix, prefix + 'arm' in chunk.functions)
    if m is None:
        return body_text
    if 'main' not in chunk.functions:
        raise ValueError('the script has no function main')
    if chunk.body and isinstance(chunk.body[-1], lua_ast.ReturnStmt):
        raise ValueError('the Lua ends in a return: nothing can come after it')
    present = _defined_in_lua(chunk, hook)
    if not present and not stub:
        raise ValueError('the hook %s is not in the script: inject it first (the integration) or use stub=True' % hook)
    globals_block, func_list, name_list = jass_block(hook, stub and not present, m, type_name, interval, prefix, source)
    lua, rc = jass_to_lua.converte('globals\n' + '\n'.join(globals_block) + '\nendglobals\n' + func_list, ref=ref,
                                   log=lambda *a: None)
    nl = '\r\n' if body_text.count('\r\n') * 2 > body_text.count('\n') else '\n'
    tail = ('-- DevoProtect anti-cheat: the game\'s own cheat codes, in single player only\n' + lua +
            LUA_WRAPPER.format(arm=name_list['arm']))
    new = body_text + ('' if body_text.endswith(('\n', '\r')) or not body_text else nl) + tail.replace('\n', nl)
    lua_ast.parse(new)
    details.update(
        stub=stub and not present,
        armer=name_list['arm'],
        armed_name=name_list['armed'],
        codes=len(name_list['codes']),
        native_calls=[n for n, _c in NATIVES],
        conversion=rc['gates'],
        summary='%d codes by chat and %d natives by a %.1f s timer; armed in a wrapper of main (%s)'
        % (len(name_list['codes']), len(NATIVES), float(interval), m),
    )
    return new

