# Declares decoy functions named like the public cheat packs, so a pack pasted by hand does not compile.
import io
import json
import os
import re
import subprocess


HERE = os.path.dirname(os.path.abspath(__file__))

REF = next((p for p in (os.path.normpath(os.path.join(HERE, '..', 'ref', '3.0')), os.path.join(HERE, 'ref', '3.0'))
            if os.path.isfile(os.path.join(p, 'common.j'))), os.path.normpath(os.path.join(HERE, '..', 'ref', '3.0')))
DATA = os.path.join(HERE, 'decoy_names_data.json')
ENGINE_FILES = ('common.j', 'blizzard.j', 'common.ai')
JASS = 'jass'
LUA = 'lua'
PER_PACK = 4
PARAMETROS = ('i', 'n', 'k', 'v', 'x', 'z')
RX_FUNCTION = re.compile(r'^\s*(?:constant\s+)?function\s+([A-Za-z_]\w*)\s+takes\s+(.+?)\s+returns\s+[A-Za-z_]\w*')
RX_MAIN = re.compile(r'^\s*function\s+main\s+takes\s+nothing\s+returns\s+nothing\s*(?://.*)?$')
RX_END = re.compile(r'^\s*endfunction\b')
NO_LUA = ('a Lua script can define a function again (the last definition wins) and the OzzyCP is all `local`: '
          'a name decoy stops nothing there')
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_ENGINE_IDS = []


def _engine_ids():
    if not _ENGINE_IDS:
        import jass_obfuscate
        missing_items = [f for f in ENGINE_FILES[:2] if not os.path.isfile(os.path.join(REF, f))]
        if missing_items:
            raise RuntimeError(
                'the game scripts are missing: %s' % ', '.join(os.path.join(REF, f) for f in missing_items)
            )
        ha = [os.path.join(REF, f) for f in ENGINE_FILES if os.path.isfile(os.path.join(REF, f))]
        _ENGINE_IDS.append(frozenset(jass_obfuscate.engine_ids(ha)))
    return _ENGINE_IDS[0]


def _ids(body_text):
    import jass_obfuscate
    types, texts = jass_obfuscate.tokenize(body_text)
    return set(x for k, x in zip(types, texts) if k == 'id')


def declare(body_text):
    body_text = body_text.replace(u'\ufeff', '')
    name_list = set(re.findall(r'(?m)^\s*function\s+([A-Za-z_]\w*)\s+takes', body_text))
    for m in re.finditer(r'(?ms)^\s*globals\b(.*?)^\s*endglobals\b', body_text):
        for lx in m.group(1).split('\n'):
            mm = re.match(r'\s*(?:constant\s+)?[A-Za-z_]\w*\s+(?:array\s+)?([A-Za-z_]\w*)\s*(?:=.*)?$', lx.strip())
            if mm:
                name_list.add(mm.group(1))
    return name_list


_DATA = []


def data_bytes():
    if not _DATA:
        with io.open(DATA, encoding='utf-8') as f:
            _DATA.append(json.load(f)['packs'])
    return _DATA[0]


def choose(body_text, per_pack=PER_PACK, packs=None):
    if int(per_pack) < 1:
        raise ValueError('per_pack has to be 1 or more')
    map_own = _ids(body_text)
    engine = _engine_ids()
    occupied = map_own | engine | {'main', 'config'}
    declared = declare(body_text.replace(u'\ufeff', ''))
    decoys, by, name_list = [], {}, {}
    all_items = data_bytes()
    missing = sorted(set(packs or ()) - set(all_items))
    if missing:
        raise ValueError('not a JASS cheat pack of the archive: %s' % ', '.join(missing))
    for pid in sorted(all_items):
        if packs and pid not in packs:
            continue
        of_pack = set(all_items[pid]['declared'])
        existing = sorted(of_pack & declared)
        natural = len(existing) >= int(per_pack)
        esc, skipped = [], {}
        for level, fname, takes in all_items[pid]['candidates']:
            if len(esc) >= int(per_pack):
                break
            if fname in name_list:
                name_list[fname]['packs'].append(pid)
                esc.append(fname)
                continue
            if natural and fname in declared:
                c = {'fname': fname, 'packs': [pid], 'level': level, 'natural': True}
            elif fname in occupied:
                skipped[fname] = 'map' if fname in map_own else 'engine'
                continue
            else:
                c = {'fname': fname, 'packs': [pid], 'level': level, 'takes_pack': takes}
            name_list[fname] = c
            decoys.append(c)
            esc.append(fname)
        by[pid] = {
            'decoys': esc,
            'skipped': skipped,
            'already_in_map': existing,
            'func_list': all_items[pid]['function_count'],
            'natural': natural,
        }
    return decoys, by, occupied


def _refuse(body_text, language, why):
    return body_text, {'ok': True, 'applied': False, 'language': language, 'why': why, 'decoys': [], 'keep_names': [],
                       'per_pack': {}, 'calls': 0, 'bytes': 0, 'line_list': [why]}


def inject(body_text, language, per_pack=PER_PACK, called=True, packs=None, **options):
    lang = (language or '').strip().lower()
    if lang != JASS:
        body_text, details = _refuse(body_text, language, NO_LUA if lang == LUA else
                                     'the script is %s, not plain JASS: no name decoy' % (language or 'unknown'))
        details['ignored'] = sorted(options)
        return body_text, details
    new, details = _inject_jass(body_text, per_pack, called, packs)
    details['ignored'] = sorted(options)
    return new, details


def _inject_jass(body_text, per_pack, called, packs):
    language = JASS
    line_list = body_text.split('\n')
    cr = '\r' if body_text.count('\r\n') * 2 > body_text.count('\n') else ''
    begin = next((i for i, lx in enumerate(line_list) if RX_FUNCTION.match(lx)), None)
    if begin is None:
        return _refuse(body_text, language, 'the script declares no function: no name decoy')
    decoys, by, occupied = choose(body_text, per_pack, packs)
    if not decoys:
        return _refuse(body_text, language, 'no cheat pack name is free in this script: no name decoy')
    name_list = set(c['fname'] for c in decoys)
    added = [c for c in decoys if not c.get('natural')]
    pair = next(
        p for p in PARAMETROS + tuple('p%d' % n for n in range(1, 10000)) if p not in occupied and p not in name_list
    )
    block_entry = []
    for c in added:
        c['signature'] = 'takes %s returns nothing' % ('integer ' + pair if c['takes_pack'] == 'nothing' else 'nothing')
        c['call_expr'] = 'call %s(%s)' % (c['fname'], '0' if c['takes_pack'] == 'nothing' else '')
        block_entry += ['function %s %s%s' % (c['fname'], c['signature'], cr), 'endfunction' + cr]
    line_list[begin:begin] = block_entry
    calls, warning = 0, None
    if called and added:
        m = next((i for i, lx in enumerate(line_list) if RX_MAIN.match(lx)), None)
        end_pos = (
            None if m is None else next((k for k in range(m + 1, len(line_list)) if RX_END.match(line_list[k])), None)
        )
        if end_pos is None:
            warning = 'the script has no main function: the decoys are not called'
        else:
            line_list[end_pos:end_pos] = ['    %s%s' % (c['call_expr'], cr) for c in added]
            calls = len(added)
    new = '\n'.join(line_list)
    keep_names = [c['fname'] for c in decoys]
    output = ['%d name decoy(s) from %d cheat pack(s) (%d declared here, %s; %d the map\'s own)' % (
        len(decoys), len([p for p in by.values() if p['decoys']]), len(added),
        'called from main' if calls else 'not called', len(decoys) - len(added))]
    own = set(c['fname'] for c in decoys if c.get('natural'))
    for pid in sorted(by):
        p = by[pid]
        extra = ''
        if p.get('natural'):
            extra = (' (the map already carries it: %d of its names; the map\'s own names stay readable, so a second '
                     'paste still collides after the obfuscation)' % len(p['already_in_map']))
        elif p['already_in_map']:
            extra = ' (the map already declares %d of its names)' % len(p['already_in_map'])
        output.append('  %s: %s%s' % (pid, ', '.join(n + ('*' if n in own else '') for n in p['decoys'])
                                      or 'none free', extra))
    if warning:
        output.append(warning)
    output.append('the obfuscator keeps them: --keep_names=' + ','.join(keep_names))
    for c in decoys:
        c.pop('takes_pack', None)
    return new, {
        'ok': True,
        'applied': True,
        'language': JASS,
        'decoys': decoys,
        'keep_names': keep_names,
        'per_pack': by,
        'calls': calls,
        'parameter': pair,
        'bytes': len(new.encode('utf-8', 'surrogateescape')) - len(body_text.encode('utf-8', 'surrogateescape')),
        'line_list': output,
    }

