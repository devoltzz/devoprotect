# The anti-cheat policy: what happens when a cheat is found (warn, block saves, defeat, end).
import re


HOOK = 'DevoAC_Acusa'
MAP_HOOK = 'DevoProtect_CheatUsed'
PREFIX = 'DEVOPOL_'
ACTIONS = ('warn', 'nosave', 'defeat', 'end')
CODE_KIND = 10
SLOTS = 28
DELAY = 1.0
END_DELAY = 6.0
RX_NAME_TOKEN = re.compile(r'^[A-Za-z]\w*$')


def _check(action_codes, hook, prefix):
    bad_ones = sorted(set(action_codes) - set(ACTIONS))
    if bad_ones:
        raise ValueError('action %s is not one of %s' % (', '.join(bad_ones), ', '.join(ACTIONS)))
    if not RX_NAME_TOKEN.match(hook) or not RX_NAME_TOKEN.match(prefix):
        raise ValueError('invalid name: hook %r, prefix %r' % (hook, prefix))


def _jass(action_codes, hook, prefix, map_hook):
    P = prefix
    defeat, end_pos, nosave, warn = (
        'defeat' in action_codes,
        'end' in action_codes,
        'nosave' in action_codes,
        'warn' in action_codes,
    )
    g = ['    boolean array %sflag' % P,
         '    boolean array %sdito' % P,
         '    string array %sqm' % P,
         '    integer %sqn = 0' % P,
         '    boolean %spend = false' % P,
         '    timer %st = null' % P]
    if defeat:
        g.append('    boolean array %sdq' % P)
    if end_pos:
        g += ['    boolean %sended = false' % P, '    boolean %sendq = false' % P, '    timer %ste = null' % P]
    f = []
    f.append(
        'function %sSlot takes player p returns integer\n'
        '    if p == null then\n        return %d\n    endif\n    return GetPlayerId(p)\nendfunction\n' % (P, SLOTS)
    )
    f.append('function %sMsg takes player p, integer kind, string detail returns string\n'
             '    if p == null then\n'
             '        return "|cffff3333[Anti-cheat]|r The map was modified (" + detail + ")."\n'
             '    endif\n'
             '    if kind == %d then\n'
             '        return "|cffff3333[Anti-cheat]|r " + GetPlayerName(p) + " used the cheat code " + detail + "."\n'
             '    endif\n'
             '    return "|cffff3333[Anti-cheat]|r " + GetPlayerName(p) + " changed a protected value (" + detail + '
             '"); it was undone."\nendfunction\n' % (P, CODE_KIND))
    if end_pos:
        f.append('function %sFim takes nothing returns nothing\n    call EndGame(true)\nendfunction\n' % P)
    block_body = ['function %sFlush takes nothing returns nothing' % P,
                  '    local integer i = 0',
                  '    local integer j']
    block_body += ['    set %spend = false' % P,
                   '    loop',
                   '        exitwhen i >= %sqn' % P,
                   '        call DisplayTimedTextToForce(GetPlayersAll(), 10.0, %sqm[i])' % P,
                   '        set i = i + 1',
                   '    endloop',
                   '    set %sqn = 0' % P]
    if defeat:
        block_body += [
            '    set i = 0',
            '    loop',
            '        exitwhen i > %d' % SLOTS,
            '        if %sdq[i] then' % P,
            '            set %sdq[i] = false' % P,
            '            if i == %d then' % SLOTS,
            '                set j = 0',
            '                loop',
            '                    exitwhen j >= GetBJMaxPlayerSlots()',
            '                    if GetPlayerController(Player(j)) == MAP_CONTROL_USER and '
            'GetPlayerSlotState(Player(j)) == PLAYER_SLOT_STATE_PLAYING then',
            '                        call CustomDefeatBJ(Player(j), "The anti-cheat found the map modified.")',
            '                    endif',
            '                    set j = j + 1',
            '                endloop',
            '            else',
            '                call CustomDefeatBJ(Player(i), "The anti-cheat found a cheat.")',
            '            endif',
            '        endif',
            '        set i = i + 1',
            '    endloop',
        ]
    if end_pos:
        block_body += ['    if %sendq then' % P,
                       '        set %sendq = false' % P,
                       '        if %ste == null then' % P,
                       '            set %ste = CreateTimer()' % P,
                       '        endif',
                       '        call TimerStart(%ste, %.1f, false, function %sFim)' % (P, END_DELAY, P)]
        block_body.append('    endif')
    block_body.append('endfunction\n')
    f.append('\n'.join(block_body))
    hook_lines = ['function %s takes player p, integer kind, string detail returns nothing' % hook,
                  '    local integer s = %sSlot(p)' % P,
                  '    local integer k = kind',
                  '    local boolean primeira = not %sflag[s]' % P,
                  '    if k < 0 or k > 63 then',
                  '        set k = 63',
                  '    endif',
                  '    set %sflag[s] = true' % P]
    if warn:
        hook_lines += ['    if not %sdito[s * 64 + k] and %sqn < 32 then' % (P, P),
                       '        set %sdito[s * 64 + k] = true' % P,
                       '        set %sqm[%sqn] = %sMsg(p, kind, detail)' % (P, P, P),
                       '        set %sqn = %sqn + 1' % (P, P),
                       '    endif']
    if defeat:
        hook_lines += ['    if primeira then', '        set %sdq[s] = true' % P, '    endif']
    if end_pos:
        hook_lines += ['    if not %sended then' % P, '        set %sended = true' % P, '        set %sendq = true' % P,
                       '    endif']
    hook_lines += ['    if not %spend then' % P,
                   '        set %spend = true' % P,
                   '        if %st == null then' % P,
                   '            set %st = CreateTimer()' % P,
                   '        endif',
                   '        call TimerStart(%st, %.1f, false, function %sFlush)' % (P, DELAY, P),
                   '    endif',
                   'endfunction\n']
    f.append('\n'.join(hook_lines))
    f.append('function %sCheated takes player p returns boolean\n'
             '    if p == null then\n        return %sflag[%d]\n    endif\n'
             '    return %sflag[GetPlayerId(p)] or %sflag[%d]\nendfunction\n' % (P, P, SLOTS, P, P, SLOTS))
    if nosave:
        f.append('function %sPreloadGenEnd takes string f returns nothing\n'
                 '    if %sCheated(GetLocalPlayer()) then\n        return\n    endif\n'
                 '    call PreloadGenEnd(f)\nendfunction\n' % (P, P))
    return g, '\n'.join(f)


def _jass_insert(body_text, tree, globals_block, func_list):
    pieces = re.split(r'(\r\n?|\n)', body_text)
    line_list = [pieces[i] + (pieces[i + 1] if i + 1 < len(pieces) else '') for i in range(0, len(pieces), 2)]
    nl = '\r\n' if body_text.count('\r\n') * 2 > body_text.count('\n') else '\n'
    block_entry = next((it for it in tree.items if type(it).__name__ == 'Globals'), None)
    added = [lx + nl for lx in func_list.rstrip('\n').split('\n') + ['']]
    if block_entry is not None:
        line_list[block_entry.end_line:block_entry.end_line] = added
        line_list[block_entry.end_line - 1:block_entry.end_line - 1] = [lx + nl for lx in globals_block]
    else:
        first = next((it for it in tree.items if type(it).__name__ == 'Function' and not it.is_native), None)
        if first is None:
            raise ValueError('the script declares no function')
        line_list[first.line - 1 : first.line - 1] = [
            lx + nl for lx in ['globals'] + list(globals_block) + ['endglobals', '']
        ] + added
    return ''.join(line_list)


def _jass_swap_map_hook(body_text, tree, prefix):
    f = tree.function_index.get(MAP_HOOK)
    if f is None or f.is_native:
        return body_text, False
    if [t for t, _n in f.params] != ['player'] or f.return_type != 'boolean':
        raise ValueError('%s has to be `takes player p returns boolean` (the map declares another signature)'
                         % MAP_HOOK)
    pieces = re.split(r'(\r\n?|\n)', body_text)
    line_list = [pieces[i] + (pieces[i + 1] if i + 1 < len(pieces) else '') for i in range(0, len(pieces), 2)]
    nl = '\r\n' if body_text.count('\r\n') * 2 > body_text.count('\n') else '\n'
    fname = f.params[0][1]
    new = ['function %s takes player %s returns boolean' % (MAP_HOOK, fname),
           '    return %sCheated(%s)' % (prefix, fname), 'endfunction']
    line_list[f.line - 1:f.end_line] = [lx + nl for lx in new]
    return ''.join(line_list), True


def _inject_jass(body_text, action_codes, hook, prefix, map_hook):
    import anticheat_ledger
    import jass_ast
    tree = jass_ast.parse(body_text)
    if hook in tree.function_index:
        raise ValueError('the script already declares %s' % hook)
    details = {'nosave': 0, 'map_hook_replaced': False}
    if map_hook:
        body_text, details['map_hook_replaced'] = _jass_swap_map_hook(body_text, tree, prefix)
        if details['map_hook_replaced']:
            tree = jass_ast.parse(body_text)
    if 'nosave' in action_codes:
        body_text, pluralize = anticheat_ledger._rename_calls(body_text, {'PreloadGenEnd': prefix + 'PreloadGenEnd'})
        details['nosave'] = pluralize.get('PreloadGenEnd', 0)
        if details['nosave']:
            tree = jass_ast.parse(body_text)
    globals_block, func_list = _jass(action_codes, hook, prefix, map_hook)
    new = _jass_insert(body_text, tree, globals_block, func_list)
    jass_ast.parse(new)
    return new, details


def _lua(action_codes, hook, prefix, map_hook):
    defeat, end_pos, nosave, warn = (
        'defeat' in action_codes,
        'end' in action_codes,
        'nosave' in action_codes,
        'warn' in action_codes,
    )
    L = ['-- DevoProtect anti-cheat: what to do when something is found',
         '%s = (function()' % hook,
         '    local flag, said, dq, qm = {}, {}, {}, {}',
         '    local pend, ended, endq, t, te = false, false, false, nil, nil',
         '    local function slot(p) if p == nil then return %d end return GetPlayerId(p) end' % SLOTS,
         '    local function msg(p, kind, detail)',
         '        if p == nil then return "|cffff3333[Anti-cheat]|r The map was modified (" .. detail .. ")." end',
         '        if kind == %d then return "|cffff3333[Anti-cheat]|r " .. GetPlayerName(p) .. " used the cheat code " '
         '.. detail .. "." end' % CODE_KIND,
         '        return "|cffff3333[Anti-cheat]|r " .. GetPlayerName(p) .. " changed a protected value (" .. detail '
         '.. "); it was undone."',
         '    end',
         '    local function cheated(p)',
         '        if p == nil then return flag[%d] == true end' % SLOTS,
         '        return flag[GetPlayerId(p)] == true or flag[%d] == true' % SLOTS,
         '    end',
         '    local function flush()',
         '        pend = false',
         '        for i = 1, #qm do DisplayTimedTextToForce(GetPlayersAll(), 10.0, qm[i]) end',
         '        qm = {}']
    if defeat:
        L += ['        for i = 0, %d do' % SLOTS,
              '            if dq[i] then',
              '                dq[i] = false',
              '                if i == %d then' % SLOTS,
              '                    for j = 0, GetBJMaxPlayerSlots() - 1 do',
              '                        local pj = Player(j)',
              '                        if GetPlayerController(pj) == MAP_CONTROL_USER and GetPlayerSlotState(pj) == '
              'PLAYER_SLOT_STATE_PLAYING then CustomDefeatBJ(pj, "The anti-cheat found the map modified.") end',
              '                    end',
              '                else',
              '                    CustomDefeatBJ(Player(i), "The anti-cheat found a cheat.")',
              '                end',
              '            end',
              '        end']
    if end_pos:
        L += ['        if endq then',
              '            endq = false',
              '            if te == nil then te = CreateTimer() end',
              '            TimerStart(te, %.1f, false, function() EndGame(true) end)' % END_DELAY,
              '        end']
    L += ['    end']
    if nosave:
        L += ['    local pge = PreloadGenEnd',
              '    if pge then',
              '        PreloadGenEnd = function(f)',
              '            if cheated(GetLocalPlayer()) then return end',
              '            return pge(f)',
              '        end',
              '    end']
    if map_hook:
        L += ['    %sCheated = cheated' % prefix]
    L += ['    return function(p, kind, detail)',
          '        local s = slot(p)',
          '        local k = kind',
          '        if k < 0 or k > 63 then k = 63 end',
          '        local primeira = not flag[s]',
          '        flag[s] = true']
    if warn:
        L += ['        if not said[s * 64 + k] and #qm < 32 then',
              '            said[s * 64 + k] = true',
              '            qm[#qm + 1] = msg(p, kind, detail)',
              '        end']
    if defeat:
        L += ['        if primeira then dq[s] = true end']
    if end_pos:
        L += ['        if not ended then ended = true; endq = true end']
    L += ['        if not pend then',
          '            pend = true',
          '            if t == nil then t = CreateTimer() end',
          '            TimerStart(t, %.1f, false, flush)' % DELAY,
          '        end',
          '    end',
          'end)()', '']
    return '\n'.join(L)


def _inject_lua(body_text, action_codes, hook, prefix, map_hook):
    import lua_ast
    chunk = lua_ast.parse(body_text)
    if hook in chunk.functions or any(isinstance(s, lua_ast.AssignStmt) and any(
            isinstance(t, lua_ast.Name) and t.name == hook for t in s.targets) for s in chunk.body):
        raise ValueError('the script already defines %s' % hook)
    has_stub = bool(map_hook) and (MAP_HOOK in chunk.functions or any(
        isinstance(s, lua_ast.AssignStmt) and any(isinstance(t, lua_ast.Name) and t.name == MAP_HOOK
                                                  for t in s.targets) for s in chunk.body))
    if has_stub and chunk.body and isinstance(chunk.body[-1], lua_ast.ReturnStmt):
        raise ValueError('the Lua script ends in a return: the map-maker hook cannot be replaced after it')
    nl = '\r\n' if body_text.count('\r\n') * 2 > body_text.count('\n') else '\n'
    head_text = _lua(action_codes, hook, prefix, has_stub).replace('\n', nl)
    new = head_text + body_text
    details = {'nosave': 0, 'map_hook_replaced': False}
    if 'nosave' in action_codes:
        details['nosave'] = len(re.findall(r'\bPreloadGenEnd\s*\(', body_text))
    if has_stub:
        new = new.rstrip('\r\n') + nl + ('%s = function(p) return %sCheated(p) end' % (MAP_HOOK, prefix)) + nl
        details['map_hook_replaced'] = True
    lua_ast.parse(new)
    return new, details


def inject(body_text, language, action_codes=('warn',), hook=HOOK, prefix=PREFIX, map_hook=True):
    if language not in ('jass', 'lua'):
        raise ValueError('language has to be jass or lua, not %r' % (language,))
    _check(action_codes, hook, prefix)
    action_codes = tuple(a for a in ACTIONS if a in set(action_codes))
    as_bytes = isinstance(body_text, bytes)
    if as_bytes:
        body_text = body_text.decode('utf-8', 'surrogateescape')
    details = {'ok': True, 'piece': 'policy', 'language': language, 'action_codes': list(action_codes), 'hook': hook,
               'already_injected': False}
    if re.search(r'\b' + re.escape(prefix), body_text):
        details.update(already_injected=True, nosave=0, map_hook_replaced=False, summary='already injected')
        return (body_text.encode('utf-8', 'surrogateescape') if as_bytes else body_text), details
    new, extra = (_inject_jass if language == 'jass' else _inject_lua)(body_text, action_codes, hook, prefix, map_hook)
    details.update(extra)
    details['summary'] = 'hook %s (%s)%s%s' % (
        hook, ', '.join(action_codes) or 'flag only',
        '; %d PreloadGenEnd call(s) of the map replaced' % extra['nosave'] if extra['nosave'] else '',
        '; %s body replaced' % MAP_HOOK if extra['map_hook_replaced'] else '')
    return (new.encode('utf-8', 'surrogateescape') if as_bytes else new), details

