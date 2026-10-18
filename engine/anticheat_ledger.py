# The anti-cheat ledger: undoes and reports gold, lumber and hero changes no call of the map explains.
import io
import os
import re

import jass_ast


HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_J = os.path.join(HERE, 'anticheat_ledger.j')
MODEL_LUA = os.path.join(HERE, 'anticheat_ledger.lua')
MODEL_MARKER = re.compile(r'^\s*(//|--)(<|\[\[)')


def without_comments(body_text, language):
    mark = '--' if language == 'lua' else '//'
    return '\n'.join(lx for lx in body_text.replace('\r\n', '\n').split('\n')
                     if not lx.lstrip().startswith(mark) or MODEL_MARKER.match(lx))
REF_AI = next((p for p in (os.path.normpath(os.path.join(HERE, '..', 'ref', '3.0', 'common.ai')),
                           os.path.join(HERE, 'ref', '3.0', 'common.ai')) if os.path.isfile(p)),
              os.path.normpath(os.path.join(HERE, '..', 'ref', '3.0', 'common.ai')))

GUARDED = (
    'SetPlayerState', 'SetPlayerStateBJ', 'AdjustPlayerStateBJ', 'AdjustPlayerStateSimpleBJ', 'SetPlayerFlagBJ',
    'MeleeStartingResources', 'SetPlayerHandicapXP', 'SetPlayerHandicapXPBJ',
    'SetHeroLevel', 'SetHeroLevelBJ', 'SetHeroXP', 'AddHeroXP', 'AddHeroXPSwapped', 'UnitStripHeroLevel',
    'SetHeroStr', 'SetHeroAgi', 'SetHeroInt', 'SetHeroStat', 'ModifyHeroStat',
    'UnitModifySkillPoints', 'ModifyHeroSkillPoints', 'ReplaceUnitBJ',
    'SetPlayerTechResearched', 'AddPlayerTechResearched', 'SetPlayerTechResearchedSwap', 'BlzDecPlayerTechResearched',
)
TECH_FUNCS = frozenset(('SetPlayerTechResearched', 'AddPlayerTechResearched', 'SetPlayerTechResearchedSwap',
                        'BlzDecPlayerTechResearched', 'GetPlayerTechCount', 'AddPlayerTechResearchedSwapped'))


def _default_upgrades():
    try:
        txt = io.open(REF_AI, encoding='latin-1').read()
    except OSError:
        return []
    return sorted(set(re.findall(r"'(R[A-Za-z0-9]{3})'", txt)))


def _rename_calls(text, name_list):
    out = []
    pluralize = {}
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == '"':
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if c == "'":
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == "'":
                    j += 1
                    break
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            j = i
            while j < n and text[j] not in '\r\n':
                j += 1
            out.append(text[i:j])
            i = j
            continue
        if c.isalpha() or c == '_':
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] == '_'):
                j += 1
            word = text[i:j]
            new = name_list.get(word)
            if new is not None:
                k = j
                while k < n and text[k] in ' \t':
                    k += 1
                if k < n and text[k] == '(':
                    out.append(new)
                    pluralize[word] = pluralize.get(word, 0) + 1
                    i = j
                    continue
            out.append(word)
            i = j
            continue
        out.append(c)
        i += 1
    return ''.join(out), pluralize


def _model_pieces(model):
    line_list = model.replace('\r\n', '\n').split('\n')
    begin = next((k for k, lx in enumerate(line_list) if lx.strip() == 'globals'), None)
    end_pos = next((k for k, lx in enumerate(line_list) if lx.strip() == 'endglobals'), None)
    if begin is None or end_pos is None or end_pos < begin:
        raise RuntimeError('the JASS model has no globals block')
    globals_block = '\n'.join(line_list[begin + 1:end_pos])
    funcs = '\n'.join(line_list[end_pos + 1:]).strip('\n')
    return globals_block, funcs


def _merge_jass(script, globals_block, funcs, init_call, after=None):
    line_list = script.replace('\r\n', '\n').split('\n')
    end_pos = next((k for k, lx in enumerate(line_list) if lx.strip() == 'endglobals'), None)
    if end_pos is None:
        start_main0 = next((k for k, lx in enumerate(line_list)
                            if re.match(r'^\s*function\s+main\s+takes\s+nothing\s+returns\s+nothing\s*$', lx)), None)
        if start_main0 is None:
            raise RuntimeError('the map script has no globals block and no main function')
        block_entry = ['globals'] + globals_block.split('\n') + ['endglobals', '', funcs, '']
        line_list = line_list[:start_main0] + block_entry + line_list[start_main0:]
    else:
        topo = end_pos
        if after:
            start_h = next((k for k in range(end_pos + 1, len(line_list))
                            if re.match(r'^\s*function\s+%s\s+takes\b' % re.escape(after), line_list[k])), None)
            end_h = None if start_h is None else next((k for k in range(start_h + 1, len(line_list))
                                                      if line_list[k].strip() == 'endfunction'), None)
            if end_h is not None:
                topo = end_h
        line_list = (
            line_list[:end_pos]
            + globals_block.split('\n')
            + line_list[end_pos : topo + 1]
            + ['', funcs, '']
            + line_list[topo + 1 :]
        )
    start_main = next((k for k, lx in enumerate(line_list)
                       if re.match(r'^\s*function\s+main\s+takes\s+nothing\s+returns\s+nothing\s*$', lx)), None)
    if start_main is None:
        raise RuntimeError('the map script has no main function (the ledger needs one)')
    main_end = next((k for k in range(start_main + 1, len(line_list)) if line_list[k].strip() == 'endfunction'), None)
    if main_end is None:
        raise RuntimeError('the map main has no endfunction')
    line_list = line_list[:main_end] + ['    ' + init_call] + line_list[main_end:]
    return '\n'.join(line_list)


def _map_techs(tree):
    out = set()
    for node in jass_ast.walk(tree):
        if isinstance(node, jass_ast.Call) and node.name in TECH_FUNCS:
            for a in node.args:
                if isinstance(a, jass_ast.Literal) and a.kind == 'rawcode':
                    out.add(jass_ast._unescape(a.text[1:-1]))
    return out


def _tech_list(tree, research):
    if not research:
        return []
    default_value = _default_upgrades()
    of_map = sorted(_map_techs(tree))
    seen, output = set(), []
    for t in list(default_value) + list(of_map):
        if t and t not in seen:
            seen.add(t)
            output.append(t)
    return output


def _apply_model(model, prefix, hook_name, jump, only_one, techs_jass, techs_lua, stub, language):
    t = model
    if language == 'jass':
        t = t.replace('DEVOAC_', prefix)
    t = t.replace('ACHOOKFN', hook_name)
    if language == 'jass':
        t = re.sub(r'(' + re.escape(prefix) + r'SALTO\s*=\s*)\d+', r'\g<1>%d' % int(jump), t, count=1)
        t = re.sub(
            r'(' + re.escape(prefix) + r'SO_UM\s*=\s*)(?:true|false)',
            r'\g<1>%s' % ('true' if only_one else 'false'),
            t,
            count=1,
        )
        line_list = []
        for i, tid in enumerate(techs_jass):
            line_list.append("    set %stech[%d] = '%s'" % (prefix, i, tid))
        line_list.append('    set %sNTECH = %d' % (prefix, len(techs_jass)))
        t = t.replace('    //<TECHS>', '\n'.join(line_list))
    else:
        t = re.sub(r'(local SALTO\s*=\s*)\d+', r'\g<1>%d' % int(jump), t, count=1)
        t = re.sub(r'(local SO_UM\s*=\s*)(?:true|false)', r'\g<1>%s' % ('true' if only_one else 'false'), t, count=1)
        if techs_lua:
            block_body = 'techs = {' + ', '.join("FourCC('%s')" % x for x in techs_lua) + '}'
        else:
            block_body = 'techs = {}'
        t = t.replace('    --[[TECHS]]', '    ' + block_body)
    t = _stub_region(t, stub, language)
    return t


def _stub_region(t, stub, language):
    opens = '//<STUB>' if language == 'jass' else '--<STUB>'
    on_close = '//</STUB>' if language == 'jass' else '--</STUB>'
    rx = re.compile(re.escape(opens) + r'.*?' + re.escape(on_close), re.S)
    if stub:
        return t.replace(opens, '').replace(on_close, '')
    return rx.sub('', t)


def inject(body_text, language, hook_name='DevoAC_Acusa', stub=False, gold_jump=400, single_player_only=False,
           research=True, prefix='DEVOAC_'):
    if language == 'jass':
        model = without_comments(io.open(MODEL_J, encoding='utf-8').read(), 'jass')
        tree = jass_ast.parse(body_text)
        techs = _tech_list(tree, research)
        model = _apply_model(model, prefix, hook_name, gold_jump, single_player_only, techs, [], stub, 'jass')
        name_list = dict((g, '%sW_%s' % (prefix, g)) for g in GUARDED)
        block_body, pluralize = _rename_calls(body_text, name_list)
        globals_block, funcs = _model_pieces(model)
        output = _merge_jass(
            block_body, globals_block, funcs, 'call %sInit()' % prefix, after=None if stub else hook_name
        )
        details = {'ok': True, 'language': 'jass', 'embrulhos': pluralize, 'wrapped': sum(pluralize.values()),
                   'techs': len(techs), 'hook_name': hook_name, 'stub': stub, 'jump': gold_jump,
                   'single_player_only': single_player_only, 'prefix': prefix}
        return output, details
    elif language == 'lua':
        model = without_comments(io.open(MODEL_LUA, encoding='utf-8').read(), 'lua')
        techs = _tech_list_lua(body_text, research)
        model = _apply_model(model, prefix, hook_name, gold_jump, single_player_only, [], techs, stub, 'lua')
        output = model.rstrip('\n') + '\n\n' + body_text
        details = {'ok': True, 'language': 'lua', 'embrulhos': {}, 'wrapped': 0, 'techs': len(techs),
                   'hook_name': hook_name, 'stub': stub, 'jump': gold_jump, 'single_player_only': single_player_only,
                   'monkeypatch': True}
        return output, details
    raise ValueError('language has to be jass or lua, not %r' % language)


def _tech_list_lua(body_text, research):
    if not research:
        return []
    default_value = _default_upgrades()
    of_map = set(
        re.findall(
            r"(?:SetPlayerTechResearched|AddPlayerTechResearched|GetPlayerTechCount)\s*\([^)]*FourCC\(\s*['\"]([A-Za-z0-9]{4})['\"]",
            body_text,
        )
    )
    seen, output = set(), []
    for t in list(default_value) + sorted(of_map):
        if t and t not in seen:
            seen.add(t)
            output.append(t)
    return output
