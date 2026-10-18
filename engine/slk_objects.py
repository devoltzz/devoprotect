# Makes the editor object data (w3u, w3t, w3a) from the SLK and TXT tables of an optimized map.
import os
import re


SPECIES = ('unit', 'item', 'ability')
NONE_ID = '\0\0\0\0'
INT_TYPES = frozenset(('bool', 'int', 'attackBits', 'channelFlags', 'channelType', 'deathType', 'defenseTypeInt',
                       'detectionType', 'fullFlags', 'interactionFlags', 'morphFlags', 'pickFlags', 'silenceFlags',
                       'spellDetail', 'stackFlags', 'teamColor', 'versionFlags', 'techAvail'))
USE = {'unit': ('useunit', 'usehero', 'usebuilding', 'usecreep'), 'item': ('useitem',), 'ability': ()}
RX_LEVEL = re.compile(r'^(.*?)(\d+)$')


def _objetos():
    import objects
    return objects


def _tipo(meta_type, text):
    if meta_type in INT_TYPES:
        n = _num(text)
        return 2 if n is not None and n != int(n) else 0
    if meta_type == 'real':
        return 1
    if meta_type == 'unreal':
        return 2
    return 3


def _num(text):
    t = '' if text is None else str(text).strip()
    if t in ('', '-', '_'):
        return 0.0
    try:
        return float(t)
    except ValueError:
        return None


def _norm(text):
    t = '' if text is None else str(text).strip()
    return '' if t in ('-', '_') else t


def _equal(a, b, tipo):
    if tipo != 3:
        x, y = _num(a), _num(b)
        if x is not None and y is not None:
            return abs(x - y) < 1e-6 * max(1.0, abs(x), abs(y))
    return _norm(a) == _norm(b)


class Columns(object):
    def __init__(self, species, meta):
        ob = _objetos()
        self.species = species
        self.simple = {}
        self.levels = {}
        self.per_level = set()
        self.multi = ob._multipart(meta)
        use = USE[species]
        for code, m in meta.items():
            flags = {k.lower(): v for k, v in m.items() if k.lower().startswith('use')}
            if use and not any(str(flags.get(u) or '0') == '1' for u in use):
                continue
            slk_name = m.get('slk') or ''
            name = (m.get('field') or '').lower()
            if not name:
                continue
            idx = ob._int(m.get('index'), -1)
            data = ob._int(m.get('data'), 0)
            rep = ob._int(m.get('repeat'), 0)
            entry = (code, idx, m.get('type'), data, rep)
            if species == 'ability' and slk_name != 'Profile':
                col = name + (ob.LETTERS[data - 1].lower() if 0 < data <= len(ob.LETTERS) else '')
                if rep > 0:
                    self.levels.setdefault(col, entry)
                else:
                    self.simple.setdefault(col, []).append(entry)
            elif species == 'ability' and rep > 0:
                self.per_level.add(name)
                self.levels.setdefault(name + '#', entry)
                self.simple.setdefault(name, []).append(entry)
            else:
                self.simple.setdefault(name, []).append(entry)

    def resolve(self, col):
        if col in self.simple:
            return [(c, i, 0, t, d) for c, i, t, d, _r in self.simple[col]]
        m = RX_LEVEL.match(col)
        if m and m.group(1) in self.levels:
            c, i, t, d, _r = self.levels[m.group(1)]
            return [(c, i, int(m.group(2)), t, d)]
        return []


def balance_of(w3i_bytes):
    import tempfile
    ob = _objetos()
    if not w3i_bytes:
        return 'custom_v1'
    fd, tmp = tempfile.mkstemp(suffix='.w3i', prefix='slk_objects_')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(w3i_bytes)
        return ob.w3i_balance(tmp)[0]
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _row_fields(cols, row):
    mapped, unmapped = [], []
    for col, text in row.items():
        if col.endswith('_lv'):
            continue
        r = cols.resolve(col)
        if r:
            mapped.append((col, text, r))
        else:
            unmapped.append(col)
    return mapped, unmapped


def _parts(text):
    return text.split(',') if text else []


def _mods_of(species, cols, meta, row, cru_row, base_row, base_cru, rep):
    ob = _objetos()
    out = []
    mapped, unmapped = _row_fields(cols, row)
    for col in unmapped:
        rep['unmapped'][col] += 1
    listed = set()
    for col, text, targets in mapped:
        for code, idx, level, mtype, data in targets:
            if species == 'ability' and col in cols.per_level:
                if (col, code) in listed:
                    continue
                listed.add((col, code))
                mine = ob.value_levels((cru_row or {}).get(col), row.get('levels'))
                theirs = ob.value_levels((base_cru or {}).get(col), base_row.get('levels')) if base_row else []
                for i, v in enumerate(mine):
                    if i < len(theirs) and _norm(theirs[i]) == _norm(v):
                        continue
                    out.append((code, 3, i + 1, 0, _value(3, v, True)))
                continue
            btext = base_row.get(col) if base_row else None
            part = text
            if idx >= 0 and (meta[code].get('slk') or '', col) in cols.multi:
                mine, theirs = _parts(text), _parts(btext)
                part = mine[idx] if idx < len(mine) else ''
                btext = theirs[idx] if idx < len(theirs) else ''
            tipo = _tipo(mtype, part)
            if base_row is not None and _equal(part, btext, tipo):
                continue
            out.append((code, tipo, level, data, _value(tipo, part, (meta[code].get('slk') or '') == 'Profile')))
    final = []
    taken = set()
    for m in out:
        k = (m[0], m[2])
        if k in taken:
            rep['twins'] += 1
            continue
        taken.add(k)
        final.append(m)
    return final


def _value(tipo, text, profile=False):
    t = _norm(text)
    if tipo == 3 and profile:
        t = t.replace('|n', '\r\n')
    if tipo == 0:
        n = _num(t)
        return int(n) if n is not None else 0
    if tipo in (1, 2):
        n = _num(t)
        return float(n) if n is not None else 0.0
    return t.encode('utf-8', 'surrogateescape').replace(b'\0', b'')


def _id_ok(s):
    return isinstance(s, str) and len(s) == 4 and all(0x20 <= ord(c) < 0x100 for c in s)

