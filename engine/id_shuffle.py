# Gives the custom object ids of a map new meaningless ones, in every file that cites them.
import collections
import hashlib
import os
import random
import re
import shutil
import string
import struct

import mpqread
import object_ids
import sstrhash
from object_ids import (TYPES, RX_SCRIPT, load_data, rewrite_objects, rewrite_script, rawcode_value,
                        unescape, id_value, object_name, script_rawcodes, M32, id_text, id_from_text)

HERE = os.path.dirname(os.path.abspath(__file__))

ARCHIVE_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
GAME_FOLDERS = (os.path.join(ARCHIVE_ROOT, 'common', 'cache', 'game_data', 'files'),
                os.path.join(ARCHIVE_ROOT, 'terceiros', 'w3x2lni-2.7.3', 'data', 'enUS-1.27.1', 'mpq'))
ALPHABET = (string.digits + string.ascii_uppercase + string.ascii_lowercase).encode('ascii')
SKIN = 'war3mapSkin.'
SCRIPTS = (('war3map.j', 'jass'), ('scripts\\war3map.j', 'jass'), ('war3map.lua', 'lua'))
RX_TEXT = re.compile(r'\.(txt|slk|fdf|ai|toc|j|lua|json|wai|w3mod)$', re.I)
RX_NO_CASE = re.compile(r'\.(txt|slk)$', re.I)
RX_TOKEN = re.compile(rb'(?<![0-9A-Za-z])[0-9A-Za-z]{4}(?![0-9A-Za-z])')
ID_IN_NAME = rb'(?:[0-9A-Za-z][0-9A-F]{6}(?=_\d)|[0-9A-Za-z]{4})'
RX_GG = re.compile(rb'\bgg_(?:unit|item|dest)_(?P<id>' + ID_IN_NAME + rb')_\d+\b')
RX_GG_JASS = re.compile(rb'(?P<str>"(?:[^"\\]|\\.)*")|(?P<comment>//[^\r\n]*)|(?P<raw>\'(?:[^\'\\]|\\.)*\')'
                        rb'|(?P<gg>\bgg_(?:unit|item|dest)_(?P<id>' + ID_IN_NAME + rb')_\d+\b)', re.S)
RX_LUA = re.compile(rb'(?P<comment>--\[(?P<eq>=*)\[.*?\](?P=eq)\]|--[^\r\n]*)'
                    rb'|(?P<fourcc>FourCC\s*\(\s*(?P<q>["\'])(?P<id>[^"\'\\\r\n]{4})(?P=q)\s*\))'
                    rb'|(?P<str>"(?:[^"\\\r\n]|\\.)*"|\'(?:[^\'\\\r\n]|\\.)*\'|\[(?P<eq2>=*)\[.*?\](?P=eq2)\])'
                    rb'|(?P<gg>\bgg_(?:unit|item|dest)_(?P<gid>' + ID_IN_NAME + rb')_\d+\b)', re.S)
NO_IDS = re.compile(r'(\.(w3e|wpm|shd|mmp|w3r|w3c|w3s|imp|blp|tga|dds|png|jpg|mdx|mdl|mp3|wav|flac|ogg|ttf|otf)'
                    r'|^\(listfile\)|^\(attributes\)|^\(signature\))$', re.I)


class NotClosed(ValueError):
    pass


def game_folders():
    is_pack = os.path.join(os.environ.get('WC3_GAME') or '', 'files')
    if os.environ.get('WC3_GAME') and os.path.isdir(is_pack):
        return (is_pack,)
    return GAME_FOLDERS


def game_ids(folders=None):
    folders = game_folders() if folders is None else folders
    out = set()
    for folder in folders:
        for root, _d, files_ in os.walk(folder):
            for n in files_:
                if not n.lower().endswith(('.slk', '.txt')):
                    continue
                try:
                    with open(os.path.join(root, n), 'rb') as f:
                        b = f.read()
                except OSError:
                    continue
                out.update(m.group(1).lower() for m in re.finditer(rb'K"([^"\r\n]{4})"', b))
                out.update(m.group(1).lower() for m in re.finditer(rb'(?m)^\[([^\]\r\n]{4})\]', b))
    if not out:
        listing = os.path.join(HERE, 'game_ids.txt')
        if os.path.isfile(listing):
            with open(listing, encoding='utf-8') as f:
                out.update(x.strip().lower().encode('latin-1') for x in f if x.strip())
    return out


ID_IN_TEXT = rb'[0-9A-Za-z](?:[0-9A-Za-z]{3}|[\x01-\x08\x0e-\x1f]{3})'
RX_TIP = re.compile(rb'<(?P<id>' + ID_IN_TEXT + rb')(?=[,:])')
RX_WTS_COMMENT = re.compile(rb'(?m)^(?P<begin>//[^\r\n]*?: )(?P<id>' + ID_IN_TEXT + rb')(?= \()')


def swap_tooltip(d, ids, tally=None, comment_text=False):
    def tip(m):
        if m.group('id') in ids:
            if tally is not None:
                tally['tooltip <id,field>'] += 1
            return b'<' + ids[m.group('id')]
        return m.group(0)
    d = RX_TIP.sub(tip, d)
    if comment_text:
        def comment(m):
            if m.group('id') in ids:
                if tally is not None:
                    tally['wts comment'] += 1
                return m.group('begin') + ids[m.group('id')]
            return m.group(0)
        d = RX_WTS_COMMENT.sub(comment, d)
    return d


def swap_tooltip_script(t, ids, lang, tally=None):
    rx = RX_LUA if lang == 'lua' else RX_SCRIPT

    def f(m):
        s = m.group('str')
        return swap_tooltip(s, ids, tally) if s else m.group(0)
    return rx.sub(f, t)


def name_of_id(idb):
    if re.fullmatch(rb'[0-9A-Za-z]{4}', idb):
        return idb
    return idb[:1] + idb[1:].hex().upper().encode('ascii')


def id_from_name(t):
    return t if len(t) == 4 else t[:1] + bytes.fromhex(t[1:].decode('ascii'))


def _swap_gg(m, ids, tally, cluster='id'):
    old = id_from_name(m.group(cluster))
    if old not in ids:
        return m.group(0)
    tally['gg_ name of the placed object'] += 1
    begin = m.start(cluster) - m.start(0)
    t = m.group(0)
    return t[:begin] + name_of_id(ids[old]) + t[m.end(cluster) - m.start(0):]


def rewrite_jass(j, ids):
    j2, tally = rewrite_script(j, dict((k, (v,)) for k, v in ids.items()))
    j2 = swap_tooltip_script(j2, ids, 'jass', tally)

    def swap(m):
        if m.group('gg'):
            return _swap_gg(m, ids, tally)
        return m.group(0)
    return RX_GG_JASS.sub(swap, j2), tally


def rewrite_lua(t, ids):
    tally = collections.Counter()

    def swap(m):
        if m.group('fourcc') and m.group('id') in ids:
            tally['FourCC'] += 1
            begin = m.start('id') - m.start(0)
            x = m.group(0)
            return x[:begin] + ids[m.group('id')] + x[begin + 4:]
        if m.group('gg'):
            return _swap_gg(m, ids, tally, 'gid')
        return m.group(0)
    return swap_tooltip_script(RX_LUA.sub(swap, t), ids, 'lua', tally), tally


def rewrite_code(t, ids, lang):
    return rewrite_lua(t, ids) if lang == 'lua' else rewrite_jass(t, ids)


def texts_with_id(t, lang):
    out = collections.Counter()
    rx = RX_LUA if lang == 'lua' else RX_SCRIPT
    for m in rx.finditer(t):
        s = m.group('str')
        if not s:
            continue
        s = s[1:-1] if s[:1] in b'"\'' else re.sub(rb'^\[=*\[|\]=*\]$', b'', s)
        if len(s) == 4:
            out[s] += 1
    return out


def leftovers_in_code(t, old_streams, lang):
    vals = set(id_value(k) for k in old_streams)
    n = 0
    if lang == 'lua':
        for m in RX_LUA.finditer(t):
            n += bool(m.group('fourcc') and m.group('id') in old_streams) + bool(m.group('gg') and
                                                                           id_from_name(m.group('gid')) in old_streams)
        return n
    for m in RX_SCRIPT.finditer(t):
        if m.group('sum_expr'):
            n += (rawcode_value(unescape(m.group('a'))) + rawcode_value(unescape(m.group('b')))) & M32 in vals
        elif m.group('raw'):
            n += rawcode_value(unescape(m.group('r'))) in vals
        elif m.group('num'):
            v = object_ids.number_value(m.group('num'))
            n += v <= M32 and v in vals
    n += sum(1 for m in RX_GG_JASS.finditer(t) if m.group('gg') and id_from_name(m.group('id')) in old_streams)
    return n


def _patch(d, position_list, ids, tally):
    b = bytearray(d)
    for role, p in position_list:
        v = bytes(b[p:p + 4])
        if v in ids:
            b[p:p + 4] = ids[v]
            tally[role] += 1
    return bytes(b)


def doo_positions(d):
    import doodads
    import map_formats
    try:
        dd = doodads.read_data(d)
    except (doodads.FormatError, struct.error) as e:
        raise NotClosed(str(e))
    if not dd.get('on_close') or map_formats.roundtrip_with(map_formats.read_doo, d) != 'same':
        raise NotClosed('the war3map.doo does not close')
    out = []
    for r in dd['regs']:
        out.append(('placed doodad', r['id_positions'][0]))
        out.extend(
            ('skin' if dd['skin'] and i == 1 else 'dropped item', p) for i, p in enumerate(r['id_positions'][1:], 1)
        )
    tail = dd['tail']
    if tail:
        base = len(d) - len(tail)
        n = struct.unpack_from('<i', tail, 4)[0]
        out.extend(('special doodad', base + 8 + 16 * i) for i in range(n))
    return out


def units_positions(d):
    import inflated_counts
    import map_formats
    try:
        u = inflated_counts.load_units_doo(d)
    except Exception as e:
        raise NotClosed(str(e))
    if (
        not u.get('on_close')
        or u['declared'] != len(u['regs'])
        or map_formats.roundtrip_with(map_formats.read_units_doo, d) != 'same'
    ):
        raise NotClosed('the war3mapUnits.doo does not close')
    return [(role, p) for r in u['regs'] for p, role in r['id_positions']]


def rewrite_positions(d, ids, position_list):
    tally = collections.Counter()
    return _patch(d, position_list(d), ids, tally), tally


def rewrite_w3i(d, ids):
    import w3i
    try:
        m = w3i.parse(d)
    except Exception as e:
        raise NotClosed(str(e))
    if w3i.write(m) != d:
        raise NotClosed('the war3map.w3i does not come back equal')
    tally = collections.Counter()

    def t(x, role):
        if x in ids:
            tally[role] += 1
            return ids[x]
        return x
    for u in m['upgrades']:
        u['id'] = t(u['id'], 'upgrade')
    for x in m['techs']:
        x['id'] = t(x['id'], 'technique')
    for g in m['random_unit_groups']:
        g['lines'] = [(c, [t(i, 'random group') for i in ids_]) for c, ids_ in g['lines']]
    for tab in m.get('random_item_tables', []):
        tab['sets'] = [[(c, t(i, 'item table')) for c, i in s] for s in tab['sets']]
    return w3i.write(m), tally, len(m.get('_tail') or b'')


FIXED_TRIGGERDATA = os.path.join(HERE, 'game_triggerdata.txt')


def _td():
    import triggerdata
    import wtg
    if not hasattr(_td, 'v'):
        _td.v = triggerdata.from_file(FIXED_TRIGGERDATA if os.path.isfile(FIXED_TRIGGERDATA) else wtg.TRIGGERDATA_TXT)
    return _td.v


def load_wtg(d):
    import wtg
    try:
        mt = wtg.read_wtg(d, _td())
        if wtg.write_wtg(mt, _td(), new_format=mt.sub_version is not None) != d:
            raise NotClosed('the war3map.wtg does not come back equal')
    except NotClosed:
        raise
    except Exception as e:
        raise NotClosed('%s: %s' % (type(e).__name__, e))
    return mt


def _param_list(mt):
    stack = [(f, None) for t in mt.triggers for f in t.functions]
    while stack:
        f, _ = stack.pop()
        for c in f.children:
            stack.append((c, None))
        ps = list(f.params)
        while ps:
            p = ps.pop()
            yield p, f.name
            if p.function is not None:
                stack.append((p.function, None))
            if p.index is not None:
                ps.append(p.index)


def rewrite_wtg(d, ids, lang='jass'):
    import wtg
    mt = load_wtg(d)
    tally = collections.Counter()
    ids_str = dict((k.decode('latin-1'), v.decode('latin-1')) for k, v in ids.items())
    for p, fn in _param_list(mt):
        if p.kind == wtg.LITERAL and fn == 'CustomScriptCode':
            new, c = rewrite_code(p.value.encode('utf-8', 'surrogateescape'), ids, lang)
            if c:
                p.value = new.decode('utf-8', 'surrogateescape')
                tally.update(dict(('code: ' + k, v) for k, v in c.items()))
        elif p.kind in (wtg.LITERAL, wtg.PRESET) and p.value in ids_str:
            p.value = ids_str[p.value]
            tally['id literal'] += 1
        elif p.kind == wtg.VARIABLE and p.value.startswith('gg_'):
            new = RX_GG.sub(lambda m: _swap_gg(m, ids, tally), p.value.encode('latin-1', 'replace'))
            p.value = new.decode('latin-1')
    for v in mt.variables:
        if v.initial_value in ids_str:
            v.initial_value = ids_str[v.initial_value]
            tally['initial value of variable'] += 1
    return wtg.write_wtg(mt, _td(), new_format=mt.sub_version is not None), tally


def wtg_by_default(d, ids):
    tally = collections.Counter()
    out = bytearray(d)
    outside = {}
    for old, new in ids.items():
        matches = set()
        for rx, role in (
            (re.compile(re.escape(b'\x03\x00\x00\x00' + old + b'\x00')), 'id literal'),
            (re.compile(rb"'" + re.escape(old) + rb"'"), 'code: direct rawcode'),
            (re.compile(rb'gg_(?:unit|item|dest)_' + re.escape(old) + rb'_\d'), 'gg_ name of the placed object'),
        ):
            for m in rx.finditer(d):
                p = m.start() + (4 if role == 'id literal' else 1 if role.startswith('code') else
                                 m.group(0).index(old))
                if p not in matches:
                    matches.add(p)
                    tally[role] += 1
        all_entries = set(m.start() for m in re.finditer(re.escape(old), d))
        if all_entries - matches:
            outside[old] = len(all_entries - matches)
            continue
        for p in matches:
            out[p:p + 4] = new
    return bytes(out), tally, outside


def rewrite_wct(d, ids, lang='jass'):
    import wtg
    try:
        ct = wtg.read_wct(d)
    except Exception as e:
        raise NotClosed(str(e))
    if wtg.write_wct(ct) != d:
        raise NotClosed('the war3map.wct does not come back equal')
    tally = collections.Counter()

    def t(x):
        if x is None:
            return None
        new, c = rewrite_code(x.encode('utf-8', 'surrogateescape'), ids, lang)
        tally.update(c)
        return new.decode('utf-8', 'surrogateescape')
    ct.header = t(ct.header)
    ct.texts = [t(x) for x in ct.texts]
    return wtg.write_wct(ct), tally


STRUCTURED = {
    'war3map.doo': lambda d, ids, _l: rewrite_positions(d, ids, doo_positions),
    'war3mapunits.doo': lambda d, ids, _l: rewrite_positions(d, ids, units_positions),
    'war3map.w3i': lambda d, ids, _l: rewrite_w3i(d, ids),
    'war3map.wtg': rewrite_wtg,
    'war3map.wct': rewrite_wct,
}


def _names(a):
    import map_formats
    try:
        lst = a.read('(listfile)') or b''
    except Exception:
        lst = b''
    name_list = [n for n in lst.decode('utf-8', 'surrogateescape').replace('\r\n', '\n').split('\n') if n.strip()]
    seen = set(n.lower() for n in name_list)
    for n in map_formats.standard_names():
        if n.lower() not in seen and a.find(n):
            name_list.append(n)
            seen.add(n.lower())
    return name_list


def _read(a, fname):
    try:
        return a.read(fname)
    except Exception:
        return None


def read_map(a):
    m = {'files_': load_data(a), 'skin_id': load_data(a, SKIN), 'scripts': [], 'others': {}, 'name_list': _names(a)}
    for fname, lang in SCRIPTS:
        if a.find(fname):
            j = _read(a, fname)
            if j:
                m['scripts'].append((fname, j, lang))
    if not m['scripts']:
        raise SystemExit('the map does not have war3map.j, scripts\\war3map.j nor war3map.lua')
    m['lang'] = m['scripts'][0][2] if len(set(s[2] for s in m['scripts'])) == 1 else 'jass'
    existing = set('war3map.' + e for e, _n, _t in TYPES) | set(SKIN.lower() + e for e, _n, _t in TYPES)
    existing |= set(n.lower() for n, _l in SCRIPTS)
    for n in m['name_list']:
        if n.lower() in existing or NO_IDS.search(n):
            continue
        d = _read(a, n)
        if d:
            m['others'][n] = d
    return m


def defined(files_):
    out = {}
    for ext, (_v, objs, _n, _d, _p) in files_.items():
        for tab, orig, new, mods in objs:
            nb = new.encode('latin-1')
            if tab == 1 and nb not in out:
                out[nb] = (ext, orig, object_name(mods))
    return out


def map_ids(m):
    in_use = set()
    for files_ in (m['files_'], m['skin_id']):
        for _e, (_v, objs, _n, d, _p) in files_.items():
            for o in objs:
                in_use.add(o[1].encode('latin-1').lower())
                in_use.add(o[2].encode('latin-1').lower())
            in_use.update(mm.group('id').lower() for mm in RX_TIP.finditer(d))
    for _n, j, lang in m['scripts']:
        if lang == 'jass':
            in_use.update(x.lower() for x in script_rawcodes(j))
        else:
            in_use.update(mm.group('id').lower() for mm in RX_LUA.finditer(j) if mm.group('fourcc'))
        in_use.update(mm.group('id').lower() for mm in RX_TIP.finditer(j))
    for fname, d in m['others'].items():
        if fname.lower() == 'war3map.wts':
            in_use.update(mm.group('id').lower() for mm in RX_TIP.finditer(d))
            in_use.update(mm.group('id').lower() for mm in RX_WTS_COMMENT.finditer(d))
    return in_use


def _arith_op_before(s):
    if s.endswith((b'+', b'-', b'*', b'/')):
        return True
    if s.endswith((b'<=', b'>=')):
        return True
    return s.endswith((b'<', b'>')) and not s.endswith((b'==', b'!=', b'<=', b'>='))


def _arith_op_after(s):
    if s.startswith((b'+', b'-', b'*', b'/')):
        return True
    if s.startswith((b'<=', b'>=', b'<', b'>')):
        return True
    return False


def arithmetic_rawcodes(j, lang):
    if lang == 'lua':
        return _lua_rawcodes(j)
    if lang != 'jass':
        return set()
    limpo = RX_CLEAN_JASS.sub(_clean_jass, j)
    out = set()
    for m in RX_SCRIPT.finditer(j):
        if not m.group('raw'):
            continue
        begin = max(limpo.rfind(b'\n', 0, m.start('r')) + 1, m.start('r') - 256)
        end_pos = limpo.find(b'\n', m.end('r'))
        end_pos = min(len(limpo) if end_pos < 0 else end_pos, m.end('r') + 256)
        before, after_diag = _unwrap(limpo[begin:m.start('r') - 1].rstrip(), limpo[m.end('r') + 1:end_pos].lstrip())
        if _arith_op_before(before) or _arith_op_after(after_diag):
            out.add(unescape(m.group('r')))
    if b'StringHash' in j:
        limpo = RX_CLEAN_JASS.sub(_clean_jass, _swap_stringhash(j))
    return out | _stored_rawcodes(limpo)


RX_CLEAN_JASS = re.compile(rb'(?P<str>"(?:[^"\\]|\\.)*")|(?P<comment>//[^\r\n]*)|(?P<raw>\'(?:[^\'\\\r\n]|\\.){1,4}\')',
                           re.S)
RX_NAME_OR_RAW = re.compile(rb'(?P<raw>\'(?:[^\'\\\r\n]|\\.){1,4}\')|(?<![\w$])(?P<fname>[A-Za-z_]\w*)')
RX_ARITH_OP = re.compile(rb'[-+*/<>]')
RX_FUNCTION = re.compile(rb'^(?:constant\s+)?function\s+(?P<f>\w+)\s+takes\s+(?P<pair>.*?)\s+returns\b')
RX_GLOBAL = re.compile(rb'^(?:constant\s+)?\w+\s+(?:array\s+)?(?P<n>\w+)\s*(?:=(?P<v>.*))?$')
RX_LOCAL = re.compile(rb'^local\s+\w+\s+(?:array\s+)?(?P<n>\w+)\s*(?:=(?P<v>.*))?$')
RX_SET = re.compile(rb'^set\s+(?P<n>\w+)\s*(?:\[.*?\])?\s*=(?P<v>.*)$')
RX_RETURN = re.compile(rb'^return\b(?P<v>.*)$')
RX_CALLS = re.compile(rb'(?<![\w$])(?P<f>[A-Za-z_]\w*)\s*\(')
RX_VALUE_RAW = re.compile(rb'^[\s(]*\'(?P<r>(?:[^\'\\\r\n]|\\.){4})\'[\s)]*$')
RX_VALUE_NAME = re.compile(rb'^[\s(]*(?P<n>[A-Za-z_]\w*)\s*(?:\[.*\])?[\s)]*$')
RX_VALUE_CALL = re.compile(rb'^[\s(]*(?P<f>[A-Za-z_]\w*)\s*\(')
RX_ONLY_CLOSE = re.compile(rb'[\s)]*')
RX_PIECES = re.compile(rb"'(?:[^'\\]|\\.)*'?|[()\[\],]")
NAME_CHARS = frozenset(string.ascii_letters.encode('ascii') + string.digits.encode('ascii') + b'_')
JASS_RESERVED_WORDS = frozenset((b'return', b'and', b'or', b'not', b'if', b'elseif', b'exitwhen', b'then', b'set',
                                 b'local', b'call', b'constant'))
PASSTHROUGH = frozenset((b'I2S', b'S2I', b'I2R', b'R2I', b'R2S', b'S2R', b'R2SW', b'SubString', b'SubStringBJ'))
SAVE_CHANNEL = {
    b'SaveInteger': (b'ht integer', 3, 0, 1, 2),
    b'SaveReal': (b'ht real', 3, 0, 1, 2),
    b'SaveStr': (b'ht string', 3, 0, 1, 2),
    b'SaveIntegerBJ': (b'ht integer', 0, 3, 2, 1),
    b'SaveRealBJ': (b'ht real', 0, 3, 2, 1),
    b'SaveStringBJ': (b'ht string', 0, 3, 2, 1),
    b'StoreInteger': (b'gc integer', 3, None, None, None),
    b'StoreReal': (b'gc real', 3, None, None, None),
    b'StoreString': (b'gc string', 3, None, None, None),
    b'StoreIntegerBJ': (b'gc integer', 0, None, None, None),
    b'StoreRealBJ': (b'gc real', 0, None, None, None),
    b'StoreStringBJ': (b'gc string', 0, None, None, None),
}
LOAD_CHANNEL = {
    b'LoadInteger': (b'ht integer', 0, 1, 2),
    b'LoadReal': (b'ht real', 0, 1, 2),
    b'LoadStr': (b'ht string', 0, 1, 2),
    b'LoadIntegerBJ': (b'ht integer', 2, 1, 0),
    b'LoadRealBJ': (b'ht real', 2, 1, 0),
    b'LoadStringBJ': (b'ht string', 2, 1, 0),
    b'GetStoredInteger': (b'gc integer', None, None, None),
    b'GetStoredReal': (b'gc real', None, None, None),
    b'GetStoredString': (b'gc string', None, None, None),
    b'GetStoredIntegerBJ': (b'gc integer', None, None, None),
    b'GetStoredRealBJ': (b'gc real', None, None, None),
    b'GetStoredStringBJ': (b'gc string', None, None, None),
}
RX_KEY_LIT = re.compile(rb"(?P<neg>-\s*)?(?:0[xX](?P<hex>[0-9A-Fa-f]+)|\$(?P<hex2>[0-9A-Fa-f]+)|(?P<dec>\d+)"
                        rb"|'(?P<raw>(?:[^'\\\r\n]|\\.){1,4})')")
RX_INIT_HT = re.compile(rb'\s*InitHashtable\s*\(\s*\)\s*')
RX_NULL = re.compile(rb'\s*null\s*')
RX_STRINGHASH = re.compile(rb'(?<![\w$])StringHash(?:BJ)?\s*\((?P<a>[ \t(]*)(?:"(?P<j>[ !#-\[\]-~]*)"'
                           rb'|\'(?P<lx>[ -&(-\[\]-~]*)\')')
RX_INIT_BJ = re.compile(rb'call\s+InitHashtableBJ\s*\(\s*\)')
RX_LAST_HT = re.compile(rb'\s*GetLastCreatedHashtableBJ\s*\(\s*\)\s*')
HT_BJ_FUNCTIONS = (b'InitHashtableBJ', b'GetLastCreatedHashtableBJ')
_SMALL_NUM = rb'(?:0[xX][0-9A-Fa-f]{1,6}|\$[0-9A-Fa-f]{1,6}|\d{1,7})'
RX_SMALL_NUM_BEFORE = re.compile(rb'(?<![\w.$])' + _SMALL_NUM + rb'\s*(?:<=|>=|<|>)$')
RX_SMALL_NUM_AFTER = re.compile(rb'^(?:<=|>=|<|>)\s*-?\s*' + _SMALL_NUM + rb'(?![\w.])(?!\s*[-+*/])')


def _sign_only(before, after_diag, op_before, op_after):
    if op_before:
        m = RX_SMALL_NUM_BEFORE.search(before)
        if not m or before[:m.start()].rstrip().endswith((b'+', b'-', b'*', b'/', b')', b']')):
            return False
    return not op_after or bool(RX_SMALL_NUM_AFTER.match(after_diag))


def _clean_jass(m):
    s = m.group(0)
    if m.group('raw'):
        return s
    return re.sub(rb'[^\r\n]', b' ', s) if b'\n' in s else b' ' * len(s)


def _paren_map(s):
    out, stack = {}, []
    for m in RX_PIECES.finditer(s):
        c = s[m.start()]
        if c == 0x27:
            continue
        if c in (0x28, 0x5B):
            stack.append([m.start(), m.end(), []])
        elif c in (0x29, 0x5D):
            if stack:
                opens, begin, pieces = stack.pop()
                pieces.append(s[begin:m.start()])
                out[opens] = (m.end(), pieces)
        elif stack:
            stack[-1][2].append(s[stack[-1][1]:m.start()])
            stack[-1][1] = m.end()
    for opens, begin, pieces in stack:
        pieces.append(s[begin:])
        out[opens] = (len(s), pieces)
    return out


def _after_name(s, i, map_path):
    k = i
    while s[k:k + 1] in (b' ', b'\t'):
        k += 1
    pair = map_path.get(k) if s[k:k + 1] in (b'[', b'(') else None
    return (pair[0], pair[1] if s[k:k + 1] == b'(' else None) if pair else (i, None)


def _unwrap(before, after_diag):
    while before.endswith(b'(') and after_diag.startswith(b')'):
        pre = before[:-1].rstrip()
        k = len(pre)
        while k and pre[k - 1] in NAME_CHARS:
            k -= 1
        if k < len(pre) and pre[k:] not in JASS_RESERVED_WORDS:
            break
        before, after_diag = pre, after_diag[1:].lstrip()
    return before, after_diag


def _jass_source(v, hash_key, summaries=None):
    mr = RX_VALUE_RAW.match(v)
    if mr:
        return ('id', unescape(mr.group('r')))
    mc = RX_VALUE_CALL.match(v)
    if mc:
        pair = _paren_map(v).get(mc.end() - 1)
        if pair and mc.group('f') not in JASS_RESERVED_WORDS and RX_ONLY_CLOSE.fullmatch(v, pair[0]):
            return _call_source(mc.group('f'), pair[1], hash_key, summaries)
        return None
    mn = RX_VALUE_NAME.match(v)
    return hash_key(mn.group('n')) if mn else None


def _call_source(f, args, hash_key, summaries=None):
    if f in PASSTHROUGH:
        return _jass_source(args[0], hash_key, summaries) if args else None
    if f in LOAD_CHANNEL:
        return ('read_data',) + _slot_jass(LOAD_CHANNEL[f], args, hash_key)
    r = summaries.get(f) if summaries else None
    if r is not None and r[0] == 'read_data':
        return ('read_data',) + _slot_parts(LOAD_CHANNEL[r[1]], _instance(r[2], args, hash_key))
    if r is not None and r[0] == 'id':
        return _jass_source(args[r[1]], hash_key, summaries) if r[1] < len(args) else None
    return ('ret', f)


def _arg(args, pos):
    if pos is None or pos >= len(args):
        return None
    v = args[pos].strip()
    while v[:1] == b'(' and v[-1:] == b')':
        v = v[1:-1].strip()
    return v


def _lit_key(v):
    m = RX_KEY_LIT.fullmatch(v) if v is not None else None
    if not m:
        return '*'
    if m.group('raw') is not None:
        n = rawcode_value(unescape(m.group('raw')))
    elif m.group('hex') or m.group('hex2'):
        n = int(m.group('hex') or m.group('hex2'), 16)
    elif len(m.group('dec')) > 1 and m.group('dec')[:1] == b'0':
        if not re.fullmatch(rb'[0-7]+', m.group('dec')):
            return '*'
        n = int(m.group('dec'), 8)
    else:
        n = int(m.group('dec'))
    return (-n if m.group('neg') else n) & 0xFFFFFFFF


def _swap_stringhash(t, lua=False):
    out, i = [], 0
    for m in RX_STRINGHASH.finditer(t):
        lit = m.group('j') if m.group('j') is not None else (m.group('lx') if lua else None)
        if lit is None:
            continue
        k, missing = m.end(), m.group('a').count(b'(') + 1
        while missing and t[k:k + 1] in (b' ', b'\t', b')'):
            missing -= t[k:k + 1] == b')'
            k += 1
        if missing:
            continue
        out += [t[i:m.start()], b'0x%08X' % (sstrhash.sstrhash2_bytes(lit) & M32)]
        i = k
    return b''.join(out + [t[i:]])


def _slot_jass(spec, args, hash_key):
    return _slot_parts(spec, [(a, hash_key) for a in args])


def _slot_parts(spec, pieces):
    chan, pt, pp, pf = spec

    def arg(pos):
        if pos is None or pos >= len(pieces) or pieces[pos][0] is None:
            return None, None
        return _arg(pieces[pos][:1], 0), pieces[pos][1]
    t, hash_key = arg(pt)
    t = hash_key(t) if t is not None and RX_NAME_ONLY.fullmatch(t) else '*'
    return (chan, t, _lit_key(arg(pp)[0]), _lit_key(arg(pf)[0]))


def _global_key(n):
    return (None, n)


def _instance(pieces, args, hash_key):
    out = []
    for p in pieces:
        if p[0] == 'p':
            out.append((args[p[1]] if p[1] < len(args) else None, hash_key))
        elif p[0] == 't':
            out.append((p[1], _global_key))
        else:
            out.append((None, hash_key))
    return out


def _whole_call(v):
    v = _arg([v], 0)
    mc = RX_VALUE_CALL.match(v)
    if not mc or mc.group('f') in JASS_RESERVED_WORDS:
        return None
    pair = _paren_map(v).get(mc.end() - 1)
    if not pair or not RX_ONLY_CLOSE.fullmatch(v, pair[0]):
        return None
    return mc.group('f'), pair[1]


RX_CALL = re.compile(rb'call\s+(?P<c>.*)$')
SUMMARY_DEPTH = 32


def _jass_summaries(func_list, bodies):
    out, resolving = {}, []

    def summary(f):
        if f in out:
            return out[f]
        if f in resolving or len(resolving) >= SUMMARY_DEPTH or f not in bodies or len(bodies[f]) != 1:
            return None
        resolving.append(f)
        r = _summarize(bodies[f][0], func_list[f][1], summary)
        resolving.pop()
        out[f] = r
        return r
    for f in bodies:
        summary(f)
    return {f: r for f, r in out.items() if r is not None}


def _summarize(s, params, summary):
    if not params:
        return None
    pset = set(params)

    def has_param(a):
        return any(m.group('fname') in pset for m in RX_NAME_OR_RAW.finditer(a))

    def loose(a, conversion=False):
        v = _arg([a], 0)
        while conversion:
            ch = _whole_call(v)
            if not ch or ch[0] not in PASSTHROUGH or not ch[1] or any(has_param(x) for x in ch[1][1:]):
                break
            v = _arg(ch[1][:1], 0)
        return params.index(v) if v in pset else None

    def pieces(args, field_value=None):
        out = []
        for k, a in enumerate(args):
            i = loose(a, conversion=k == field_value)
            if i is not None:
                out.append(('p', i))
            elif has_param(a):
                return None
            else:
                out.append(('t', a))
        return out

    def compose(sub, mine):
        return tuple((mine[p[1]] if p[1] < len(mine) else ('x',)) if p[0] == 'p' else p for p in sub)
    mr = RX_RETURN.match(s)
    if mr:
        e = mr.group('v')
        while True:
            i = loose(e, conversion=True)
            if i is not None:
                return ('id', i)
            ch = _whole_call(e) if e.strip() else None
            if ch is None:
                return None
            g, args = ch
            r = summary(g)
            if g in LOAD_CHANNEL or (r and r[0] == 'read_data'):
                ps = pieces(args)
                if ps is None:
                    return None
                return ('read_data', g, tuple(ps)) if g in LOAD_CHANNEL else ('read_data', r[1], compose(r[2], ps))
            if not r or r[0] != 'id' or r[1] >= len(args):
                return None
            if any(has_param(a) and loose(a) is None for k, a in enumerate(args) if k != r[1]):
                return None
            e = args[r[1]]
    mc = RX_CALL.match(s)
    ch = _whole_call(mc.group('c')) if mc else None
    if ch is None:
        return None
    g, args = ch
    r = summary(g)
    if g in SAVE_CHANNEL:
        ps = pieces(args, field_value=SAVE_CHANNEL[g][1])
        return ('saved', g, tuple(ps)) if ps is not None and SAVE_CHANNEL[g][1] < len(ps) else None
    if r and r[0] == 'saved':
        ps = pieces(args)
        return ('saved', r[1], compose(r[2], ps)) if ps is not None else None
    return None


RX_NAME_ONLY = re.compile(rb'[A-Za-z_]\w*')


def _link_channels(value_list, copies, in_arith, sign_only, tables_of):
    def ef(t):
        return ('*',) if t == '*' else (tables_of(t) or ('*',))
    guards = set(k for k in value_list if k[0] == 'saved') | set(p for _d, p in copies if p[0] == 'saved')
    read_set = set(d for d, _p in copies if d[0] == 'read_data') | set(
        k for k in in_arith | sign_only if k[0] == 'read_data'
    )
    added, tables, exists = [], collections.defaultdict(set), set()
    for g in guards:
        _x, chan, t0, p, c = g
        for t in ef(t0):
            tables[chan].add(t)
            for k in (('gx', chan, t, p, c), ('ap', chan, t, p), ('action_match', chan, t, c), ('at', chan, t)):
                added.append((g, k))
                exists.add(k)
    for lx in read_set:
        _x, chan, t0, p, c = lx
        targets = set()
        for t in ef(t0):
            targets |= tables[chan] if t == '*' else {t, '*'}
        for tt in targets:
            if p != '*' and c != '*':
                sources = (('gx', chan, tt, p, c), ('gx', chan, tt, p, '*'), ('gx', chan, tt, '*', c),
                           ('gx', chan, tt, '*', '*'))
            elif c != '*':
                sources = (('action_match', chan, tt, c), ('action_match', chan, tt, '*'))
            elif p != '*':
                sources = (('ap', chan, tt, p), ('ap', chan, tt, '*'))
            else:
                sources = (('at', chan, tt),)
            added.extend((k, lx) for k in sources if k in exists)
    copies.extend(added)


def _param_tables(alias_names, reassigned, not_table):
    res = {p: set() for p in alias_names if p not in reassigned}
    changed = True
    while changed:
        changed = False
        for p, r in res.items():
            if '*' in r:
                continue
            new = set()
            for a in alias_names[p]:
                if a == '*' or (a in not_table and a not in res):
                    new = {'*'}
                    break
                new |= res[a] if a in not_table else {a}
            if not new <= r:
                res[p] = {'*'} if '*' in new else r | new
                changed = True
    return res


def _jass_param_list(pair):
    return [p.split()[-1] for p in pair.split(b',') if p.split() and p.strip() != b'nothing']


def _ids_in_arith(value_list, copies, in_arith, sign_only):
    come_out = collections.defaultdict(list)
    for from_, new_value in copies:
        come_out[from_].append(new_value)
    work_queue = [k for k, v in value_list.items() if v]
    while work_queue:
        from_ = work_queue.pop()
        for new_value in come_out.get(from_, ()):
            new_ones = value_list[from_] - value_list[new_value]
            if new_ones:
                value_list[new_value] |= new_ones
                work_queue.append(new_value)

    def ids(k):
        return {k[1]} if k[0] == 'id' else value_list.get(k, set())
    out = set()
    for k in in_arith:
        out |= ids(k)
    for k in sign_only - in_arith:
        out |= set(x for x in ids(k) if not 0x02 <= x[0] <= 0x7F)
    return out


def _stored_rawcodes(limpo):
    value_list = collections.defaultdict(set)
    copies = []
    in_arith = set()
    sign_only = set()
    not_table = set()
    line_list = [x.strip() for x in limpo.split(b'\n')]
    func_list, n_func = {}, 0
    bodies, current, repeated = {}, None, set()
    for s in line_list:
        mf = RX_FUNCTION.match(s)
        if mf:
            n_func += 1
            current = mf.group('f')
            if current in func_list:
                repeated.add(current)
            func_list[current] = (n_func, _jass_param_list(mf.group('pair')))
            bodies[current] = []
        elif s == b'endfunction':
            current = None
        elif current is not None and s and len(bodies[current]) < 2:
            bodies[current].append(s)
    for f in repeated:
        bodies.pop(f)
    summaries = _jass_summaries(func_list, bodies)
    scope_name, func_name, local_vars, in_globals, n_func, params = None, None, set(), False, 0, set()
    bj_rule, after_init = not any(f in func_list for f in HT_BJ_FUNCTIONS), False
    alias_names = collections.defaultdict(set)
    reassigned = set()

    def step_on(source, new_value):
        if source is None:
            return
        if source[0] == 'id':
            value_list[new_value].add(source[1])
        else:
            copies.append((source, new_value))
    for s in line_list:
        if not s:
            continue
        fresh, after_init = after_init, bj_rule and bool(RX_INIT_BJ.fullmatch(s))
        if s == b'globals' or s == b'endglobals':
            in_globals = s == b'globals'
            continue
        mf = RX_FUNCTION.match(s)
        if mf:
            n_func += 1
            scope_name, func_name, local_vars = n_func, mf.group('f'), set(_jass_param_list(mf.group('pair')))
            params = set(local_vars)
            not_table.update((scope_name, p) for p in local_vars)
            continue
        if s == b'endfunction':
            scope_name, func_name, local_vars, params = None, None, set(), set()
            continue
        if scope_name is None and not in_globals:
            continue

        def hash_key(n):
            return (scope_name, n) if n in local_vars else (None, n)
        if in_globals:
            md = RX_GLOBAL.match(s)
        else:
            md = RX_LOCAL.match(s)
            if md:
                if md.group('n') in params:
                    reassigned.add(hash_key(md.group('n')))
                local_vars.add(md.group('n'))
            else:
                md = RX_SET.match(s)
        if md and md.group('v') is not None:
            step_on(_jass_source(md.group('v'), hash_key, summaries), hash_key(md.group('n')))
            if not (RX_INIT_HT.fullmatch(md.group('v')) or RX_NULL.fullmatch(md.group('v'))
                    or (fresh and RX_LAST_HT.fullmatch(md.group('v')))):
                not_table.add(hash_key(md.group('n')))
            if md.group('n') in params and not RX_NULL.fullmatch(md.group('v')):
                reassigned.add(hash_key(md.group('n')))
        elif scope_name is not None:
            mr = RX_RETURN.match(s)
            if mr:
                step_on(_jass_source(mr.group('v'), hash_key, summaries), ('ret', func_name))
        map_path = None
        if b'(' in s:
            for mc in RX_CALLS.finditer(s):
                f = func_list.get(mc.group('f'))
                r = summaries.get(mc.group('f')) if f else None
                if f and r is None:
                    map_path = map_path or _paren_map(s)
                    for pair, arg in zip(f[1], map_path.get(mc.end() - 1, (0, ()))[1]):
                        step_on(_jass_source(arg, hash_key, summaries), (f[0], pair))
                        a = _arg([arg], 0)
                        alias_names[(f[0], pair)].add(hash_key(a) if RX_NAME_ONLY.fullmatch(a) else '*')
                elif r is not None:
                    if r[0] == 'saved':
                        chan, pos, pt, pp, pf = SAVE_CHANNEL[r[1]]
                        map_path = map_path or _paren_map(s)
                        pieces = _instance(r[2], map_path.get(mc.end() - 1, (0, ()))[1], hash_key)
                        if pos < len(pieces) and pieces[pos][0] is not None:
                            step_on(_jass_source(pieces[pos][0], pieces[pos][1], summaries),
                                    ('saved',) + _slot_parts((chan, pt, pp, pf), pieces))
                elif mc.group('f') in SAVE_CHANNEL:
                    chan, pos, pt, pp, pf = SAVE_CHANNEL[mc.group('f')]
                    map_path = map_path or _paren_map(s)
                    args = map_path.get(mc.end() - 1, (0, ()))[1]
                    if pos < len(args):
                        step_on(_jass_source(args[pos], hash_key, summaries),
                                ('saved',) + _slot_jass((chan, pt, pp, pf), args, hash_key))
        if not RX_ARITH_OP.search(s):
            continue
        map_path = map_path or (_paren_map(s) if b'(' in s or b'[' in s else {})
        for mm in RX_NAME_OR_RAW.finditer(s):
            if not mm.group('fname'):
                continue
            end_pos, args = _after_name(s, mm.end(), map_path)
            before, after_diag = _unwrap(s[:mm.start()].rstrip(), s[end_pos:].lstrip())
            op_before, op_after = _arith_op_before(before), _arith_op_after(after_diag)
            if op_before or op_after:
                k = (
                    hash_key(mm.group('fname'))
                    if args is None
                    else _call_source(mm.group('fname'), args, hash_key, summaries)
                )
                if k is not None:
                    (sign_only if _sign_only(before, after_diag, op_before, op_after) else in_arith).add(k)
    from_param = _param_tables(alias_names, reassigned, not_table)

    def tables_of(t):
        if t not in not_table:
            return (t,)
        r = from_param.get(t)
        return tuple(r) if r and '*' not in r else ('*',)
    _link_channels(value_list, copies, in_arith, sign_only, tables_of)
    return _ids_in_arith(value_list, copies, in_arith, sign_only)


RX_LUA_TOKEN = re.compile(
    rb'\s*(?:(?P<x>@\d+@|\$'
    rb'|0[xX][0-9A-Fa-f]*(?:\.[0-9A-Fa-f]*)?(?:[pP][-+]?\d+)?|(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?'
    rb'|[A-Za-z_]\w*|\.\.\.|\.\.|==|~=|<=|>=|<<|>>|//|::|[-+*/%^#&~|<>=(){}\[\];:,.])|(?P<o>\S))'
)
RX_SMALL_NUM_LUA = re.compile(rb'0[xX][0-9A-Fa-f]{1,6}|\d{1,7}(?:\.\d*)?')
LUA_RESERVED_WORDS = frozenset(
    b'and break do else elseif end false for function goto if in local nil not or repeat return '
    b'then true until while'.split()
)
LUA_BLOCK_END = frozenset((b'end', b'else', b'elseif', b'until'))
LUA_BINARY_OPS = frozenset(b'+ - * / // % ^ .. == ~= < <= > >= and or & | ~ << >>'.split())
LUA_ARITH_OPS = frozenset(b'+ - * / // % ^ & | ~ << >>'.split())
LUA_ORDER_OPS = frozenset(b'< <= > >='.split())
PASSTHROUGH_LUA = PASSTHROUGH | {b'tostring', b'tonumber'}


def _lua_name(x):
    return x is not None and (x[:1].isalpha() or x[:1] == b'_') and x not in LUA_RESERVED_WORDS


class _LuaFlow:
    def __init__(self, toks, ids):
        self.t, self.i, self.ids = toks, 0, ids
        self.value_list = collections.defaultdict(set)
        self.copies, self.in_arith, self.sign_only = [], set(), set()
        self.frames = [[0, set()]]
        self.funcs, self.n_func = [None], 0
        self.defs = collections.defaultdict(list)
        self.calls = []
        self.collect = self.hint = None
        self.ranges = []
        self.not_table = set()
        self.fresh_set = set()
        self.after_init = -1

    def tok(self, k=0):
        p = self.i + k
        return self.t[p] if p < len(self.t) else None

    def skip(self, x):
        if self.tok() == x:
            self.i += 1
            return True
        return False

    def resolve(self, fname):
        for fid, local_vars in reversed(self.frames):
            if fname in local_vars:
                return ('lx', fid, fname)
        return ('g', fname)

    def step_on(self, sources, new_value):
        for f in sources:
            if f[0] == 'id':
                self.value_list[new_value].add(f[1])
            else:
                self.copies.append((f, new_value))

    def opens(self, local_vars=()):
        self.frames.append([self.frames[-1][0], set(local_vars)])

    def block_entry(self):
        while self.tok() is not None and self.tok() not in LUA_BLOCK_END:
            begin = self.i
            self.statement()
            if self.i == begin:
                self.i += 1

    def block_body(self, fname, as_method):
        params = [b'self'] if as_method else []
        if self.skip(b'('):
            while self.tok() is not None and self.tok() != b')' and self.tok() not in LUA_RESERVED_WORDS:
                if _lua_name(self.tok()) or self.tok() == b'...':
                    params.append(self.tok())
                self.i += 1
            self.skip(b')')
        self.n_func += 1
        if fname is not None:
            self.defs[fname].append((self.n_func, params))
        self.not_table.update(('lx', self.n_func, p) for p in params)
        self.frames.append([self.n_func, set(params) - {b'...'}])
        self.funcs.append(fname)
        self.block_entry()
        self.funcs.pop()
        self.frames.pop()
        self.skip(b'end')

    def statement(self):
        x = self.tok()
        fresh = self.after_init == self.i
        if x == b';' or x == b'break':
            if fresh and x == b';':
                self.after_init += 1
            self.i += 1
        elif x == b'if':
            self.i += 1
            self.expr()
            self.skip(b'then')
            self.opens()
            self.block_entry()
            while self.tok() in (b'elseif', b'else'):
                self.frames[-1][1] = set()
                self.i += 1
                if self.t[self.i - 1] == b'elseif':
                    self.expr()
                    self.skip(b'then')
                self.block_entry()
            self.frames.pop()
            self.skip(b'end')
        elif x in (b'while', b'do'):
            self.i += 1
            if x == b'while':
                self.expr()
                self.skip(b'do')
            self.opens()
            self.block_entry()
            self.frames.pop()
            self.skip(b'end')
        elif x == b'for':
            self.i += 1
            name_list = self.name_list()
            sources = set()
            if self.skip(b'='):
                for f, _m in self.listing():
                    self.pluralize(f)
            else:
                self.skip(b'in')
                old_one, self.collect = self.collect, set()
                for f, _m in self.listing():
                    sources |= f
                sources |= self.collect
                self.collect = old_one if old_one is None else old_one | self.collect
            self.skip(b'do')
            self.opens(name_list)
            for n in name_list:
                self.step_on(sources, self.resolve(n))
                self.not_table.add(self.resolve(n))
            self.block_entry()
            self.frames.pop()
            self.skip(b'end')
        elif x == b'repeat':
            self.i += 1
            self.opens()
            self.block_entry()
            if self.skip(b'until'):
                self.expr()
            self.frames.pop()
        elif x == b'function':
            self.i += 1
            fname, as_method = None, False
            while _lua_name(self.tok()):
                fname = self.tok()
                self.i += 1
                if self.tok() in (b'.', b':'):
                    as_method = self.tok() == b':'
                    self.i += 1
                    continue
                break
            self.block_body(fname, as_method)
        elif x == b'local':
            self.i += 1
            if self.skip(b'function'):
                fname = self.tok() if _lua_name(self.tok()) else None
                if fname is not None:
                    self.i += 1
                    self.frames[-1][1].add(fname)
                self.block_body(fname, False)
                return
            name_list = self.name_list(with_attribute=True)
            exprs = self.listing(name_list) if self.skip(b'=') else []
            ranges = self.ranges if exprs else []
            self.frames[-1][1].update(name_list)
            self.assigns([self.resolve(n) for n in name_list], exprs, fresh, ranges)
        elif x == b'return':
            self.i += 1
            if self.tok() is not None and self.tok() not in LUA_BLOCK_END and self.tok() != b';':
                for f, _m in self.listing():
                    self.step_on(f, ('ret', self.funcs[-1]))
        elif x == b'goto':
            self.i += 2
        elif x == b'::':
            self.i += 2
            self.skip(b'::')
        else:
            begin = self.i
            _f, tgt, _m, last = self.suffixed()
            if self.i == begin or self.tok() not in (b'=', b','):
                if self.t[begin:self.i] == [b'InitHashtableBJ', b'(', b')']:
                    self.after_init = self.i
                return
            targets, hints = [tgt], [last]
            while self.skip(b','):
                _f, tgt, _m, last = self.suffixed()
                targets.append(tgt)
                hints.append(last)
            if self.skip(b'='):
                exprs = self.listing(hints)
                self.assigns(targets, exprs, fresh, self.ranges)

    def name_list(self, with_attribute=False):
        out = []
        while _lua_name(self.tok()):
            out.append(self.tok())
            self.i += 1
            if with_attribute and self.tok() == b'<':
                self.i += 2
                self.skip(b'>')
            if not self.skip(b','):
                break
        return out

    def assigns(self, targets, exprs, fresh=False, ranges=()):
        for k, tgt in enumerate(targets):
            if tgt is None:
                continue
            field_value = exprs[k][0] if k < len(exprs) else None
            is_nil = (self.t[ranges[k][0]:ranges[k][1]] == [b'nil'] if k < len(exprs) and k < len(ranges) and ranges[k]
                      else k >= len(exprs) and not (exprs and exprs[-1][1]))
            if fresh and field_value == {('ret', b'GetLastCreatedHashtableBJ')}:
                self.fresh_set.add(tgt)
            elif field_value != {('ret', b'InitHashtable')} and not is_nil:
                self.not_table.add(tgt)
            if k < len(exprs):
                self.step_on(exprs[k][0], tgt)
            elif exprs and exprs[-1][1]:
                self.step_on(exprs[-1][0], tgt)

    def listing(self, hints=()):
        out, ranges = [], []
        while True:
            self.hint = hints[len(out)] if len(out) < len(hints) else None
            begin = self.i
            out.append(self.expr())
            ranges.append((begin, self.i))
            if self.i == begin or not self.skip(b','):
                break
        self.hint = None
        self.ranges = ranges
        return out

    def pluralize(self, sources):
        self.in_arith |= sources

    def expr(self):
        hint, self.hint = self.hint, None
        opnds, ops, multi = [], [], False
        while True:
            unary_ops = []
            while self.tok() in (b'-', b'not', b'#', b'~'):
                unary_ops.append(self.tok())
                self.i += 1
            begin = self.i
            f, small, multi = self.simple(hint if not opnds else None)
            if unary_ops:
                if b'-' in unary_ops or b'~' in unary_ops:
                    self.pluralize(f)
                small = small and set(unary_ops) == {b'-'}
                f, multi = set(), False
            opnds.append((f, small))
            if self.i == begin and not unary_ops:
                break
            if self.tok() in LUA_BINARY_OPS:
                ops.append(self.tok())
                self.i += 1
                continue
            break
        while len(opnds) <= len(ops):
            opnds.append((set(), False))
        output = set()
        for k, (f, _small) in enumerate(opnds):
            neighbors = []
            if k > 0:
                neighbors.append((ops[k - 1], k - 1, ops[k - 2] if k >= 2 else None))
            if k < len(ops):
                neighbors.append((ops[k], k + 1, ops[k + 1] if k + 1 < len(ops) else None))
            name_list = [o for o, _j, _l in neighbors]
            if f and any(o in LUA_ARITH_OPS for o in name_list):
                self.pluralize(f)
            elif f and any(o in LUA_ORDER_OPS for o in name_list):
                if all(opnds[j][1] and lado not in LUA_ARITH_OPS for o, j, lado in neighbors if o in LUA_ORDER_OPS):
                    self.sign_only |= f
                else:
                    self.pluralize(f)
            if all(o in (b'and', b'or', b'..') for o in name_list):
                output |= f
        return output, multi and len(opnds) == 1

    def simple(self, hint):
        x = self.tok()
        if x is None:
            return set(), False, False
        if x[:1] == b'@':
            self.i += 1
            return {('id', self.ids[int(x[1:-1])])}, False, False
        if x in (b'$', b'nil', b'true', b'false'):
            self.i += 1
            return set(), False, False
        if x[:1].isdigit() or (x[:1] == b'.' and x[1:2].isdigit()):
            self.i += 1
            return set(), bool(RX_SMALL_NUM_LUA.fullmatch(x)), False
        if x == b'...':
            self.i += 1
            return {('current_val', self.frames[-1][0])}, False, True
        if x == b'{':
            return self.table(), False, False
        if x == b'function':
            self.i += 1
            self.block_body(hint, False)
            return set(), False, False
        f, _target, multi, _u = self.suffixed()
        return f, False, multi

    def suffixed(self):
        x = self.tok()
        if _lua_name(x):
            self.i += 1
            tgt = self.resolve(x)
            sources, last = {tgt}, x
        elif x == b'(':
            self.i += 1
            sources, _m = self.expr()
            self.skip(b')')
            tgt = last = None
        else:
            return set(), None, False, None
        multi = False
        while True:
            x = self.tok()
            if x == b'.' and _lua_name(self.tok(1)):
                last = self.tok(1)
                tgt = ('.', last)
                sources, multi = {tgt}, False
                self.i += 2
            elif x == b'[':
                self.i += 1
                self.expr()
                self.skip(b']')
                multi = False
            elif x == b':' and _lua_name(self.tok(1)):
                last = self.tok(1)
                self.i += 2
                self.called(last, [(sources, False)] + self.args())
                sources, tgt, multi, last = {('ret', last)}, None, True, None
            elif x in (b'(', b'{', b'$'):
                native_lib = last if tgt == ('g', last) else None
                args = self.args()
                ranges = self.ranges
                self.called(last, args)
                sources, tgt, multi = ({('ret', last)} if last else set()), None, True
                if native_lib in PASSTHROUGH_LUA:
                    sources, multi = sources | (args[0][0] if args else set()), False
                elif native_lib in LOAD_CHANNEL:
                    sources, multi = (
                        sources | {('read_data',) + self.button_slot(LOAD_CHANNEL[native_lib], ranges)},
                        False,
                    )
                elif native_lib in SAVE_CHANNEL and SAVE_CHANNEL[native_lib][1] < len(args):
                    chan, pos, pt, pp, pf = SAVE_CHANNEL[native_lib]
                    self.step_on(args[pos][0], ('saved',) + self.button_slot((chan, pt, pp, pf), ranges))
                last = None
            else:
                return sources, tgt, multi, last

    def args(self):
        x = self.tok()
        if x == b'$':
            self.i += 1
            self.ranges = [None]
            return [(set(), False)]
        if x == b'{':
            out = [(self.table(), False)]
            self.ranges = [None]
            return out
        self.i += 1
        if self.skip(b')'):
            self.ranges = []
            return []
        out = self.listing()
        self.skip(b')')
        return out

    def button_slot(self, spec, ranges):
        chan = spec[0]

        def only_problems(pos):
            f = ranges[pos] if pos is not None and pos < len(ranges) else None
            return self.t[f[0]] if f and f[1] - f[0] == 1 else None
        t = only_problems(spec[1])
        t = self.resolve(t) if _lua_name(t) else '*'
        keys = []
        for pos in spec[2:]:
            x = only_problems(pos)
            if x is not None and x[:1] == b'@':
                keys.append(int.from_bytes(self.ids[int(x[1:-1])], 'big') & 0xFFFFFFFF)
            elif x is not None and re.fullmatch(rb'0[xX][0-9A-Fa-f]+', x):
                keys.append(int(x[2:], 16) & 0xFFFFFFFF)
            elif x is not None and x.isdigit():
                keys.append(int(x) & 0xFFFFFFFF)
            else:
                keys.append('*')
        return (chan, t) + tuple(keys)

    def called(self, fname, args):
        if self.collect is not None:
            for f, _m in args:
                self.collect |= f
        if fname is not None:
            self.calls.append((fname, args))

    def table(self):
        self.i += 1
        sources = set()
        while self.tok() is not None and self.tok() != b'}' and self.tok() not in LUA_BLOCK_END:
            begin = self.i
            if self.skip(b'['):
                self.expr()
                self.skip(b']')
                self.skip(b'=')
                sources |= self.expr()[0]
            elif _lua_name(self.tok()) and self.tok(1) == b'=':
                fname = self.tok()
                self.i += 2
                self.hint = fname
                self.step_on(self.expr()[0], ('.', fname))
            else:
                sources |= self.expr()[0]
            if not (self.skip(b',') or self.skip(b';')) and self.i == begin:
                self.i += 1
        self.skip(b'}')
        return sources

    def resultado(self):
        for fname, args in self.calls:
            for fid, params in self.defs.get(fname, ()):
                for k, p in enumerate(params):
                    if p == b'...':
                        for f, _m in args[k:]:
                            self.step_on(f, ('current_val', fid))
                        break
                    if k < len(args):
                        self.step_on(args[k][0], ('lx', fid, p))
                    elif args and args[-1][1]:
                        self.step_on(args[-1][0], ('lx', fid, p))
        if any(f in self.defs for f in HT_BJ_FUNCTIONS):
            self.not_table |= self.fresh_set
        _link_channels(self.value_list, self.copies, self.in_arith, self.sign_only,
                       lambda t: ('*',) if t in self.not_table else (t,))
        return _ids_in_arith(self.value_list, self.copies, self.in_arith, self.sign_only)


def _lua_rawcodes(t):
    ids = []
    if b'StringHash' in t:
        t = _swap_stringhash(t, lua=True)

    def clean(m):
        if m.group('fourcc'):
            ids.append(m.group('id'))
            return b' @%d@ ' % (len(ids) - 1)
        if m.group('str'):
            return b' $ '
        if m.group('comment'):
            return b' '
        return m.group(0)
    limpo = RX_LUA.sub(clean, t)
    if not ids:
        return set()
    toks = [m.group('x') for m in RX_LUA_TOKEN.finditer(limpo) if m.group('x')]
    script_flow = _LuaFlow(toks, ids)
    try:
        while script_flow.tok() is not None:
            script_flow.block_entry()
            script_flow.i += 1
        return script_flow.resultado()
    except RecursionError:
        return set(ids)


def _dont_rewrite(fname, d, lang):
    hash_key = fname.lower().rsplit('\\', 1)[-1]
    if hash_key in ('(listfile)', '(attributes)', '(signature)', 'war3map.wts'):
        return False
    if hash_key in STRUCTURED:
        try:
            STRUCTURED[hash_key](d, {}, lang)
            return False
        except NotClosed:
            return True
    return False


def where_is(m, candidates):
    avoid = collections.defaultdict(list)
    cand_low = set(candidates)
    for fname, j, lang in m['scripts']:
        for x in texts_with_id(j, lang):
            if x in cand_low:
                avoid[x].append('text in %s' % fname)
        for x in arithmetic_rawcodes(j, lang):
            if x in cand_low:
                avoid[x].append('rawcode in arithmetic/ordering in %s' % fname)
    for fname, d in m['others'].items():
        hash_key = fname.lower()
        if hash_key == 'war3map.wts':
            continue
        if hash_key in STRUCTURED:
            try:
                STRUCTURED[hash_key](d, {}, m['lang'])
                continue
            except NotClosed as e:
                if hash_key == 'war3map.wtg':
                    _b, _c, outside = wtg_by_default(d, dict((k, k) for k in candidates))
                    for k in outside:
                        avoid[k].append('%s (outside the patterns: %s)' % (fname, str(e)[:60]))
                    continue
                why = '%s (does not close: %s)' % (fname, str(e)[:60])
                for k in candidates:
                    if k in d:
                        avoid[k].append(why)
                continue
        if RX_TEXT.search(fname) or '.' not in fname.rsplit('\\', 1)[-1]:
            letter_case = bytes.lower if RX_NO_CASE.search(fname) else (lambda x: x)
            dd = letter_case(d)
            matches = set(x.group(0) for x in RX_TOKEN.finditer(dd))
            for k in candidates:
                if letter_case(k) in matches or (not k.isalnum() and letter_case(k) in dd):
                    avoid[k].append(fname)
    return avoid


NON_PRINTABLE = bytes(range(1, 9)) + bytes(range(14, 32))


def draw(candidates, forbidden, seed, non_ascii=False, avoid_bytes=()):
    rng = random.Random(seed)
    out = {}
    for old in candidates:
        for _t in range(100000):
            if non_ascii:
                new = old[:1] + bytes(rng.choice(NON_PRINTABLE) for _i in range(3))
            else:
                new = old[:1] + bytes(rng.choice(ALPHABET) for _i in range(3))
            if new.lower() not in forbidden and not any(new in blob for blob in avoid_bytes):
                break
        else:
            raise ValueError('no free id with the letter %r' % old[:1])
        forbidden.add(new.lower())
        out[old] = new
    return out


def reuses(candidates, previous, forbidden, from_game, avoid_bytes=()):
    reuse, nameless, taken = {}, {}, set()
    for old in candidates:
        if old not in previous:
            continue
        new = previous[old][0]
        txt = new.decode('latin-1')
        if len(new) != 4 or new[:1] != old[:1]:
            nameless[old] = 'the key id (%s) does not keep the 1st letter of the old one' % txt
        elif new.lower() in from_game:
            nameless[old] = 'the key id (%s) is a game id' % txt
        elif new.lower() in forbidden:
            nameless[old] = 'the key id (%s) is already used or cited by the map' % txt
        elif new.lower() in taken:
            nameless[old] = 'the key id (%s) was already reused by another id' % txt
        elif any(new in blob for blob in avoid_bytes):
            nameless[old] = 'the key id (%s) appears in a file that is not rewritten' % txt
        else:
            reuse[old] = new
            taken.add(new.lower())
    return reuse, nameless


def read_tsv(file_path):
    out = {}
    with open(file_path, encoding='utf-8') as f:
        next(f)
        for ln in f:
            c = ln.rstrip('\r\n').split('\t')
            if len(c) >= 2:
                out[bytes.fromhex(c[0])] = (id_from_text(c[1]),) + tuple(c[2:5])
    return out


def read_previous(file_path):
    try:
        with open(file_path, encoding='utf-8') as f:
            head_line = f.readline()
        if not head_line.startswith('old_id_hex\tnew_id'):
            raise ValueError('the header is not that of the key (%r)' % head_line[:40])
        return read_tsv(file_path)
    except (OSError, ValueError) as e:
        raise SystemExit('--previous-key: %s is not an ID key (.tsv): %s' % (file_path, e))


def write_tsv(file_path, ids, defs, retired=None):
    type_name = dict((e, t) for e, _n, t in TYPES)

    def limpo(x):
        return x.replace('\t', ' ').replace('\r', ' ').replace('\n', ' ')
    with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('old_id_hex\tnew_id\ttype\tbase\tname\n')
        for old, new in sorted(ids.items(), key=lambda x: (defs[x[0]][0], x[0])):
            ext, base, fname = defs[old]
            f.write('%s\t%s\t%s\t%s\t%s\n' % (old.hex(), id_text(new), type_name[ext], base, limpo(fname)))
        for old, ln in sorted((retired or {}).items()):
            rest = (tuple(ln[1:]) + ('', '', ''))[:3]
            f.write('%s\t%s\t%s\t%s\t%s\tretired\n' % ((old.hex(), id_text(ln[0]))
                                                         + tuple(limpo(x) for x in rest)))


def applies(m, ids):
    new_ones = dict((k, (v,)) for k, v in ids.items())
    replacements, matrix, warnings = [], {}, []

    def ln(fname, d, d2, tally, not_interp, method='reworked'):
        changed = d2 != d
        diffs = (sum(1 for x, y in zip(d, d2) if x != y) if len(d) == len(d2) else
                 'size %d -> %d' % (len(d), len(d2)))
        matrix[fname] = {'method': method if changed else 'no reference', 'references': dict(tally),
                         'bytes_changed': diffs if changed else 0, 'round_trip': 'ok', 'not_interpreted': not_interp,
                         'byte_size': len(d)}
        if changed:
            replacements.append((fname, d2))
    for prefix, files_ in (('war3map.', m['files_']), (SKIN, m['skin_id'])):
        output, tally = rewrite_objects(files_, new_ones)
        per_file_counts = collections.defaultdict(collections.Counter)
        for k, v in tally.items():
            per_file_counts['?'][k] += v
        for ext, (_v, _o, _n, d, pos) in files_.items():
            fname = prefix + ext
            _s, c1 = rewrite_objects({ext: files_[ext]}, new_ones)
            d2 = swap_tooltip(output.get(ext, d), ids, c1)
            ln(fname, d, d2, c1, len(d) - pos)
    for fname, j, lang in m['scripts']:
        j2, tally = rewrite_code(j, ids, lang)
        ln(fname, j, j2, tally, 0)
        matrix[fname]['not_interpreted'] = 'text (outside string/comment)'
    for fname, d in m['others'].items():
        hash_key = fname.lower()
        if hash_key == 'war3map.wts':
            cw = collections.Counter()
            d2 = swap_tooltip(d, ids, cw, comment_text=True)
            ln(fname, d, d2, cw, '-', 'rewritten (only tooltip and comment)')
            matrix[fname]['round_trip'] = '-'
            _toks = re.findall(rb'(?<![0-9A-Za-z])[0-9A-Za-z]{4}(?![0-9A-Za-z])', d2)
            matrix[fname]['id_quoted_in_text'] = sum(1 for _t in _toks if _t in ids)
            continue
        if hash_key not in STRUCTURED:
            continue
        try:
            r = STRUCTURED[hash_key](d, ids, m['lang'])
            ln(fname, d, r[0], r[1], r[2] if len(r) > 2 else 0)
        except NotClosed as e:
            if hash_key == 'war3map.wtg':
                d2, tally, outside = wtg_by_default(d, ids)
                if outside:
                    raise ValueError(
                        'wtg: ids outside the patterns that should be in the avoid list: %r' % sorted(outside)
                    )
                ln(fname, d, d2, tally, len(d), 'rewritten by pattern (%s)' % str(e)[:60])
                matrix[fname]['round_trip'] = 'cannot read (only the exact patterns)'
            else:
                matrix[fname] = {'method': 'untouched (does not close: %s)' % str(e)[:60], 'references': {},
                                 'bytes_changed': 0, 'round_trip': 'DOES NOT CLOSE', 'not_interpreted': len(d),
                                 'byte_size': len(d)}
    return replacements, matrix, warnings


def references(m, universe):
    ident = dict((k, k) for k in universe)
    _t, matrix, _a = applies(m, ident)
    return dict((n, sum(v for v in x['references'].values())) for n, x in matrix.items()
                if not x['method'].startswith('only counted'))


def shuffle(entry, output, tsv=None, seed=None, keep_names=(), undo=None, only_count=False, game=None,
            non_ascii=False, previous=None, log=print):
    details = {'entry': entry, 'output': output, 'ok': False}
    if previous and undo:
        raise SystemExit('--anterior does not combine with --desfaz (the undo already follows the key it receives)')
    prev_tab = read_previous(previous) if previous else None
    retired = {}
    a = mpqread.Archive(entry)
    m = read_map(a)
    for fname, j, lang in m['scripts']:
        if b'function main' not in j:
            raise SystemExit(
                '%s is not a complete script (%d B, no `function main`: the KKWE stub, with the real script '
                'encrypted in another file): the ids it cites cannot be rewritten, the map would break. '
                'I will not shuffle.' % (fname, len(j))
            )
    defs = defined(m['files_'])
    if undo:
        tab = read_tsv(undo)
        ids = dict((new, old) for old, (new, _t, _b, _n) in tab.items() if new in defs)
        log('undo: %d of %d ids of %s are in the map' % (len(ids), len(tab), undo))
        avoid = {}
    else:
        if seed is None:
            h = hashlib.sha256()
            with open(entry, 'rb') as f:
                for block_entry in iter(lambda: f.read(1 << 20), b''):
                    h.update(block_entry)
            seed = int(h.hexdigest()[:16], 16)
        keep_names = set(x.encode('latin-1') for x in keep_names)
        avoid = where_is(m, set(defs) - keep_names)
        for k in keep_names & set(defs):
            avoid.setdefault(k, []).append('kept on request')
        from_game = game_ids(game or None)
        if not from_game:
            raise SystemExit('no game SLK/txt found: without them the new id may be a game one')
        forbidden = map_ids(m) | from_game | set(k.lower() for k in defs)
        candidates = sorted(k for k in defs if k not in avoid)
        candidates.sort(key=lambda k: ([e for e, _n, _t in TYPES].index(defs[k][0]), k))
        avoid_bytes = [d for fname, d in m['others'].items() if _dont_rewrite(fname, d, m['lang'])]
        reuse, no_reuse = {}, {}
        if prev_tab is not None:
            reuse, no_reuse = reuses(candidates, prev_tab, forbidden, from_game, avoid_bytes)
            forbidden |= set(x[0].lower() for x in prev_tab.values())
            for k in prev_tab:
                if k in avoid and k in defs:
                    no_reuse[k] = 'kept now: %s' % '; '.join(avoid[k][:2])
        drawn = draw([k for k in candidates if k not in reuse], forbidden, seed, non_ascii=non_ascii,
                     avoid_bytes=avoid_bytes)
        ids = dict((k, reuse[k] if k in reuse else drawn[k]) for k in candidates)
        if prev_tab is not None:
            occupied = set(v.lower() for v in ids.values()) | set(k.lower() for k in defs if k not in ids)
            for k, ln in sorted(prev_tab.items()):
                if k not in ids and ln[0].lower() not in occupied:
                    retired[k] = ln
                    occupied.add(ln[0].lower())
            new_ones = sum(1 for k in candidates if k not in prev_tab)
            details['previous'] = {'hash_key': previous, 'in_key': len(prev_tab), 'reused': len(reuse),
                                   'new_drawn': new_ones, 'retired': len(retired),
                                   'no_reuse': dict((k.decode('latin-1'), v) for k, v in sorted(no_reuse.items()))}
            log('previous: %d of %d ids of the key %s reused; %d new object(s) drawn; %d without reuse (the save '
                'that stores these ids breaks); %d retired id(s) reserved'
                % (len(reuse), len(prev_tab), previous, new_ones, len(no_reuse), len(retired)))
            for k, v in sorted(no_reuse.items())[:20]:
                log('  no reuse %s: %s' % (k.decode('latin-1'), v))
            if prev_tab and not reuse:
                log(
                    'WARNING: no id of the previous key was reused: is it the key of the previous version of THIS map (the one of the '
                    'clean map, not that of an already protected map)?'
                )
        details['seed'] = seed
        details['non_ascii'] = non_ascii
        details['game_ids'] = len(from_game)
    if tsv and not undo:
        write_tsv(tsv, ids, defs, retired)
        log('table (the KEY; does not go with the map): %s' % tsv)
    details['replaced'] = len(ids)
    details['by_kind'] = dict(collections.Counter(defs[k][0] for k in ids))
    details['kept'] = dict((k.decode('latin-1'), v) for k, v in sorted(avoid.items()))
    log('ids swapped: %d %s; kept: %d' % (len(ids), details['by_kind'], len(avoid)))
    for k, v in sorted(avoid.items())[:20]:
        log('  kept %s: %s' % (k.decode('latin-1'), '; '.join(v[:3])))
    replacements, matrix, _av = applies(m, ids)
    details['matrix'] = matrix
    before = references(m, set(ids))
    leftovers = dict((fname, leftovers_in_code(t, set(ids), lang)) for fname, t, lang in
                     [(n, dict(replacements).get(n, j), lg) for n, j, lg in m['scripts']])
    details['leftovers_in_script'] = leftovers
    for fname, x in sorted(matrix.items()):
        log('  %-28s %-24s refs=%-5s bytes changed=%-8s round trip=%-5s not interpreted=%s'
            % (fname, x['method'][:24], sum(x['references'].values()), x['bytes_changed'], x['round_trip'],
               x['not_interpreted']))
    log('script: reference to a leftover old id: %s' % leftovers)
    if only_count:
        details['ok'] = not any(leftovers.values())
        return details
    if any(leftovers.values()):
        raise SystemExit('a reference to an old id is left in the script: not writing')
    if os.path.normcase(os.path.abspath(output)) == os.path.normcase(os.path.abspath(entry)):
        raise SystemExit('the output must be a different file (the original does not change)')
    shutil.copyfile(entry, output)
    import mpqadd
    if replacements:
        mpqadd.add_files(output, replacements, log=lambda *x: None)
    b = mpqread.Archive(output)
    bad_ones = [n for n, data_bytes in replacements if b.read(n) != data_bytes]
    m2 = read_map(b)
    defs2 = defined(m2['files_'])
    old_defined = sorted(k.decode('latin-1') for k in ids if k in defs2)
    missing_items = sorted(v.decode('latin-1') for v in ids.values() if v not in defs2)
    after_diag = references(m2, set(ids.values()))
    orphans = references(m2, set(ids))
    open_names = dict((n, (before.get(n, 0), after_diag.get(n, 0))) for n in set(before) | set(after_diag)
                      if before.get(n, 0) != after_diag.get(n, 0))
    orphans = dict((n, v) for n, v in orphans.items() if v)
    leftovers2 = dict((n, leftovers_in_code(t, set(ids), lg)) for n, t, lg in m2['scripts'])
    details.update({'reread_different': bad_ones, 'old_still_defined': old_defined, 'new_missing': missing_items,
                    'references_before': before, 'references_after': after_diag, 'open_graph': open_names,
                    'orphans': orphans, 'leftovers_in_written_script': leftovers2})
    log('written: %s -- %d file(s) swapped, re-read %s' % (output, len(replacements),
                                                           'identical' if not bad_ones else 'DIFFERENT %s' % bad_ones))
    log(
        'graph: references before=%d after=%d; files that do not close: %s; orphans (old id): %s; '
        'old id defined: %d; new id missing: %d'
        % (
            sum(before.values()),
            sum(after_diag.values()),
            open_names or 'none',
            orphans or 'none_found',
            len(old_defined),
            len(missing_items),
        )
    )
    details['ok'] = not (bad_ones or old_defined or missing_items or open_names or orphans or any(leftovers2.values()))
    return details
