# Reads the whole structure of an MDX model, versions 800 to 1800.
import re
import struct

import mdxcheck


TRACKS = {
    'KMTF': (1, 'i'), 'KMTA': (1, 'f'), 'KMTE': (1, 'f'), 'KFC3': (3, 'f'), 'KFCA': (1, 'f'), 'KFTC': (1, 'f'),
    'KTAT': (3, 'f'), 'KTAR': (4, 'f'), 'KTAS': (3, 'f'),
    'KGAO': (1, 'f'), 'KGAC': (3, 'f'),
    'KGTR': (3, 'f'), 'KGRT': (4, 'f'), 'KGSC': (3, 'f'),
    'KLAS': (1, 'f'), 'KLAE': (1, 'f'), 'KLAC': (3, 'f'), 'KLAI': (1, 'f'), 'KLBI': (1, 'f'), 'KLBC': (3, 'f'),
    'KLAV': (1, 'f'), 'KLSI': (1, 'f'),
    'KATV': (1, 'f'),
    'KPEE': (1, 'f'), 'KPEG': (1, 'f'), 'KPLN': (1, 'f'), 'KPLT': (1, 'f'), 'KPEL': (1, 'f'), 'KPES': (1, 'f'),
    'KPEV': (1, 'f'),
    'KP2E': (1, 'f'), 'KP2G': (1, 'f'), 'KP2L': (1, 'f'), 'KP2R': (1, 'f'), 'KP2N': (1, 'f'), 'KP2W': (1, 'f'),
    'KP2S': (1, 'f'), 'KP2V': (1, 'f'),
    'KPPA': (1, 'f'), 'KPPC': (3, 'f'), 'KPPE': (1, 'f'), 'KPPL': (1, 'f'), 'KPPS': (1, 'f'), 'KPPV': (1, 'f'),
    'KRHA': (1, 'f'), 'KRHB': (1, 'f'), 'KRAL': (1, 'f'), 'KRCO': (3, 'f'), 'KRTX': (1, 'i'), 'KRVS': (1, 'f'),
    'KCTR': (3, 'f'), 'KTTR': (3, 'f'), 'KCRL': (1, 'f'),
    'IDUF': (1, 'f'), 'ELAF': (1, 'f'), 'PTSF': (1, 'f'),
}
NODE_BONE = (b'BONE', b'HELP', b'EVTS', b'CLID')
NODE_AFTER = (b'LITE', b'ATCH', b'PREM', b'PRE2', b'RIBB', b'CORN')
NODE_SIZE = 96
HI_MASK = 0xFF000000
_TAGS_RX = re.compile(b'|'.join(t.encode() for t in sorted(TRACKS)))


class Track(object):
    __slots__ = ('tag', 'start', 'end', 'count', 'interp', 'gseq', 'words', 'kind', 'frames', 'owner', 'event')

    def __init__(self, tag, start, end, count, interp, gseq, words, kind, frames, owner, event=False):
        self.tag, self.start, self.end, self.count, self.interp, self.gseq = tag, start, end, count, interp, gseq
        self.words, self.kind, self.frames, self.owner, self.event = words, kind, frames, owner, event

    @property
    def stride(self):
        return 4 * (1 + self.words * (3 if self.interp > 1 else 1))

    @property
    def body(self):
        return self.start + (12 if self.event else 16)


class Model(object):
    def __init__(self, data):
        self.data = data
        self.version = None
        self.chunks = []
        self.seqs, self.glbs, self.texs, self.mats, self.geos = [], [], [], [], []
        self.nodes, self.cams, self.txan, self.geoa = [], [], [], []
        self.modl = None
        self.pivots = 0
        self.bind_poses = None
        self.tracks = []
        self.containers = []
        self.notes = []

    def note(self, text):
        if len(self.notes) < 40:
            self.notes.append(text)


def _u32(d, p):
    return struct.unpack_from('<I', d, p)[0]


def _cstr(b):
    i = b.find(b'\0')
    return (b if i < 0 else b[:i]).decode('latin-1')


def _chain(m, pos, end, owner, allowed=None, commit=True, dead=None):
    d = m.data
    out = []
    while pos + 16 <= end:
        if dead is not None and pos in dead:
            break
        tag = d[pos:pos + 4].decode('latin-1')
        info = TRACKS.get(tag)
        if info is None or (allowed is not None and tag not in allowed):
            break
        count, interp, gseq = struct.unpack_from('<IIi', d, pos + 4)
        if interp > 3:
            break
        words, kind = info
        stride = 4 * (1 + words * (3 if interp > 1 else 1))
        last = pos + 16 + count * stride
        if count > 0x1000000 or last > end:
            break
        frames = [struct.unpack_from('<i', d, pos + 16 + i * stride)[0] for i in range(count)]
        out.append(Track(tag, pos, last, count, interp, gseq, words, kind, frames, owner))
        pos = last
    if commit:
        m.tracks.extend(out)
    return pos, out


def _event_track(m, pos, end, owner):
    d = m.data
    if pos + 12 > end or d[pos:pos + 4] != b'KEVT':
        return pos
    count, gseq = struct.unpack_from('<Ii', d, pos + 4)
    last = pos + 12 + 4 * count
    if last > end:
        return pos
    frames = list(struct.unpack_from('<%di' % count, d, pos + 12))
    m.tracks.append(Track('KEVT', pos, last, count, 0, gseq, 0, 'i', frames, owner, event=True))
    return last


def _tail_tracks(m, lo, end, owner, allowed=None, candidates=()):
    if lo >= end:
        return True
    d = m.data
    if _TAGS_RX.search(d, lo, end) is None:
        return True
    import itertools
    dead = set()
    for off in itertools.chain(candidates, range(0, end - lo - 15)):
        p = lo + off
        if p + 16 > end or p in dead:
            continue
        stop, got = _chain(m, p, end, owner, allowed, commit=False, dead=dead)
        if stop == end and got:
            m.tracks.extend(got)
            return True
        dead.add(p)
        dead.update(t.start for t in got)
    return False


def _node(m, kind, pos):
    d = m.data
    size = _u32(d, pos)
    node = {'kind': kind, 'off': pos, 'end': pos + size, 'name': _cstr(d[pos + 4:pos + 84]),
            'id': _u32(d, pos + 84), 'parent': struct.unpack_from('<i', d, pos + 88)[0], 'flags': _u32(d, pos + 92),
            'tracks': []}
    m.containers.append((pos, pos, pos + size, 0))
    owner = '%s "%s"' % (kind.decode(), node['name'])
    node['owner'] = owner
    n0 = len(m.tracks)
    stop, _got = _chain(m, pos + NODE_SIZE, pos + size, owner)
    if stop != pos + size:
        m.note('%s: the node tracks do not close (%d bytes left)' % (owner, pos + size - stop))
    node['tracks'] = m.tracks[n0:]
    return node


def _read_nodes(m, tag, size, off):
    d = m.data
    end = off + size
    q = off
    while q + 4 <= end:
        if tag in NODE_BONE:
            ns = _u32(d, q)
            if ns < NODE_SIZE or q + ns > end:
                m.note('%s: a node of %d bytes' % (tag.decode(), ns))
                return
            node = _node(m, tag, q)
            q += ns
            if tag == b'BONE':
                node['geoset'], node['geoset_anim'] = struct.unpack_from('<ii', d, q) if q + 8 <= end else (-1, -1)
                q += 8
            elif tag == b'EVTS':
                if d[q:q + 4] == b'KEVT':
                    q = _event_track(m, q, end, node['owner'])
            elif tag == b'CLID':
                kind = _u32(d, q) if q + 4 <= end else 99
                extra = {0: 24, 1: 24, 2: 16, 3: 28}.get(kind)
                if extra is None:
                    m.note('a collision shape of type %d' % kind)
                    return
                q += 4 + extra
        else:
            total = _u32(d, q)
            if total < 4 + NODE_SIZE or q + total > end:
                m.note('%s: an entry of %d bytes' % (tag.decode(), total))
                return
            m.containers.append((q, q, q + total, 0))
            node = _node(m, tag, q + 4)
            node['entry_end'] = q + total
            first = node['end']
            owner = node['owner']
            if tag == b'ATCH':
                node['path'] = _cstr(d[first:first + 260])
                _tail_tracks(m, first + 264, q + total, owner, allowed={'KATV'})
            elif tag == b'LITE':
                node['type'] = _u32(d, first) if first + 4 <= q + total else None
                if not _tail_tracks(m, first, q + total, owner, allowed={t for t in TRACKS if t[:2] == 'KL'},
                                    candidates=(44, 48, 72)):
                    m.note('%s: the light tracks do not close' % owner)
            elif tag == b'PRE2':
                _pre2_fields(m, node, first, q + total)
                if not _tail_tracks(m, first, q + total, owner, allowed={t for t in TRACKS if t[:3] == 'KP2'},
                                    candidates=(171,)):
                    m.note('%s: the emitter tracks do not close' % owner)
            elif tag == b'RIBB':
                if first + 52 <= q + total:
                    node['material'] = _u32(d, first + 44)
                    node['height_above'], node['height_below'] = struct.unpack_from('<2f', d, first)
                if not _tail_tracks(m, first, q + total, owner, allowed={t for t in TRACKS if t[:2] == 'KR'},
                                    candidates=(52,)):
                    m.note('%s: the ribbon tracks do not close' % owner)
            elif tag == b'CORN':
                if not _tail_tracks(m, first, q + total, owner, allowed={t for t in TRACKS if t[:3] == 'KPP'},
                                    candidates=(552,)):
                    m.note('%s: the popcorn tracks do not close' % owner)
            elif tag == b'PREM':
                if not _tail_tracks(m, first, q + total, owner,
                                    allowed={'KPEE', 'KPEG', 'KPLN', 'KPLT', 'KPEL', 'KPES', 'KPEV'}):
                    m.note('%s: the emitter tracks do not close' % owner)
            q += total
        m.nodes.append(node)
    if q != end:
        m.note('%s: the chunk does not close on its entries' % tag.decode())


def _pre2_fields(m, node, first, end):
    d = m.data
    if first + 171 > end:
        return
    vals = struct.unpack_from('<8f', d, first)
    filt, rows, cols, head = struct.unpack_from('<4I', d, first + 32)
    node.update(speed=vals[0], latitude=vals[2], filter=filt, rows=rows, cols=cols)
    node['time_middle'] = struct.unpack_from('<f', d, first + 52)[0]
    node['texture'], node['squirt'], node['priority'], node['replaceable'] = struct.unpack_from('<IIiI', d, first + 155)
    node['xyquad'] = bool(node['flags'] & 0x100000)


def _read_cams(m, size, off):
    d = m.data
    end = off + size
    q = off
    while q + 4 <= end:
        raw = _u32(d, q)
        ent = raw & ~HI_MASK
        if ent < 120 or q + ent > end:
            m.note('CAMS: a camera of %d bytes' % ent)
            return
        m.containers.append((q, q, q + ent, HI_MASK))
        cam = {'off': q, 'end': q + ent, 'hi': raw & HI_MASK, 'name': _cstr(d[q + 4:q + 84]),
               'values': struct.unpack_from('<9f', d, q + 84)}
        owner = 'CAMS "%s"' % cam['name']
        if not _tail_tracks(m, q + 120, q + ent, owner, candidates=(0,)):
            m.note('%s: the camera tracks do not close' % owner)
        m.cams.append(cam)
        q += ent


def _layer_fixed(version, d, q):
    if version < 900:
        return 28
    if version < 1000:
        return 32
    if version < 1100:
        return 52
    n = _u32(d, q + 56)
    return 60 + 8 * n


def _read_mtls(m, size, off):
    d = m.data
    end = off + size
    p = off
    while p + 4 <= end:
        inc = _u32(d, p)
        if inc < 20 or p + inc > end:
            m.note('MTLS: a material of %d bytes' % inc)
            return
        m.containers.append((p, p, p + inc, 0))
        mat = {'off': p, 'end': p + inc, 'priority': struct.unpack_from('<i', d, p + 4)[0], 'flags': _u32(d, p + 8),
               'shader': '', 'layers': []}
        q = p + 12
        if d[q:q + 4] != b'LAYS' and q + 84 <= p + inc and d[q + 80:q + 84] == b'LAYS':
            mat['shader'] = _cstr(d[q:q + 80])
            q += 80
        elif d[q:q + 4] != b'LAYS':
            m.note('MTLS: material %d has no LAYS' % len(m.mats))
            m.mats.append(mat)
            p += inc
            continue
        nlay = _u32(d, q + 4)
        q += 8
        for k in range(nlay):
            if q + 28 > p + inc:
                m.note('MTLS: layer %d of material %d past the material' % (k, len(m.mats)))
                break
            linc = _u32(d, q)
            if linc < 28 or q + linc > p + inc:
                m.note('MTLS: a layer of %d bytes' % linc)
                break
            m.containers.append((q, q, q + linc, 0))
            filt, shade, tex, texanim, coord = struct.unpack_from('<IIiiI', d, q + 4)
            alpha = struct.unpack_from('<f', d, q + 24)[0]
            lay = {'off': q, 'end': q + linc, 'filter': filt, 'shading': shade, 'texture': tex, 'texanim': texanim,
                   'coord': coord, 'alpha': alpha, 'tracks': [], 'slots': []}
            if m.version >= 1100 and linc >= 64 and 60 + 8 * _u32(d, q + 56) <= linc:
                lay['slots'] = [struct.unpack_from('<II', d, q + 60 + 8 * j) for j in range(_u32(d, q + 56))]
            owner = 'material %d layer %d' % (len(m.mats), k)
            allowed = {'KMTF', 'KMTA', 'KMTE', 'KFC3', 'KFCA', 'KFTC'}
            n0 = len(m.tracks)
            if lay['slots']:
                pos = q + 60
                for _j in lay['slots']:
                    pos += 8
                    if d[pos:pos + 4] == b'KMTF':
                        pos, _got = _chain(m, pos, q + linc, owner, allowed={'KMTF'})
                if _chain(m, pos, q + linc, owner, allowed=allowed)[0] != q + linc:
                    m.note('%s: the layer tracks do not close (version %s)' % (owner, m.version))
            else:
                fixed = _layer_fixed(m.version, d, q) if m.version < 1100 or linc >= 64 else 28
                if not _tail_tracks(m, q + fixed, q + linc, owner, allowed=allowed, candidates=(0,)) and \
                        not _tail_tracks(m, q + 28, q + linc, owner, allowed=allowed):
                    m.note('%s: the layer tracks do not close (version %s)' % (owner, m.version))
            lay['tracks'] = m.tracks[n0:]
            mat['layers'].append(lay)
            q += linc
        m.mats.append(mat)
        p += inc


GEO_PARTS = (
    (b'VRTX', 12),
    (b'NRMS', 12),
    (b'PTYP', 4),
    (b'PCNT', 4),
    (b'PVTX', 2),
    (b'GNDX', 1),
    (b'MTGC', 4),
    (b'MATS', 4),
)


def _read_geos(m, size, off):
    d = m.data
    end = off + size
    p = off
    while p + 8 <= end:
        inc = _u32(d, p)
        if inc < 12 or p + inc > end:
            m.note('GEOS: a geoset of %d bytes' % inc)
            return
        m.containers.append((p, p, p + inc, 0))
        g = {'off': p, 'end': p + inc, 'parts': {}, 'skin': None, 'tang': None, 'uvas': None}
        q = p + 4
        ok = True
        for tag, width in GEO_PARTS:
            if q + 8 > p + inc or d[q:q + 4] != tag:
                ok = False
                break
            cnt = _u32(d, q + 4)
            g['parts'][tag.decode()] = (cnt, q + 8)
            q += 8 + cnt * width
        if not ok or q + 12 > p + inc:
            m.note('GEOS: geoset %d does not parse (%s)' % (len(m.geos), 'a part is missing' if not ok else 'it ends'))
            m.geos.append(g)
            p += inc
            continue
        g['mats_end'] = q
        g['material'], g['group'], g['flags'] = struct.unpack_from('<III', d, q)
        placed = False
        for lod in ((True, False) if m.version >= 900 else (False, True)):
            r = _geo_tail(m, g, q + 12, p + inc, lod)
            if r:
                placed = True
                break
        if not placed:
            m.note('GEOS: geoset %d: the tail (extents, SKIN, UVAS) does not parse' % len(m.geos))
        m.geos.append(g)
        p += inc


def _geo_tail(m, g, q, end, lod):
    d = m.data
    lod_at = q
    if lod:
        q += 84
    if q + 32 > end:
        return False
    bounds = struct.unpack_from('<7f', d, q)
    nex = _u32(d, q + 28)
    ext_at = q + 32
    q = ext_at + nex * 28
    if q > end:
        return False
    skin = tang = None
    while q + 8 <= end and d[q:q + 4] in (b'TANG', b'SKIN'):
        cnt = _u32(d, q + 4)
        if d[q:q + 4] == b'TANG':
            tang = (cnt, q + 8)
            q += 8 + cnt * 16
        else:
            w = None
            for width in (1, 2):
                nxt = q + 8 + cnt * width
                if nxt + 8 <= end and d[nxt:nxt + 4] in (b'UVAS', b'TANG', b'SKIN'):
                    w = width
                    break
            if w is None:
                return False
            skin = (cnt, q + 8, w)
            q += 8 + cnt * w
    if d[q:q + 4] != b'UVAS' or q + 8 > end:
        return False
    nsets = _u32(d, q + 4)
    r = q + 8
    for _i in range(nsets):
        if r + 8 > end or d[r:r + 4] != b'UVBS':
            return False
        r += 8 + _u32(d, r + 4) * 8
    if r != end:
        return False
    g.update(lod=lod, lod_at=lod_at, bounds=bounds, seq_extents=(nex, ext_at), skin=skin, tang=tang,
             uvas=(nsets, q + 8), tail_at=q)
    return True


def _read_simple_tracks(m, size, off, what):
    d = m.data
    end = off + size
    q = off
    while q + 4 <= end:
        inc = _u32(d, q)
        if inc < 8 or q + inc > end:
            m.note('%s: an entry of %d bytes' % (what, inc))
            return
        m.containers.append((q, q, q + inc, 0))
        entry = {'off': q, 'end': q + inc}
        owner = '%s %d' % (what, len(m.geoa if what == 'GEOA' else m.txan))
        if what == 'GEOA':
            if inc < 28:
                m.note('GEOA: an entry of %d bytes' % inc)
                return
            entry['alpha'] = struct.unpack_from('<f', d, q + 4)[0]
            entry['geoset'] = struct.unpack_from('<i', d, q + 24)[0]
            if not _tail_tracks(m, q + 28, q + inc, owner, allowed={'KGAO', 'KGAC'}):
                m.note('%s: the tracks do not close' % owner)
            m.geoa.append(entry)
        else:
            if not _tail_tracks(m, q + 4, q + inc, owner, allowed={'KTAT', 'KTAR', 'KTAS'}):
                m.note('%s: the tracks do not close' % owner)
            m.txan.append(entry)
        q += inc


def read(data):
    data = bytes(data)
    chunks, err = mdxcheck.walk(data)
    if err:
        raise ValueError(err)
    m = Model(data)
    m.chunks = chunks
    for tag, size, off in chunks:
        if tag == b'VERS' and size >= 4:
            m.version = _u32(data, off)
            break
    if m.version is None:
        raise ValueError('no VERS chunk')
    for tag, size, off in chunks:
        m.containers.append((off - 4, off, off + size, 0))
    for tag, size, off in chunks:
        try:
            if tag == b'MODL' and size >= 372:
                m.modl = {'name': _cstr(data[off:off + 80]), 'anim_file': _cstr(data[off + 80:off + 340]),
                          'bounds': struct.unpack_from('<7f', data, off + 340), 'off': off}
            elif tag == b'SEQS':
                for i in range(size // 132):
                    p = off + i * 132
                    s, e = struct.unpack_from('<II', data, p + 80)
                    m.seqs.append({'name': _cstr(data[p:p + 80]), 'start': s, 'end': e, 'bounds':
                                   struct.unpack_from('<7f', data, p + 104), 'off': p})
                if size % 132:
                    m.note('SEQS: %d bytes left over' % (size % 132))
            elif tag == b'GLBS':
                m.glbs = list(struct.unpack_from('<%dI' % (size // 4), data, off))
            elif tag == b'TEXS':
                for i in range(size // 268):
                    p = off + i * 268
                    m.texs.append({'replaceable': _u32(data, p), 'path': _cstr(data[p + 4:p + 264]),
                                   'flags': _u32(data, p + 264)})
            elif tag == b'MTLS':
                _read_mtls(m, size, off)
            elif tag == b'GEOS':
                _read_geos(m, size, off)
            elif tag == b'GEOA':
                _read_simple_tracks(m, size, off, 'GEOA')
            elif tag == b'TXAN':
                _read_simple_tracks(m, size, off, 'TXAN')
            elif tag == b'CAMS':
                _read_cams(m, size, off)
            elif tag in NODE_BONE or tag in NODE_AFTER:
                _read_nodes(m, tag, size, off)
            elif tag == b'PIVT':
                m.pivots = size // 12
            elif tag == b'BPOS' and size >= 4:
                m.bind_poses = _u32(data, off)
        except (struct.error, IndexError, ValueError) as e:
            m.note('%s: %s' % (tag.decode('latin-1'), e))
    return m


def edit(data, model, edits):
    buf = bytearray(data)
    deltas = []
    for a, b, new in sorted(edits, key=lambda e: (e[0], e[1])):
        deltas.append((a, b, len(new) - (b - a)))
    for i in range(len(deltas) - 1):
        if deltas[i][1] > deltas[i + 1][0]:
            raise ValueError('overlapping edits')
    for pos, lo, hi, keep in model.containers:
        change = 0
        for a, b, dl in deltas:
            if dl and lo <= a and b <= hi and (a < b or lo < a <= hi):
                change += dl
        if change:
            raw = struct.unpack_from('<I', buf, pos)[0]
            new = ((raw & ~keep & 0xFFFFFFFF) + change) | (raw & keep) if keep else raw + change
            struct.pack_into('<I', buf, pos, new)
    for a, b, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        buf[a:b] = new
    return bytes(buf)
