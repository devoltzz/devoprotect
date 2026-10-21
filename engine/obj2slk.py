# Writes the map's object data as the game's own SLK and TXT tables, read from the installed game or from the downloaded tables pack.
import collections
import fnmatch
import os
import re

import slk_cols
import slk_levels
import slk_objects


SPECIES = slk_objects.SPECIES
TXT_MODES = ('full', 'delta', 'none')
MAX_LEVEL = 6
NONE_ID = slk_objects.NONE_ID
NUMBER_TYPES = slk_objects.INT_TYPES | frozenset(('real', 'unreal'))
EMPTY_MARK = frozenset(['auto', 'primary', 'preventplace', 'requireplace'])


def _objects():
    import objects
    return objects


def _out_name(details):
    head, _sep, tail = details.partition('\\')
    return head[:1].upper() + head[1:] + '\\' + tail if tail else details


def _unquote(k):
    return k[1:-1] if len(k) >= 2 and k[0] == '"' and k[-1] == '"' else k


def slk_raw(data):
    txt = data.decode('utf-8', 'surrogateescape')
    cells = {}
    y = 0
    for line in txt.split('\n'):
        line = line.rstrip('\r')
        if not line.startswith('C;'):
            continue
        x = k = None
        for f in slk_cols.slk_fields(line):
            if f[:1] == 'X' and f[1:].isdigit():
                x = int(f[1:])
            elif f[:1] == 'Y' and f[1:].isdigit():
                y = int(f[1:])
            elif f[:1] == 'K':
                k = f[1:]
        if x is None or k is None:
            continue
        cells.setdefault(y, {})[x] = k
    head = cells.get(1, {})
    header = [_unquote(head.get(i, '')) for i in range(1, max(head or [0]) + 1)]
    rows = collections.OrderedDict()
    for yy in sorted(cells):
        if yy == 1 or 1 not in cells[yy]:
            continue
        rows[_unquote(cells[yy][1])] = cells[yy]
    return header, rows


def ini_raw(data):
    if data[:3] == b'\xef\xbb\xbf':
        data = data[3:]
    out = collections.OrderedDict()
    cur = None
    for line in data.decode('utf-8', 'surrogateescape').split('\n'):
        line = line.rstrip('\r')
        if not line or line.startswith('//') or line.startswith(';'):
            continue
        m = re.match(r'^\[([^\]]+)\]\s*$', line)
        if m:
            cur = out.setdefault(m.group(1), collections.OrderedDict())
            continue
        if cur is None or '=' not in line:
            continue
        k, v = line.split('=', 1)
        cur[k.strip().lower()] = (k.strip(), v.strip())
    return out


class Kind(object):
    def __init__(self, base, species, max_level=MAX_LEVEL):
        ob = _objects()
        cfg = ob.OBJ_KINDS[species]
        self.species = species
        self.flat = base.table(species)
        self.raw_data = base.raw_data(species)
        self.meta = base.metadata(species)
        self.multi = ob._multipart(self.meta)
        self.per_level = ob._tips_per_level(self.meta) if species == 'ability' else set()
        self.cols = slk_objects.Columns(species, self.meta)
        self.slk = []
        for details in cfg['slk']:
            cpath = base.resolve(details)
            if cpath is not None:
                h, rows = slk_raw(base.read_data(cpath))
                self.slk.append((details, h, rows))
        self.game_max_level = 0
        self.max_level = 0
        if species == 'ability':
            self._extend_levels(max_level)
        self.id_cols = set(h[0].lower() for _r, h, _rows in self.slk if h)
        self.slk_cols = set(c.lower() for _r, h, _rows in self.slk for c in h if c)
        self.txt = []
        for pad in cfg['txt']:
            for n in base._names(pad):
                cpath = base.resolve(n)
                if cpath is not None:
                    self.txt.append((n, ini_raw(base.read_data(cpath))))
        for pad in cfg['locale']:
            for n in base._names(pad, locale=True):
                cpath = base.resolve_locale(n)
                if cpath is not None:
                    self.txt.append((n, ini_raw(base.read_data(cpath))))
        homes = collections.defaultdict(collections.Counter)
        for i, (_n, secs) in enumerate(self.txt):
            for sec in secs.values():
                for k in sec:
                    homes[k.split(':', 1)[0]][i] += 1
        self.home = {k: max(c, key=lambda i: (c[i], i)) for k, c in homes.items()}

    def _extend_levels(self, top):
        for i, (details, h, rows) in enumerate(self.slk):
            levels = [int(m.group(1)) for c in h for m in [re.match(r'^DataA(\d+)$', c)] if m]
            self.game_max_level = max(levels or [0])
            extra = ['%s%d' % (f, n) for n in range(self.game_max_level + 1, top + 1) for f in slk_levels.LEVEL_FIELDS]
            if extra and self.game_max_level:
                last = max([len(h)] + [max(c) for c in rows.values() if c])
                self.slk[i] = (details, h + [''] * (last - len(h)) + extra, rows)
        self.max_level = max(top, self.game_max_level)

    def meta_type(self, key):
        r = self.cols.resolve(key)
        return r[0][3] if r else None


def read_objects(read, species):
    ob = _objects()
    name = ob.OBJ_KINDS[species]['map_path']
    lvl = ob.uses_levels(name)
    merged = collections.OrderedDict()
    ver = None
    files = []
    for n in (name, name.replace('war3map.', 'war3mapSkin.')):
        d = read(n)
        if not d:
            continue
        v, objs, _p = ob.read_objects_bytes(d, lvl, fname=n)
        ver = ver or v
        files.append(n)
        for t, o, nw, mods in objs:
            merged.setdefault((t, o, nw), []).extend(list(mods))
    return ver, [(k[0], k[1], k[2], m) for k, m in merged.items()], files


def read_wts(read):
    import object_names
    d = read('war3map.wts') or b''
    return dict((int(m.group(1)), m.group(2).decode('utf-8', 'surrogateescape'))
                for m in object_names.wts_entries(d))


def _usable_id(s):
    return slk_objects._id_ok(s) and not (s[0] in '-.' or s[0].isdigit() or s[-1] == ']')


def _new_rel():
    return {'unknown_fields': collections.Counter(), 'missing_trigstr': set(), 'tally': collections.Counter()}


def _route(kind, mod, txt, wts):
    ob = _objects()
    code, type_name, level = mod[0], mod[1], mod[2]
    m = kind.meta.get(code)
    if m is None:
        return 'no_field'
    field = (m.get('field') or '').lower()
    src = m.get('slk') or ''
    rep = ob._int(m.get('repeat'), 0)
    if src == 'Profile':
        if txt == 'none':
            return 'profile_kept'
        target = 'txt'
    else:
        col = field
        if kind.species == 'ability':
            data = ob._int(m.get('data'), 0)
            col += ob.LETTERS[data - 1].lower() if 0 < data <= len(ob.LETTERS) else ''
            if rep > 0:
                if level > kind.max_level:
                    return 'level_above_%d' % kind.max_level
                col += str(max(level, 1))
        if col not in kind.slk_cols:
            return 'no_column'
        if txt == 'none' and col in kind.home:
            return 'profile_kept'
        target = 'slk'
    if type_name == 3:
        s = ob.render(type_name, mod[4], wts)
        if '"' in s:
            return 'quote'
        if target == 'slk' and s and s[0] in '0123456789-.' and m.get('type') not in NUMBER_TYPES:
            return 'number_like_text'
    return None


class Converted(object):
    def __init__(self, kind, objs, txt, wts, fill_levels=True, others=None):
        ob = _objects()
        self.kind = kind
        letter_case = collections.defaultdict(set)
        for i in kind.flat:
            letter_case[i.lower()].add(i)
        for _n, secs in kind.txt:
            for i in secs:
                letter_case[i.lower()].add(i)
        for t, o, n, _m in objs:
            letter_case[(n if t == 1 else o).lower()].add(n if t == 1 else o)
        self.rows = collections.OrderedDict()
        self.levels = {}
        self.parent = {}
        self.left = []
        self.rep = collections.Counter()
        self.kept = collections.Counter()
        self.filled = collections.Counter()
        self.lost = collections.Counter()
        details = _new_rel()
        seen = set()
        for t, o, n, mods in objs:
            oid = n if t == 1 else o
            why = None
            if o not in kind.flat:
                why = 'parent_unknown'
            elif t == 1 and (n in kind.flat or not _usable_id(n)):
                why = 'id_not_usable'
            elif kind.species == 'ability' and t == 1 and o == 'ACac':
                why = 'based_on_ACac'
            elif oid in seen:
                why = 'duplicate_id'
            elif letter_case[oid.lower()] - {oid}:
                why = 'id_case_conflict'
            elif t == 1 and others and others.get(oid.lower()):
                why = 'id_case_conflict_other_kind'
            if why:
                self.rep['objects_kept'] += 1
                self.kept['object_' + why] += 1
                self.left.append((t, o, n, list(mods)))
                continue
            seen.add(oid)
            absorb, keep = [], []
            for md in mods:
                why = _route(kind, md, txt, wts)
                (keep if why else absorb).append(md)
                if why:
                    self.kept[why] += 1
            rec = dict(kind.flat[o])
            level_data = ob.apply_modifications(
                kind.species, rec, kind.raw_data.get(o, {}), absorb, kind.meta, kind.multi, kind.per_level, wts, details
            )
            self.rows[oid] = rec
            self.levels[oid] = level_data
            self.parent[oid] = o
            self.rep['new' if t == 1 else 'originals'] += 1
            self.rep['mods'] += len(mods)
            self.rep['mods_absorbed'] += len(absorb)
            if t == 1 and txt == 'none':
                keep = self._inherited_profile(o, keep, slk_objects._num(rec.get('levels')))
            if keep:
                self.left.append((0, oid, NONE_ID, keep))
            if fill_levels and kind.species == 'ability':
                self._fill(oid, rec)

    def _inherited_profile(self, parent, keep, levels=None):
        kind = self.kind
        prow = kind.flat[parent]
        sub = dict((k, v) for k, v in prow.items() if k in kind.home and kind.cols.resolve(k))
        sub['levels'] = prow.get('levels')
        for k in prow:
            if k in kind.home and not kind.cols.resolve(k):
                self.lost[k] += 1
        r = {'unmapped': collections.Counter(), 'twins': 0}
        inherited = slk_objects._mods_of(
            kind.species, kind.cols, kind.meta, sub, kind.raw_data.get(parent), None, None, r
        )
        own = set((m[0], m[2]) for m in keep)
        top = int(levels) if levels else None
        return keep + [m for m in inherited if (m[0], m[2]) not in own and kind.meta[m[0]].get('slk') == 'Profile'
                       and not (m[1] == 3 and m[4] == b'') and not (top and m[2] > top)]

    def _fill(self, oid, rec):
        kind = self.kind
        top = kind.game_max_level
        n = slk_objects._num(rec.get('levels'))
        if not top or n is None or n <= top:
            return
        for f in slk_levels.LEVEL_FIELDS:
            v4 = rec.get('%s%d' % (f.lower(), top))
            if v4 in (None, ''):
                continue
            for lv in range(top + 1, min(int(n), kind.max_level, MAX_LEVEL) + 1):
                k = '%s%d' % (f.lower(), lv)
                if rec.get(k) in (None, ''):
                    rec[k] = v4
                    self.filled[k] += 1

    def changed(self, oid):
        prow = self.kind.flat[self.parent[oid]]
        rec = self.rows[oid]
        out = dict((k, v) for k, v in rec.items() if str(v) != str(prow.get(k, '')))
        lv = dict((k, v) for k, v in self.levels.get(oid, {}).items() if v)
        for k in lv:
            out.pop(k, None)
        return out, lv


def _slk_cell(kind, col, value):
    t = '' if value is None else str(value)
    if t == '' and (col.lower() in EMPTY_MARK or re.match(r'^targs\d+$', col.lower())):
        return '"_"'
    if t == '':
        return None
    if kind.meta_type(col.lower()) in NUMBER_TYPES or kind.meta_type(col.lower()) is None:
        if slk_objects._num(t) is not None and t.strip() not in ('-', '_'):
            return t.strip()
    return '"%s"' % re.sub(r'\r\n|\r|\n', '|n', t)


def write_slk(kind, conv):
    out = []
    for details, header, rows in kind.slk:
        lower = [c.lower() for c in header]
        order = list(rows) + sorted(i for i in conv.rows if i not in rows and conv.parent[i] in rows)
        lines = ['ID;PWXL;N;E', 'B;X%d;Y%d;D0' % (len(header), len(order) + 1)]
        for x, c in enumerate(header, 1):
            if c:
                lines.append('C;X%d;%sK"%s"' % (x, 'Y1;' if x == 1 else '', c))
        for y, rid in enumerate(order, 2):
            if rid in conv.rows:
                prow = rows.get(conv.parent[rid], {})
                ch, _lv = conv.changed(rid)
                cells = {}
                for x, c in enumerate(lower, 1):
                    if x == 1:
                        cells[x] = '"%s"' % rid
                    elif kind.species == 'unit' and c == 'name':
                        if rid != conv.parent[rid]:
                            cells[x] = '"custom_%s"' % rid
                        elif x in prow:
                            cells[x] = prow[x]
                    elif c and c in ch:
                        k = _slk_cell(kind, header[x - 1], ch[c])
                        if k is not None:
                            cells[x] = k
                    elif x in prow:
                        cells[x] = prow[x]
            else:
                cells = rows[rid]
            first = True
            for x in sorted(cells):
                lines.append('C;X%d;%sK%s' % (x, ('Y%d;' % y) if first else '', cells[x]))
                first = False
        lines.append('E')
        out.append((_out_name(details), ('\r\n'.join(lines) + '\r\n').encode('utf-8', 'surrogateescape')))
    return out


def _txt_value(kind, key, value):
    t = re.sub(r'\r\n|\r|\n', '|n', '' if value is None else str(value))
    if ('Profile', key) in kind.multi:
        return ','.join('"%s"' % p if p != p.strip() else p for p in t.split(','))
    mt = kind.meta_type(key)
    if (',' in t or t != t.strip()) and (mt is None or mt not in NUMBER_TYPES and not mt.endswith('List')):
        return '"%s"' % t
    return t


def _txt_levels(values):
    return ','.join('"%s"' % re.sub(r'\r\n|\r|\n', '|n', str(v)) for v in values)


def write_txt(kind, conv, txt):
    if txt == 'none':
        return []
    files = [(n, collections.OrderedDict((sid, collections.OrderedDict(sec)) for sid, sec in secs.items()))
             for n, secs in kind.txt]
    touched = collections.OrderedDict()
    for oid in conv.rows:
        pair = conv.parent[oid]
        ch, lv = conv.changed(oid)
        if oid != pair:
            for i, (_n, secs) in enumerate(kind.txt):
                if pair in secs:
                    files[i][1][oid] = collections.OrderedDict(secs[pair])
                    touched.setdefault(i, set()).add(oid)
        keys = [(k, _txt_value(kind, k, v)) for k, v in ch.items()
                if (k in kind.home or (kind.cols.resolve(k) and k not in kind.slk_cols)) and k not in kind.id_cols]
        keys += [(k, _txt_levels(v)) for k, v in lv.items()]
        for k, val in keys:
            where = [i for i, (_n, secs) in enumerate(files) if oid in secs and any(
                q.split(':', 1)[0] == k for q in secs[oid])]
            dst = where[-1] if where else kind.home.get(k, len(files) - 1)
            for i in where:
                sec = files[i][1][oid]
                for q in [q for q in sec if q.split(':', 1)[0] == k]:
                    del sec[q]
                touched.setdefault(i, set()).add(oid)
            sec = files[dst][1].setdefault(oid, collections.OrderedDict())
            sec[k] = (_key_case(kind, k), val)
            touched.setdefault(dst, set()).add(oid)
    out = []
    for i, (n, secs) in enumerate(files):
        if txt == 'delta':
            secs = collections.OrderedDict((s, v) for s, v in secs.items() if s in touched.get(i, ()))
            if not secs:
                continue
        lines = []
        for sid, sec in secs.items():
            lines.append('[%s]' % sid)
            lines.extend('%s=%s' % kv for kv in sec.values())
            lines.append('')
        out.append((_out_name(n), '\r\n'.join(lines).encode('utf-8', 'surrogateescape')))
    return out


def _key_case(kind, key):
    for c, _i, _t, _d, _r in kind.cols.simple.get(key, ()):
        f = kind.meta[c].get('field')
        if f and f.lower() == key:
            return f
    return key


def write_objects(ver, left, lvl):
    ob = _objects()
    return ob.write_objects_bytes(ver or 2, left, lvl)


def map_has_tables(read, names, species):
    import fnmatch
    ob = _objects()
    cfg = ob.OBJ_KINDS[species]
    low = [n.replace('/', '\\').lower() for n in names]
    found = [r for r in cfg['slk'] if read(r)]
    for pad in list(cfg['txt']) + list(cfg['locale']):
        found += [n for n in low if fnmatch.fnmatchcase(n, pad)]
    return found


def convert(read, base, names=(), species=SPECIES, txt='full', fill_levels=True, progress=None, max_level=MAX_LEVEL):
    if txt not in TXT_MODES:
        raise ValueError('txt must be one of %s' % (TXT_MODES,))
    ob = _objects()
    p = progress or (lambda *_a, **_k: None)
    wts = read_wts(read)
    out = {'files': [], 'report': {}, 'skipped': {}}
    read_count = dict((s, read_objects(read, s)) for s in species)
    all_items = collections.defaultdict(set)
    for s, (_v, objs, _f) in read_count.items():
        if not objs:
            continue
        for t, o, n, _m in objs:
            all_items[(n if t == 1 else o).lower()].add((s, n if t == 1 else o))
        for i in base.table(s):
            all_items[i.lower()].add((s, i))
    for s in species:
        ver, objs, files = read_count[s]
        if not objs:
            out['skipped'][s] = 'no object file'
            continue
        has = map_has_tables(read, names, s)
        if has:
            out['skipped'][s] = 'the map already ships %s' % ', '.join(has[:3])
            continue
        p('Converting the %s objects' % s)
        kind = Kind(base, s, max_level)
        others = dict((k, set(x for x in v if x[0] != s)) for k, v in all_items.items() if any(x[0] != s for x in v))
        conv = Converted(kind, objs, txt, wts, fill_levels, others=others)
        mine = write_slk(kind, conv) + write_txt(kind, conv, txt)
        lvl = ob.uses_levels(ob.OBJ_KINDS[s]['map_path'])
        for f in files:
            mine.append((f, write_objects(ver, conv.left if f == files[0] else [], lvl)))
        out['files'] += mine
        r = dict(conv.rep)
        r.update(
            kept=dict(conv.kept),
            filled=sum(conv.filled.values()),
            lost=dict(conv.lost),
            objects_left=len(conv.left),
            mods_left=sum(len(o[3]) for o in conv.left),
            game_rows=len(kind.flat),
            files=len(mine),
            bytes=sum(len(b) for _n, b in mine),
            object_bytes_before=sum(len(read(f)) for f in files),
            object_bytes_after=sum(len(b) for n, b in mine if n in files),
        )
        out['report'][s] = r
        out.setdefault('converted', {})[s] = (kind, conv, objs)
    return out


def check_pack(folder):
    import hashlib
    import json
    import casc_wc3
    with open(os.path.join(folder, casc_wc3.PACK_MANIFEST), encoding='utf-8') as f:
        m = json.load(f)
    for path, md5 in m['files'].items():
        try:
            with open(casc_wc3.pack_file_path(folder, path), 'rb') as f:
                ok = hashlib.md5(f.read()).hexdigest() == md5
        except OSError:
            ok = False
        if not ok:
            raise ValueError('the tables pack in %s is damaged (%s)' % (folder, path))
    return m


def unzip_pack(zip_path, folder):
    import shutil
    import zipfile
    tmp = folder + '.tmp'
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split('/')
            if info.filename.startswith('/') or any(c in info.filename for c in '\\:') or \
                    any(p in ('', '.', '..') for p in parts):
                raise ValueError('the tables pack has a name outside its folder: %r' % info.filename)
            target = os.path.join(tmp, *parts)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'wb') as f:
                f.write(z.read(info))
    m = check_pack(tmp)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.replace(tmp, folder)
    return m


def fetch_pack(url, sha256, cache, timeout=60, agent='obj2slk'):
    import hashlib
    import urllib.request
    import casc_wc3
    folder = os.path.join(cache, sha256[:16])
    if os.path.isfile(os.path.join(folder, casc_wc3.PACK_MANIFEST)):
        return folder
    req = urllib.request.Request(url, headers={'User-Agent': agent})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(64 << 20)
    got = hashlib.sha256(data).hexdigest()
    if got != sha256.lower():
        raise ValueError('the tables pack from %s is not the expected one (sha256 %s, expected %s)'
                         % (url, got[:16], sha256[:16]))
    os.makedirs(cache, exist_ok=True)
    zip_path = folder + '.zip'
    with open(zip_path + '.tmp', 'wb') as f:
        f.write(data)
    os.replace(zip_path + '.tmp', zip_path)
    try:
        unzip_pack(zip_path, folder)
    finally:
        os.remove(zip_path)
    return folder


def open_tables(game=None, pack=None):
    import casc_wc3
    if game:
        casc = casc_wc3.CascWC3(game)
    else:
        try:
            casc = casc_wc3.CascWC3(casc_wc3.DEFAULT_GAME)
        except Exception:
            if not pack:
                raise
            casc = casc_wc3.CascWC3(pack() if callable(pack) else pack)
    return casc, {
        'source': 'pack' if casc.is_pack else 'game',
        'version': casc.version_num,
        'build_key': casc.build_key,
    }
