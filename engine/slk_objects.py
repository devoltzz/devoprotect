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


def _codes(text):
    return frozenset(x.strip() for x in str(text or '').strip('"').split(',') if x.strip())


class Columns(object):
    def __init__(self, species, meta):
        ob = _objetos()
        self.species = species
        self.simple = {}
        self.levels = {}
        self.levels_all = {}
        self.spec = {}
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
            self.spec[code] = (_codes(m.get('useSpecific')), _codes(m.get('notSpecific')))
            if species == 'ability' and slk_name != 'Profile':
                col = name + (ob.LETTERS[data - 1].lower() if 0 < data <= len(ob.LETTERS) else '')
                if rep > 0:
                    self.levels.setdefault(col, entry)
                    self.levels_all.setdefault(col, []).append(entry)
                else:
                    self.simple.setdefault(col, []).append(entry)
            elif species == 'ability' and rep > 0:
                self.per_level.add(name)
                self.levels.setdefault(name + '#', entry)
                self.simple.setdefault(name, []).append(entry)
            else:
                self.simple.setdefault(name, []).append(entry)

    def applies(self, field, code):
        use, excluded = self.spec.get(field, (frozenset(), frozenset()))
        return code in use if use else code not in excluded

    def resolve(self, col, code=None):
        if col in self.simple:
            ents = self.simple[col]
            if code is not None and self.species == 'ability':
                ents = [e for e in ents if self.applies(e[0], code)]
            return [(c, i, 0, t, d) for c, i, t, d, _r in ents]
        m = RX_LEVEL.match(col)
        if m and m.group(1) in self.levels:
            if code is not None and self.species == 'ability':
                ents = [e for e in self.levels_all[m.group(1)] if self.applies(e[0], code)]
                if not ents:
                    return []
                c, i, t, d, _r = ents[0]
            else:
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


CLASSIC_FOR_OLDER = '1.27b'


def game_of(path=None, version=None):
    import wc3_versions
    if version:
        if wc3_versions.is_reforged(version):
            return None, 'Reforged (the target)'
        v = wc3_versions.normalize(version) or version
        return v, '%s (the target)' % v
    if not path:
        return None, 'Reforged'
    try:
        d = wc3_versions.detect(path)
    except Exception as e:
        return None, 'Reforged (the version of the map was not found: %s)' % str(e)[:60]
    rng = d.get('range')
    if rng == 'pre-1.24':
        return CLASSIC_FOR_OLDER, '%s (the map is older than 1.24)' % CLASSIC_FOR_OLDER
    if rng in ('1.24-1.28', '1.29') and d.get('version'):
        return d['version'], '%s (the map is for %s)' % (d['version'], rng)
    return None, 'Reforged (the map is for %s)' % (rng or 'Reforged')


def game_base(version, w3i=None):
    ob = _objetos()
    if version:
        import wc3_versions
        g = wc3_versions.game(version)
        if g is None:
            raise RuntimeError('the game data of Warcraft III %s is not here' % version)
        return ob.GameBase(casc=g, balance=balance_of(w3i))
    return ob.GameBase(balance=balance_of(w3i))


def _row_fields(cols, row, code=None):
    mapped, unmapped = [], []
    for col, text in row.items():
        if col.endswith('_lv'):
            continue
        r = cols.resolve(col, code)
        if r:
            mapped.append((col, text, r))
        else:
            unmapped.append(col)
    return mapped, unmapped


def _parts(text):
    return text.split(',') if text else []


def _mods_of(species, cols, meta, row, cru_row, base_row, base_cru, rep, code=None):
    ob = _objetos()
    out = []
    mapped, unmapped = _row_fields(cols, row, code if species == 'ability' else None)
    for col in unmapped:
        rep['unmapped'][col] += 1
    levels = _levels(row, base_row) if species == 'ability' and code is not None else None
    listed = set()
    for col, text, targets in mapped:
        for code, idx, level, mtype, data in targets:
            if levels is not None and level > levels:
                rep['above_levels'] = rep.get('above_levels', 0) + 1
                continue
            if species == 'ability' and col in cols.per_level:
                if (col, code) in listed:
                    continue
                listed.add((col, code))
                if levels is None:
                    mine = ob.value_levels((cru_row or {}).get(col), row.get('levels'))
                    theirs = ob.value_levels((base_cru or {}).get(col), base_row.get('levels')) if base_row else []
                else:
                    mine = _per_level((cru_row or {}).get(col), levels)
                    theirs = _per_level((base_cru or {}).get(col), _levels(base_row, None)) if base_row else []
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


def _levels(row, base_row):
    for r in (row, base_row):
        n = _num((r or {}).get('levels')) if r else None
        if n:
            return max(1, int(n))
    return 1


def _per_level(raw, levels):
    if raw is None or raw == '':
        return []
    ob = _objetos()
    parts = [ob._unquoted(p.strip()) for p in ob._split_levels(raw)]
    return [parts[min(i, len(parts) - 1)] for i in range(levels)]


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

