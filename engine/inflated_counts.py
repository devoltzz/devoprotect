# Finds and fixes inflated record counters in the files only the World Editor reads.
import re
import struct



class End(Exception):
    pass


class FormatError(Exception):
    pass


_I32 = struct.Struct('<i').unpack_from
_U32 = struct.Struct('<I').unpack_from
_F32 = struct.Struct('<f').unpack_from


class Reader(object):
    __slots__ = ('b', 'o')

    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def remaining(self):
        return len(self.b) - self.o

    def _require(self, n):
        if n < 0:
            raise End('negative length (%d)' % n)
        if self.remaining() < n:
            raise End('%d B missing' % (n - self.remaining()))

    def i32(self):
        o = self.o
        if len(self.b) - o < 4:
            self._require(4)
        v = _I32(self.b, o)[0]
        self.o = o + 4
        return v

    def u32(self):
        o = self.o
        if len(self.b) - o < 4:
            self._require(4)
        v = _U32(self.b, o)[0]
        self.o = o + 4
        return v

    def f32(self):
        o = self.o
        if len(self.b) - o < 4:
            self._require(4)
        v = _F32(self.b, o)[0]
        self.o = o + 4
        return v

    def f32s(self, n):
        o = self.o
        if len(self.b) - o >= 4 * n:
            v = list(struct.unpack_from('<%df' % n, self.b, o))
            self.o = o + 4 * n
            return v
        return [self.f32() for _ in range(n)]

    def bs(self, n):
        o = self.o
        if n < 0 or len(self.b) - o < n:
            self._require(n)
        v = self.b[o:o + n]
        self.o = o + n
        return v

    def s(self, ceiling=4096):
        e = self.b.find(b'\x00', self.o)
        if e < 0 or e - self.o > ceiling:
            raise End('string without NUL (or longer than %d B)' % ceiling)
        v = self.b[self.o:e]
        self.o = e + 1
        return v


def _res(regs, declared, r, minimum, head_line, count_pos, **extra):
    d = {
        'regs': regs,
        'declared': declared,
        'remaining': r.remaining(),
        'end_pos': r.o,
        'minimum': minimum,
        'head_line': head_line,
        'count_pos': count_pos,
        'available': len(r.b) - head_line,
    }
    d.update(extra)
    return d


def min_w3r(v):
    n = 16 + 1
    n += 4 if v >= 1 else 0
    n += 4 if v >= 3 else 0
    n += 1 if v >= 4 else 0
    n += 4 if v >= 5 else 0
    n += 8 if v >= 7 else 0
    return n


def read_region(r, v):
    reg = {}
    if v >= 2:
        reg['rect'] = r.f32s(4)
    else:
        reg['rect'] = [float(r.i32()) for _ in range(4)]
    reg['fname'] = r.s()
    if v >= 1:
        reg['creation'] = r.i32()
    if v >= 3:
        reg['weather'] = r.bs(4)
    if v >= 4:
        reg['sound'] = r.s()
    if v >= 5:
        reg['color'] = r.bs(4)
    if v >= 7:
        r.i32()
        r.i32()
    return reg


def read_w3r(b):
    r = Reader(b, 8)
    v, n = struct.unpack_from('<II', b, 0)
    regs = []
    for _ in range(min(n, 1 << 20)):
        try:
            regs.append(read_region(r, v))
        except End:
            break
    return _res(regs, n, r, min_w3r(v), 8, 4, version_num=v)


RX_BLOCKER = re.compile(r'\bAddCameraBlocker\s*\(\s*(\w+)\s*\)')


def min_w3c(v, new_ones=True, dof=None):
    if dof is None:
        return min(min_w3c(v, new_ones, True), min_w3c(v, new_ones, False))
    n = 10 * 4 + 1
    n += 12 if new_ones else 0
    n += (12 + 4) if (dof and v >= 3) else 0
    return n


def read_camera(r, v, new_ones, dof=True):
    k = 10 + (3 if new_ones else 0) + (3 if (dof and v >= 3) else 0)
    if r.remaining() >= 4 * k:
        f = r.f32s(k)
        cpath = {'tgt': f[0:2], 'z': f[2], 'rotation': f[3], 'angle': f[4], 'target_distance': f[5], 'roll': f[6],
                 'fov': f[7], 'far': f[8], 'near': f[9]}
        if new_ones:
            cpath['local'] = f[10:13]
        if dof and v >= 3:
            cpath['dof'] = f[k - 3:k]
    else:
        cpath = {'tgt': [r.f32() for _ in range(2)], 'z': r.f32(), 'rotation': r.f32(), 'angle': r.f32(),
                 'target_distance': r.f32(), 'roll': r.f32(), 'fov': r.f32(), 'far': r.f32(), 'near': r.f32()}
        if new_ones:
            cpath['local'] = [r.f32() for _ in range(3)]
        if dof and v >= 3:
            cpath['dof'] = [r.f32() for _ in range(3)]
    cpath['fname'] = r.s()
    if dof and v >= 3:
        cpath['type_name'] = r.i32()
    return cpath


def read_w3c(b):
    v, n = struct.unpack_from('<II', b, 0)
    best = None
    for new_ones in (False, True):
        for dof in (False, True):
            if dof and v < 3:
                continue
            r = Reader(b, 8)
            regs = []
            for _ in range(min(n, 1 << 20)):
                try:
                    regs.append(read_camera(r, v, new_ones, dof))
                except End:
                    break
            cand = _res(regs, n, r, min_w3c(v, new_ones, dof), 8, 4, version_num=v, layout=(new_ones, dof))
            if r.remaining() == 0 and len(regs) == n:
                return cand
            if best is None or (0 <= cand['remaining'] < best['remaining']):
                best = cand
    return best


def _min_sound(v):
    n = 3 + 17 * 4
    n += (8 + 11) if v > 1 else 0
    n += 5 if v > 2 else 0
    return n


SOUND_CAP = 1 << 20


def read_sound(r, v):
    sound = {'fname': r.s(SOUND_CAP), 'file_path': r.s(SOUND_CAP), 'eax': r.s(SOUND_CAP), 'flags': r.i32()}
    for _c in range(3):
        r.i32()
    r.f32()
    r.f32()
    r.i32()
    r.i32()
    for _c in range(3):
        r.f32()
    for _c in range(2):
        r.f32()
    r.i32()
    for _c in range(3):
        r.f32()
    if v > 1:
        r.s(SOUND_CAP)
        r.s(SOUND_CAP)
        r.s(SOUND_CAP)
        r.i32()
        r.s(SOUND_CAP)
        r.i32()
        r.s(SOUND_CAP)
        r.bs(3)
        r.s(SOUND_CAP)
        r.s(SOUND_CAP)
        r.s(SOUND_CAP)
        r.s(SOUND_CAP)
    if v > 2:
        r.bs(1)
        r.i32()
    return sound


def read_w3s_records(b):
    r = Reader(b, 8)
    v, n = struct.unpack_from('<II', b, 0)
    sounds = []
    for _ in range(min(n, 1 << 20)):
        try:
            sounds.append(read_sound(r, v))
        except End:
            break
    return _res(sounds, n, r, _min_sound(v), 8, 4, version_num=v)


def read_imp(b):
    r = Reader(b, 8)
    v, n = struct.unpack_from('<II', b, 0)
    item_entries = []
    for _ in range(min(n, 1 << 20)):
        try:
            item_entries.append({'type_name': r.bs(1)[0], 'file_path': r.s()})
        except End:
            break
    return _res(item_entries, n, r, 2, 8, 4, version_num=v)


def read_mmp(b):
    r = Reader(b, 8)
    v, n = struct.unpack_from('<II', b, 0)
    icons = []
    for _ in range(min(n, 1 << 20)):
        try:
            icons.append({'type_name': r.i32(), 'x': r.i32(), 'y': r.i32(), 'color': r.bs(4)})
        except End:
            break
    return _res(icons, n, r, 16, 8, 4, version_num=v)


def read_wct(b):
    if len(b) < 4:
        raise FormatError('too short')
    r = Reader(b, 0)
    ver = r.u32()
    if ver == 0:
        declared = r.i32()
        head_line, count_pos = 8, 4
    elif ver == 1:
        r.s()
        sz = r.i32()
        if sz:
            r.bs(sz)
        declared = r.i32()
        head_line, count_pos = r.o, r.o - 4
    elif ver & 0x80000000:
        if ver not in (0x80000001, 0x80000004):
            raise FormatError('unknown subversion 0x%08X' % ver)
        if r.u32() != 1:
            raise FormatError('subversion without version 1')
        r.s()
        sz = r.i32()
        if sz:
            r.bs(sz)
        head_line, count_pos = r.o, None
        trigger_list = []
        while r.remaining() > 0 and len(trigger_list) < 1 << 20:
            t = r.i32()
            if t:
                r.bs(t)
            trigger_list.append(t)
        return _res(trigger_list, len(trigger_list), r, 4, head_line, count_pos, version_num=1, subversion=ver)
    else:
        raise FormatError('unknown version %d' % ver)
    trigger_list = []
    for _ in range(min(declared, 1 << 20)):
        try:
            t = r.i32()
            if t:
                r.bs(t)
        except End:
            break
        trigger_list.append(t)
    return _res(trigger_list, declared, r, 4, head_line, count_pos, version_num=ver)


def load_wtg(b):
    if b[:4] != b'WTG!':
        raise FormatError('missing WTG!')
    r = Reader(b, 4)
    ver = r.u32()
    if ver & 0x80000000:
        if ver not in (0x80000001, 0x80000004):
            raise FormatError('unknown new format 0x%08X' % ver)
        ver = r.u32()
        for _c in range(4):
            r.u32()
        minimum = 17
    elif ver in (3, 4, 6, 7):
        minimum = 9
    else:
        raise FormatError('unknown version %d' % ver)
    n = r.u32()
    return _res([], n, r, minimum, r.o, r.o - 4, version_num=ver, no_records=True)


UNITS_LAYOUTS = ((7, 9), (8, 9), (8, 11), (12, 9), (12, 11), (13, 9), (13, 11))


def units_layout_flags(ver, sub):
    if (ver, sub) not in UNITS_LAYOUTS:
        raise FormatError('unknown version %d/%d' % (ver, sub))
    return sub >= 11, ver >= 12


def _units_minimum(ver, sub, skin):
    if (ver, sub) == (7, 9):
        return 91
    if (ver, sub) not in UNITS_LAYOUTS or (ver, sub) == (8, 11):
        return 115 if skin else 111
    modern, cluster = units_layout_flags(ver, sub)
    return 91 + (4 if skin else 0) + (16 if modern else 0) + (16 if cluster else 0)


def read_units_record(b, p, ver, sub, skin=False):
    modern, cluster = units_layout_flags(ver, sub)
    if (ver, sub) == (7, 9):
        skin = False
    o = p + 36 + (4 if skin else 0) + (4 if cluster else 0)
    if o + 7 > len(b):
        raise End('ended in the record header (byte %d)' % p)
    d = {'p': p, 'ident': b[p:p + 4], 'skin': skin, 'modern': modern, 'flags': b[o],
         'owner': struct.unpack_from('<h', b, o + 1)[0]}
    d['variation'] = struct.unpack_from('<i', b, p + 4)[0]
    d['xyz'] = struct.unpack_from('<3f', b, p + 8)
    d['angle'] = struct.unpack_from('<f', b, p + 20)[0]
    d['skin_id'] = b[p + 36:p + 40] if skin else None
    d['id_positions'] = [(p, 'type_name')] + ([(p + 36, 'skin')] if skin else [])
    d['cluster'] = struct.unpack_from('<i', b, o - 4)[0] if cluster else None
    d['uprooted'] = struct.unpack_from('<i', b, o + 3)[0]
    o += 7
    if o + 8 > len(b):
        raise End('ended before the hp (byte %d)' % p)
    d['hp'], d['mana'] = struct.unpack_from('<2i', b, o)
    o += 8
    d['itp'] = -1
    if modern:
        d['itp'] = struct.unpack_from('<i', b, o)[0] if o + 4 <= len(b) else -1
        o += 4
    if o + 4 > len(b):
        raise End('ended before the item sets (byte %d)' % p)
    d['item_sets'] = struct.unpack_from('<i', b, o)[0]
    if not 0 <= d['item_sets'] <= 32:
        raise End('item sets %d' % d['item_sets'])
    o += 4
    item_entries, d['set_items'] = 0, []
    for _k in range(d['item_sets']):
        if o + 4 > len(b):
            raise End('ended in an item set (byte %d)' % p)
        k = struct.unpack_from('<i', b, o)[0]
        if not 0 <= k <= 64:
            raise End('set with %d items' % k)
        if o + 4 + 8 * k > len(b):
            raise End('ended in an item set (byte %d)' % p)
        d['set_items'].append([(b[o + 4 + 8 * j:o + 8 + 8 * j], struct.unpack_from('<i', b, o + 8 + 8 * j)[0])
                               for j in range(k)])
        d['id_positions'].extend((o + 4 + 8 * j, 'dropped item') for j in range(k))
        item_entries += k
        o += 4 + 8 * k
    d['item_entries'] = item_entries
    if o + 12 > len(b):
        raise End('ended before the gold (byte %d)' % p)
    d['gold'] = struct.unpack_from('<i', b, o)[0]
    d['acq'] = struct.unpack_from('<f', b, o + 4)[0]
    d['level'] = struct.unpack_from('<i', b, o + 8)[0]
    o += 12
    d['hero_attributes'] = None
    if modern:
        d['hero_attributes'] = struct.unpack_from('<3i', b, o) if o + 12 <= len(b) else None
        o += 12
    if o + 4 > len(b):
        raise End('ended before the inventory (byte %d)' % p)
    d['inv'] = struct.unpack_from('<i', b, o)[0]
    if not 0 <= d['inv'] <= 64:
        raise End('inventory with %d items' % d['inv'])
    if o + 4 + 8 * d['inv'] > len(b):
        raise End('ended before the abilities (byte %d)' % p)
    d['inventory'] = [(struct.unpack_from('<i', b, o + 4 + 8 * j)[0], b[o + 8 + 8 * j:o + 12 + 8 * j])
                      for j in range(d['inv'])]
    d['id_positions'].extend((o + 8 + 8 * j, 'inventory') for j in range(d['inv']))
    o += 4 + 8 * d['inv']
    if o + 4 > len(b):
        raise End('ended before the abilities (byte %d)' % p)
    d['habs'] = struct.unpack_from('<i', b, o)[0]
    if not 0 <= d['habs'] <= 64:
        raise End('unit with %d abilities' % d['habs'])
    if o + 4 + 12 * d['habs'] > len(b):
        raise End('ended before is_random (byte %d)' % p)
    d['abilities'] = [(b[o + 4 + 12 * j:o + 8 + 12 * j],) + struct.unpack_from('<2i', b, o + 8 + 12 * j)
                      for j in range(d['habs'])]
    d['id_positions'].extend((o + 4 + 12 * j, 'ability') for j in range(d['habs']))
    o += 4 + 12 * d['habs']
    if o + 4 > len(b):
        raise End('ended before is_random (byte %d)' % p)
    d['rnd'] = struct.unpack_from('<i', b, o)[0]
    o += 4
    d['block_entry'] = None
    if d['rnd'] == 0:
        if o + 4 > len(b):
            raise End('ended in the random table (byte %d)' % p)
        d['block_entry'] = (int.from_bytes(b[o:o + 3], 'little'), b[o + 3])
        o += 4
    elif d['rnd'] == 1:
        if o + 8 > len(b):
            raise End('ended in the random table (byte %d)' % p)
        d['block_entry'] = struct.unpack_from('<2i', b, o)
        o += 8
    elif d['rnd'] == 2:
        if o + 4 > len(b):
            raise End('ended in the random table (byte %d)' % p)
        k = struct.unpack_from('<i', b, o)[0]
        if not 0 <= k <= 256:
            raise End('random table of %d' % k)
        if o + 4 + 8 * k > len(b):
            raise End('ended in the random table (byte %d)' % p)
        d['block_entry'] = [(b[o + 4 + 8 * j:o + 8 + 8 * j], struct.unpack_from('<i', b, o + 8 + 8 * j)[0])
                            for j in range(k)]
        d['id_positions'].extend((o + 4 + 8 * j, 'random_creep') for j in range(k))
        o += 4 + 8 * k
    elif d['rnd'] != -1:
        raise End('is_random %d' % d['rnd'])
    if o + 12 > len(b):
        raise End('ended before the end of the record (byte %d)' % p)
    d['color'], d['waygate'], d['creation'] = struct.unpack_from('<3i', b, o)
    o += 12
    d['roll_angle'] = d['pitch'] = None
    d['lights'] = 0
    if cluster:
        if o + 12 > len(b):
            raise End('ended before the end of the record (byte %d)' % p)
        d['roll_angle'], d['pitch'], d['lights'] = struct.unpack_from('<ffi', b, o)
        if not 0 <= d['lights'] <= 64:
            raise End('record with %d lights' % d['lights'])
        o += 12 + 36 * d['lights']
        if o > len(b):
            raise End('ended before the end of the record (byte %d)' % p)
    d['sz'] = o - p
    return d


def load_units_doo(b):
    if b[:4] != b'W3do':
        raise FormatError('missing W3do')
    ver, sub = struct.unpack_from('<ii', b, 4)
    n = struct.unpack_from('<I', b, 12)[0]
    if (ver, sub) == (7, 9):
        skins = (False,)
    elif (ver, sub) == (8, 11):
        skins = (False, True)
    else:
        skins = (True, False)
    best = None
    for skin in skins:
        regs, o, err = [], 16, None
        for _i in range(n):
            try:
                d = read_units_record(b, o, ver, sub, skin)
            except (End, struct.error) as e:
                err = e
                break
            regs.append(d)
            o += d['sz']
        on_close = err is None and o == len(b)
        if on_close:
            return _res(
                regs,
                n,
                Reader(b, o),
                _units_minimum(ver, sub, skin),
                16,
                12,
                version_num=(ver, sub),
                on_close=True,
                layout='%d/%d%s' % (ver, sub, '+skin' if skin else ''),
                skin=skin,
            )
        if best is None or len(regs) > len(best[0]):
            best = (regs, o, skin)
    if (ver, sub) == (8, 9) and _units_from_old_writer(b):
        raise FormatError('the 8/9 an old writer wrote (item counts of -1)')
    regs, o, skin = best
    return _res(regs, n, Reader(b, o), _units_minimum(ver, sub, skin), 16, 12, version_num=(ver, sub), on_close=False,
                layout='%d/%d%s' % (ver, sub, '+skin' if skin else ''), skin=skin)


_READERS = {'war3map.w3r': read_w3r, 'war3map.w3c': read_w3c, 'war3map.w3s': read_w3s_records, 'war3map.imp': read_imp,
            'war3map.mmp': read_mmp, 'war3map.wct': read_wct, 'war3map.wtg': load_wtg,
            'war3mapUnits.doo': load_units_doo}


def _units_from_old_writer(b):
    if len(b) < 16 + 59 or b[:4] != b'W3do' or struct.unpack_from('<ii', b, 4) != (8, 9):
        return False
    return -1 in (struct.unpack_from('<i', b, 16 + 51)[0], struct.unpack_from('<i', b, 16 + 55)[0])


def _num(t):
    s = (t or '').strip().replace(' ', '')
    if s.startswith('+'):
        s = s[1:]
    return float(s)


RX_LITERAL_HEX = re.compile(r'"(?:[^"\\]|\\.)*"|//[^\n]*|\'[^\'\n]*\'|(?<![\w.$])(?:\$|0[xX])([0-9A-Fa-f]+)\b')
_ID_LETTERS = frozenset(b'0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')


def flat_literals(body_text):
    if '$' not in body_text and '0x' not in body_text and '0X' not in body_text:
        return body_text

    def swap(m):
        if m.group(1) is None:
            return m.group(0)
        v = int(m.group(1), 16)
        b = (v & 0xFFFFFFFF).to_bytes(4, 'big')
        if v > 0xFFFFFF and all(c in _ID_LETTERS for c in b):
            return "'%s'" % b.decode('ascii')
        return str(v)

    return RX_LITERAL_HEX.sub(swap, body_text)


def _var_name(fname, prefix=''):
    if prefix and fname.startswith(prefix):
        fname = fname[len(prefix):]
    return fname.replace('_', ' ')


RX_RECT = re.compile(r'gg_rct_([A-Za-z0-9_]+)\s*=\s*Rect\(\s*([^)]*)\)')
RX_RECT_JASS = re.compile(r'set\s+gg_rct_([A-Za-z0-9_]+)\s*=\s*Rect\(\s*([^)]*)\)')
RX_WEATHER = re.compile(r'AddWeatherEffect\(\s*gg_rct_([A-Za-z0-9_]+)\s*,\s*'
                        r'(?:FourCC\(\s*[\'"](.{1,4})[\'"]\s*\)|\'(.{1,4})\')')
RX_SOUND_POS = re.compile(r'SetSoundPosition\(\s*(gg_snd_[A-Za-z0-9_]+)\s*,\s*'
                          r'([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)')
RX_STACKED_SOUND = re.compile(r'RegisterStackedSound\(\s*(gg_snd_[A-Za-z0-9_]+)\s*,\s*\w+\s*,\s*'
                              r'([-+0-9.eE]+)\s*,\s*([-+0-9.eE]+)')


RX_SIMPLE_CALL = re.compile(r'(?m)^[ \t]*call[ \t]+(\w+)[ \t]*\([ \t]*\)[ \t]*(?://.*)?\r?$')
RX_INITBLIZZARD = re.compile(r'\bInitBlizzard[ \t]*\(')
CREATION = (('regions', ('Rect(',)), ('cameras', ('CreateCameraSetup(',)),
            ('units', ('CreateUnit(', 'BlzCreateUnitWithSkin(')), ('item_entries', ('CreateItem(',)),
            ('destructables', ('CreateDestructable', 'BlzCreateDestructable', 'CreateDeadDestructable')))


def _bodies_by_name(body_text):
    marks = _function_marks(body_text)
    out = {}
    for k, (begin, fname) in enumerate(marks):
        end_pos = marks[k + 1][0] if k + 1 < len(marks) else len(body_text)
        out.setdefault(fname, body_text[begin:end_pos])
    return out


def creation_skeleton(body_text):
    if not body_text:
        return {}
    bodies = _bodies_by_name(body_text)
    main = bodies.get('main')
    if not main or not RX_INITBLIZZARD.search(main):
        return {}
    before = main[:RX_INITBLIZZARD.search(main).start()]
    out = {}
    for root in RX_SIMPLE_CALL.findall(before):
        if root not in bodies:
            continue
        closure, work_queue = [], [root]
        while work_queue:
            n = work_queue.pop(0)
            if n in closure or n not in bodies:
                continue
            closure.append(n)
            work_queue += RX_SIMPLE_CALL.findall(bodies[n])
        segment = ''.join(bodies[n] for n in closure)
        for role, marks in CREATION:
            if any(m in segment for m in marks):
                out.setdefault(role, []).extend(n for n in closure if n not in out.get(role, []))
    return out


def _bodies_of_role(body_text, role):
    name_list = creation_skeleton(body_text).get(role)
    if not name_list:
        return ''
    bodies = _bodies_by_name(body_text)
    return ''.join(bodies[n] for n in name_list if n in bodies)


RX_ANY_RECT = re.compile(r'set\s+(\w+)\s*=\s*Rect\(\s*([^)]*)\)')
RX_ANY_WEATHER = re.compile(r'AddWeatherEffect\(\s*(\w+)\s*,\s*(?:FourCC\(\s*[\'"](.{1,4})[\'"]\s*\)|\'(.{1,4})\')')


def script_regions(body_text):
    if not body_text:
        return []
    body_text = flat_literals(body_text)
    hits, order = {}, []
    for rx in (RX_RECT_JASS, RX_RECT):
        for m in rx.finditer(body_text):
            fname = m.group(1)
            if fname in hits:
                continue
            nums = []
            for p in m.group(2).split(','):
                try:
                    nums.append(_num(p))
                except ValueError:
                    nums = []
                    break
            if len(nums) != 4:
                continue
            hits[fname] = {'rect': nums, 'fname': _var_name(fname), 'creation': len(order),
                           'weather': b'\x00' * 4, 'sound': b'', 'color': bytes((0xFF, 0x80, 0x80, 0xFF)),
                           'var': 'gg_rct_' + fname}
            order.append(fname)
    rx_weather = RX_WEATHER
    if not order:
        body_text = _bodies_of_role(body_text, 'regions')
        rx_weather = RX_ANY_WEATHER
        for m in RX_ANY_RECT.finditer(body_text):
            fname = m.group(1)
            if fname in hits:
                continue
            nums = []
            for p in m.group(2).split(','):
                try:
                    nums.append(_num(p))
                except ValueError:
                    nums = []
                    break
            if len(nums) != 4:
                continue
            hits[fname] = {'rect': nums, 'fname': 'Region %03d' % (len(order) + 1), 'creation': len(order),
                           'weather': b'\x00' * 4, 'sound': b'', 'color': bytes((0xFF, 0x80, 0x80, 0xFF)), 'var': fname}
            order.append(fname)
    if not order:
        return []
    for m in rx_weather.finditer(body_text):
        if m.group(1) in hits:
            hits[m.group(1)]['weather'] = (m.group(2) or m.group(3) or '').encode('latin-1')[:4].ljust(4, b'\x00')
    for m in RX_SOUND_POS.finditer(body_text):
        try:
            x, y = _num(m.group(2)), _num(m.group(3))
        except ValueError:
            continue
        for reg in hits.values():
            r = reg['rect']
            if abs((r[0] + r[2]) / 2.0 - x) < 0.5 and abs((r[1] + r[3]) / 2.0 - y) < 0.5:
                reg['sound'] = m.group(1).encode('latin-1')
                break
    for m in RX_STACKED_SOUND.finditer(body_text):
        try:
            width, height = _num(m.group(2)), _num(m.group(3))
        except ValueError:
            continue
        for reg in hits.values():
            r = reg['rect']
            if abs((r[2] - r[0]) - width) < 0.5 and abs((r[3] - r[1]) - height) < 0.5:
                reg['sound'] = m.group(1).encode('latin-1')
                break
    for m in RX_BLOCKER.finditer(body_text):
        for reg in hits.values():
            if reg.get('var') == m.group(1):
                reg['block_reason'] = True
    return [hits[n] for n in order]


RX_ANY_FUNCTION = re.compile(r'function\s+([A-Za-z_]\w*)\b\s*[\(t]')


def _function_marks(body_text, chosen=None):
    out = []
    for m in RX_ANY_FUNCTION.finditer(body_text):
        j = m.start() - 1
        while j >= 0 and body_text[j] in ' \t':
            j -= 1
        if j >= 0 and body_text[j] not in ';\r\n':
            continue
        if chosen is None or m.group(1) in chosen:
            out.append((m.start(), m.group(1)))
    return out

