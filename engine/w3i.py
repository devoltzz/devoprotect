# Reads and writes war3map.w3i, including damaged variants.
import struct



class R(object):
    def __init__(self, data):
        self.d = data
        self.p = 0

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.p)[0]
        self.p += 4
        return v

    def raw(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def s(self):
        e = self.d.index(b'\0', self.p)
        v = self.d[self.p:e]
        self.p = e + 1
        return v


class W(object):
    def __init__(self):
        self.parts = []

    def i32(self, v):
        self.parts.append(struct.pack('<i', v))

    def f32(self, v):
        self.parts.append(struct.pack('<f', v))

    def raw(self, b):
        self.parts.append(bytes(b))

    def s(self, b):
        self.parts.append(bytes(b) + b'\0')

    def bytes(self):
        return b''.join(self.parts)


def parse(data):
    r = R(data)
    m = _header(r)
    first_pos = r.p
    v = m['version']
    options = (True, False) if v >= 37 else (False,)
    for hud in options:
        r.p = first_pos
        m['player_hud'] = hud
        try:
            _sections(r, m, v)
        except (struct.error, ValueError, IndexError):
            continue
        plausible = all(0 <= p['type'] <= 4 and 0 <= p['race'] <= 4 and 0 <= p['fixed_start'] <= 3
                        for p in m['players'])
        if r.p == len(data) and plausible:
            m['_tail'] = b''
            return m
    r.p = first_pos
    m['player_hud'] = v >= 39
    _sections(r, m, v)
    m['_tail'] = data[r.p:]
    return m


def _header(r):
    m = {}
    v = m['version'] = r.i32()
    m['saves'] = r.i32()
    m['editor_version'] = r.i32()
    if v >= 27:
        m['game_version'] = [r.i32(), r.i32(), r.i32(), r.i32()]
    m['name'] = r.s()
    m['author'] = r.s()
    m['description'] = r.s()
    m['players_recommended'] = r.s()
    m['camera_bounds'] = [r.f32() for _ in range(8)]
    m['camera_complements'] = [r.i32() for _ in range(4)]
    m['width'] = r.i32()
    m['height'] = r.i32()
    m['flags'] = r.i32()
    m['tileset'] = r.raw(1)
    if v >= 25:
        m['loading_bg'] = r.i32()
        if v >= 37:
            m['race_crest'] = r.i32()
        m['loading_model'] = r.s()
    else:
        m['loading_bg'] = r.i32()
    m['loading_text'] = r.s()
    m['loading_title'] = r.s()
    m['loading_subtitle'] = r.s()
    if v >= 25:
        m['game_data_set'] = r.i32()
        m['prologue_model'] = r.s()
    else:
        m['loading_number'] = r.i32()
    m['prologue_text'] = r.s()
    m['prologue_title'] = r.s()
    m['prologue_subtitle'] = r.s()
    if v >= 25:
        m['fog_type'] = r.i32()
        m['fog_start'] = r.f32()
        m['fog_end'] = r.f32()
        m['fog_density'] = r.f32()
        m['fog_color'] = r.raw(4)
        if v >= 36:
            m['fog_heights'] = [r.f32() for _ in range(4)]
        if v >= 39:
            m['fog_extra'] = [r.f32(), r.i32()]
        m['weather'] = r.raw(4)
        m['sound_env'] = r.s()
        m['light_env'] = r.raw(1)
        m['water_tint'] = r.raw(4)
    if v >= 28:
        m['script_language'] = r.i32()
    if v >= 29:
        m['supported_modes'] = r.i32()
    if v >= 30:
        m['game_data_version'] = r.i32()
    if v >= 32:
        m['v33_extra'] = [r.i32() for _ in range(2 if v == 32 else 3)]
    if v >= 34:
        m['hd_water'] = [r.i32() for _ in range(7)] + [r.raw(4)]
    if v >= 35:
        m['hd_water_envmap'] = r.i32()
    if v >= 38:
        m['minimap_alpha_color'] = r.raw(4)
    return m


def _sections(r, m, v):
    hud = m.get('player_hud')
    n = r.i32()
    players = []
    for _ in range(n):
        p = {}
        p['number'] = r.i32()
        p['type'] = r.i32()
        p['race'] = r.i32()
        if hud:
            p['hud'] = r.i32()
        p['fixed_start'] = r.i32()
        p['name'] = r.s()
        p['x'] = r.f32()
        p['y'] = r.f32()
        p['ally_low'] = r.i32()
        p['ally_high'] = r.i32()
        if v >= 31:
            p['enemy_low'] = r.i32()
            p['enemy_high'] = r.i32()
        players.append(p)
    m['players'] = players
    n = r.i32()
    forces = []
    for _ in range(n):
        f = {'flags': r.i32(), 'mask': r.i32(), 'name': r.s()}
        forces.append(f)
    m['forces'] = forces
    n = r.i32()
    ups = []
    for _ in range(n):
        ups.append({'players': r.i32(), 'id': r.raw(4), 'level': r.i32(), 'avail': r.i32()})
    m['upgrades'] = ups
    n = r.i32()
    techs = []
    for _ in range(n):
        techs.append({'players': r.i32(), 'id': r.raw(4)})
    m['techs'] = techs
    n = r.i32()
    rug = []
    for _ in range(n):
        g = {'number': r.i32(), 'name': r.s()}
        pc = r.i32()
        g['types'] = [r.i32() for _ in range(pc)]
        lc = r.i32()
        lines = []
        for _ in range(lc):
            chance = r.i32()
            ids = [r.raw(4) for _ in range(pc)]
            lines.append((chance, ids))
        g['lines'] = lines
        rug.append(g)
    m['random_unit_groups'] = rug
    if v >= 25:
        n = r.i32()
        rit = []
        for _ in range(n):
            t = {'number': r.i32(), 'name': r.s()}
            sc = r.i32()
            sets = []
            for _ in range(sc):
                ic = r.i32()
                items = [(r.i32(), r.raw(4)) for _ in range(ic)]
                sets.append(items)
            t['sets'] = sets
            rit.append(t)
        m['random_item_tables'] = rit
    if v in (26, 27):
        m['legacy_script_language'] = r.i32()


PLAYER_TYPES = (0, 1, 2, 3, 4)


class _Short(Exception):
    pass


def _count(r, maximum):
    if len(r.d) - r.p < 4:
        return None
    n = r.i32()
    if not 0 <= n <= maximum:
        raise ValueError('count %d outside the plausible range' % n)
    return n


def _hke_player(r, v):
    num = r.i32()
    extra = 8 if v >= 31 else 0
    block_body = r.d[r.p:r.p + 256]
    if block_body[:4] != b'\0\0\0\0':
        raise ValueError('not type 0')
    k = next((i for i, c in enumerate(block_body[:28 + extra]) if c), None)
    if k is None:
        fname, sz = b'', 28 + extra
    else:
        e = block_body.find(b'\0', k)
        if e < 0:
            raise ValueError('name without NUL')
        fname = block_body[k:e]
        sz = 28 + extra + len(fname)
        if block_body[e:sz].strip(b'\0'):
            raise ValueError('type 0 with data after the name')
    if len(block_body) < sz:
        raise _Short()
    r.p += sz
    return {'number': num, 'type': 0, 'race': 0, 'fixed_start': 0, 'name': fname, 'x': 0.0, 'y': 0.0, 'ally_low': 0,
            'ally_high': 0}


def _object_id(b):
    return len(b) == 4 and all(0x20 < c < 0x7F for c in b)


def _read_upgrades(r):
    out = []
    for _ in range(_count(r, 100000)):
        u = {'players': r.i32(), 'id': r.raw(4), 'level': r.i32(), 'avail': r.i32()}
        if not _object_id(u['id']) or not 0 <= u['level'] < 1000 or not 0 <= u['avail'] <= 2:
            raise ValueError('implausible upgrade')
        out.append(u)
    return out


def _read_techs(r):
    out = []
    for _ in range(_count(r, 100000)):
        t = {'players': r.i32(), 'id': r.raw(4)}
        if not _object_id(t['id']):
            raise ValueError('implausible tech entry')
        out.append(t)
    return out


def _read_groups(r):
    out = []
    for _ in range(_count(r, 10000)):
        g = {'number': r.i32(), 'name': r.s()}
        pc = r.i32()
        if not 0 <= pc <= 64:
            raise ValueError('implausible random group')
        g['types'] = [r.i32() for _ in range(pc)]
        lc = r.i32()
        if not 0 <= lc <= 10000:
            raise ValueError('implausible random group')
        g['lines'] = []
        for _ in range(lc):
            chance = r.i32()
            ids = [r.raw(4) for _ in range(pc)]
            if not 0 <= chance <= 100 or any(len(x) < 4 for x in ids):
                raise ValueError('implausible random group line')
            g['lines'].append((chance, ids))
        out.append(g)
    return out


def _read_tables(r):
    out = []
    for _ in range(_count(r, 10000)):
        t = {'number': r.i32(), 'name': r.s()}
        sc = r.i32()
        if not 0 <= sc <= 10000:
            raise ValueError('implausible random table')
        sets = []
        for _ in range(sc):
            ic = r.i32()
            if not 0 <= ic <= 10000:
                raise ValueError('implausible random table')
            item_entries = [(r.i32(), r.raw(4)) for _ in range(ic)]
            if any(not 0 <= c <= 100 or len(i) < 4 for c, i in item_entries):
                raise ValueError('implausible random table item')
            sets.append(item_entries)
        t['sets'] = sets
        out.append(t)
    return out


def _section(r, reader, deviations):
    begin = r.p
    if len(r.d) - begin < 4:
        return 'cut_tail', []
    for skip in range(4):
        if skip and r.d[begin + skip - 1] != 0:
            break
        r.p = begin + skip
        try:
            regs = reader(r)
            if r.p > len(r.d):
                raise _Short()
            if skip:
                deviations.append('extra_byte')
            return 'ok', regs
        except (ValueError, IndexError, TypeError, struct.error, _Short):
            continue
    r.p = begin
    return 'junk', []


def _tolerant_sections(r, m, v, type0_short):
    deviations = []
    n = r.i32()
    if not 0 <= n <= 28:
        raise ValueError('%d players' % n)
    players = []
    for _ in range(n):
        if type0_short and r.d[r.p + 4:r.p + 8] == b'\0\0\0\0':
            players.append(_hke_player(r, v))
            deviations.append('player_type0_short')
            continue
        p = {'number': r.i32(), 'type': r.i32(), 'race': r.i32()}
        if m.get('player_hud'):
            p['hud'] = r.i32()
        p['fixed_start'], p['name'] = r.i32(), r.s()
        if not (0 <= p['number'] < 28 and p['type'] in PLAYER_TYPES and 0 <= p['race'] <= 5 and
                0 <= p['fixed_start'] <= 15):
            raise ValueError('implausible player: %r' % p)
        p['x'], p['y'], p['ally_low'], p['ally_high'] = r.f32(), r.f32(), r.i32(), r.i32()
        if v >= 31:
            p['enemy_low'], p['enemy_high'] = r.i32(), r.i32()
        if not (abs(p['x']) < 1e6 and abs(p['y']) < 1e6):
            raise ValueError('implausible position')
        players.append(p)
    m['players'] = players
    nf = r.i32()
    if not 0 <= nf <= 28 or (players and not nf):
        raise ValueError('%d forces' % nf)
    forces = []
    for _ in range(nf):
        f = {'flags': r.i32(), 'mask': r.i32(), 'name': r.s()}
        if not 0 <= f['flags'] < 0x10000:
            raise ValueError('implausible force')
        forces.append(f)
    m['forces'] = forces
    m['upgrades'], m['techs'], m['random_unit_groups'] = [], [], []
    if v >= 25:
        m['random_item_tables'] = []
    if len(r.d) - r.p == 1 and r.d[r.p] == 0xFF:
        r.p += 1
        deviations.append('tail_ff')
        return deviations
    sections = [('upgrades', _read_upgrades), ('techs', _read_techs), ('random_unit_groups', _read_groups)]
    if v >= 25:
        sections.append(('random_item_tables', _read_tables))
    for hash_key, reader in sections:
        status, regs = _section(r, reader, deviations)
        if status == 'cut_tail':
            deviations.append('truncated_tail')
            break
        if status == 'junk':
            deviations.append('junk_in_' + hash_key)
            break
        m[hash_key] = regs
    return deviations


def parse_tolerant(data):
    if len(data) < 4:
        raise ValueError('w3i too short: %d byte(s), not even the version fits' % len(data))
    best = None
    huds = (False, True) if struct.unpack_from('<i', data, 0)[0] >= 37 else (False,)
    for type0_short, hud in [(t, h) for t in (False, True) for h in huds]:
        r = R(data)
        try:
            m = _header(r)
            m['player_hud'] = hud
            deviations = _tolerant_sections(r, m, m['version'], type0_short)
        except (ValueError, IndexError, TypeError, struct.error, _Short):
            continue
        rest = data[r.p:]
        if not rest:
            score = 3
        elif not rest.strip(b'\0'):
            score = 2
            deviations.append('trailing_zeros')
        elif not rest.strip(b'\0\xcd'):
            score = 1
            deviations.append('junk_at_end')
        else:
            score = 0
            deviations.append('junk_at_end')
        if any(d.startswith('junk_in_') for d in deviations):
            score = min(score, 0)
        m['_tail'] = b''
        score = (score, -sum(1 for d in deviations if d == 'extra_byte' or d.startswith('junk_in_')))
        if best is None or score > best[2]:
            best = (m, sorted(set(deviations)), score)
    if best is None:
        raise ValueError('w3i version %d: no parse fits the file' % struct.unpack_from('<i', data, 0)[0])
    return best[0], best[1]


def parse_or_tolerant(data):
    try:
        return parse(data)
    except Exception:
        return parse_tolerant(data)[0]


LOSSLESS_DEVIATIONS = frozenset(('tail_ff', 'truncated_tail', 'trailing_zeros'))


def parse_lossless(data):
    try:
        return parse(data), []
    except Exception as e:
        strict = '%s: %s' % (type(e).__name__, e)
    m, deviations = parse_tolerant(data)
    outside = sorted(set(deviations) - LOSSLESS_DEVIATIONS)
    if outside:
        raise ValueError('the w3i does not read strictly (%s) and the tolerant read has a deviation that loses data: %s'
                         % (strict[:80], ', '.join(outside)))
    return m, deviations


def write(m, version=None):
    v = version if version is not None else m['version']
    w = W()
    w.i32(v)
    w.i32(m['saves'])
    w.i32(m['editor_version'])
    if v >= 27:
        w.i32(*[m.get('game_version', [1, 31, 1, 12173])[0]])
        for x in m.get('game_version', [1, 31, 1, 12173])[1:]:
            w.i32(x)
    w.s(m['name'])
    w.s(m['author'])
    w.s(m['description'])
    w.s(m['players_recommended'])
    for x in m['camera_bounds']:
        w.f32(x)
    for x in m['camera_complements']:
        w.i32(x)
    w.i32(m['width'])
    w.i32(m['height'])
    w.i32(m['flags'])
    w.raw(m['tileset'])
    w.i32(m['loading_bg'])
    if v >= 37:
        w.i32(m.get('race_crest', 0))
    if v >= 25:
        w.s(m.get('loading_model', b''))
    w.s(m['loading_text'])
    w.s(m['loading_title'])
    w.s(m['loading_subtitle'])
    if v >= 25:
        w.i32(m.get('game_data_set', 0))
        w.s(m.get('prologue_model', b''))
    else:
        w.i32(m.get('loading_number', 0))
    w.s(m['prologue_text'])
    w.s(m['prologue_title'])
    w.s(m['prologue_subtitle'])
    if v >= 25:
        w.i32(m.get('fog_type', 0))
        w.f32(m.get('fog_start', 0.0))
        w.f32(m.get('fog_end', 0.0))
        w.f32(m.get('fog_density', 0.0))
        w.raw(m.get('fog_color', b'\0\0\0\0'))
        if v >= 36:
            for x in m.get('fog_heights', [0.0, 0.0, 0.0, 0.0]):
                w.f32(x)
        if v >= 39:
            fx = m.get('fog_extra', [1.0, 0])
            w.f32(fx[0])
            w.i32(fx[1])
        w.raw(m.get('weather', b'\0\0\0\0'))
        w.s(m.get('sound_env', b''))
        w.raw(m.get('light_env', b'\0'))
        w.raw(m.get('water_tint', b'\xff\xff\xff\xff'))
    if v >= 28:
        w.i32(m.get('script_language', 0))
    if v >= 29:
        w.i32(m.get('supported_modes', 3))
    if v >= 30:
        w.i32(m.get('game_data_version', 1))
    if v >= 32:
        zoom = list(m.get('v33_extra') or [])
        n = 2 if v == 32 else 3
        for x in (zoom + [0] * n)[:n]:
            w.i32(x)
    if v >= 34:
        hd = m.get('hd_water') or [0] * 7 + [b'\xff\xff\xff\xff']
        for x in hd[:7]:
            w.i32(x)
        w.raw(hd[7])
    if v >= 35:
        w.i32(m.get('hd_water_envmap', 0))
    if v >= 38:
        w.raw(m.get('minimap_alpha_color', b'\0\0\0\xff'))
    hud = m.get('player_hud', v >= 39) if v >= 37 else False
    w.i32(len(m['players']))
    for p in m['players']:
        w.i32(p['number'])
        w.i32(p['type'])
        w.i32(p['race'])
        if hud:
            w.i32(p.get('hud', 0))
        w.i32(p['fixed_start'])
        w.s(p['name'])
        w.f32(p['x'])
        w.f32(p['y'])
        w.i32(p['ally_low'])
        w.i32(p['ally_high'])
        if v >= 31:
            w.i32(p.get('enemy_low', 0))
            w.i32(p.get('enemy_high', 0))
    w.i32(len(m['forces']))
    for f in m['forces']:
        w.i32(f['flags'])
        w.i32(f['mask'])
        w.s(f['name'])
    w.i32(len(m['upgrades']))
    for u in m['upgrades']:
        w.i32(u['players'])
        w.raw(u['id'])
        w.i32(u['level'])
        w.i32(u['avail'])
    w.i32(len(m['techs']))
    for t in m['techs']:
        w.i32(t['players'])
        w.raw(t['id'])
    w.i32(len(m['random_unit_groups']))
    for g in m['random_unit_groups']:
        w.i32(g['number'])
        w.s(g['name'])
        w.i32(len(g['types']))
        for t in g['types']:
            w.i32(t)
        w.i32(len(g['lines']))
        for chance, ids in g['lines']:
            w.i32(chance)
            for x in ids:
                w.raw(x)
    if v >= 25:
        w.i32(len(m.get('random_item_tables', [])))
        for t in m.get('random_item_tables', []):
            w.i32(t['number'])
            w.s(t['name'])
            w.i32(len(t['sets']))
            for items in t['sets']:
                w.i32(len(items))
                for chance, iid in items:
                    w.i32(chance)
                    w.raw(iid)
    if v in (26, 27):
        w.i32(m.get('legacy_script_language', 0))
    w.raw(m.get('_tail', b''))
    return w.bytes()

