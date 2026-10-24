# Rewrites JPEG BLP textures with optimal Huffman tables, losing nothing.
import io
import os
import struct
from array import array


SOF_NOT_BASELINE = {0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
VERSION = 'blp_huffman/2'


class _LeBits:
    __slots__ = ('d', 'p', 'acc', 'n')

    def __init__(self, d, p):
        self.d = d
        self.p = p
        self.acc = 0
        self.n = 0

    def bits(self, k):
        while self.n < k:
            d = self.d
            b = d[self.p]
            if b == 0xFF:
                if d[self.p + 1] == 0x00:
                    self.p += 2
                else:
                    raise ValueError('JPEG: marker %02X inside the entropy data' % d[self.p + 1])
            else:
                self.p += 1
            self.acc = ((self.acc << 8) | b) & 0xFFFFFFFFFFFF
            self.n += 8
        self.n -= k
        return (self.acc >> self.n) & ((1 << k) - 1)

    def alinha(self):
        self.n = 0
        self.acc = 0


def _tab_decod(counts, syms):
    code = 0
    k = 0
    maxcode = [-1] * 18
    valptr = [0] * 17
    mincode = [0] * 17
    for L in range(1, 17):
        n = counts[L - 1]
        if n:
            valptr[L] = k
            mincode[L] = code
            code += n
            k += n
            maxcode[L] = code - 1
        code <<= 1
    return maxcode, valptr, mincode, syms


def _decod(lb, t):
    maxcode, valptr, mincode, syms = t
    code = lb.bits(1)
    L = 1
    while code > maxcode[L]:
        code = (code << 1) | lb.bits(1)
        L += 1
        if L > 16:
            raise ValueError('codigo Huffman invalido')
    return syms[valptr[L] + code - mincode[L]]


def _segmentos(d):
    if d[:2] != b'\xff\xd8':
        raise ValueError('no SOI')
    segs = [(0xD8, 0, 2)]
    p = 2
    while True:
        while d[p] == 0xFF and d[p + 1] == 0xFF:
            p += 1
        if d[p] != 0xFF:
            raise ValueError('marcador esperado em %d' % p)
        mk = d[p + 1]
        L = struct.unpack_from('>H', d, p + 2)[0]
        segs.append((mk, p, p + 2 + L))
        p += 2 + L
        if mk == 0xDA:
            return segs, p


def _dht_tables(seg):
    q = 0
    while q < len(seg):
        tc, th = seg[q] >> 4, seg[q] & 15
        counts = list(seg[q + 1:q + 17])
        n = sum(counts)
        yield (tc, th), counts, list(seg[q + 17:q + 17 + n]), seg[q:q + 17 + n]
        q += 17 + n


_NATIVE_SOUND = [None]


def _native_sound():
    if _NATIVE_SOUND[0] is None:
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            import mpqcrypt
            _NATIVE_SOUND[0] = mpqcrypt.load_jpeg() or False
        except Exception:
            _NATIVE_SOUND[0] = False
    return _NATIVE_SOUND[0]


class _HuffAnalysis(dict):
    def __missing__(self, k):
        if k != 'seq':
            raise KeyError(k)
        keys, recs = self['nat']
        seq = []
        ap = seq.append
        for x in recs:
            if x & 0x80000000:
                ap(None)
                continue
            key = keys[(x >> 24) & 0x7F]
            s = (x >> 16) & 0xFF
            ap((key, s, x & 0xFFFF, s & 15 if key[0] else s))
        self['seq'] = seq
        return seq


def _analyze_native(scan, d, segs, ent, nmcu, dri, block_list, raw_data):
    keys, idx, spec = [], {}, bytearray()
    for (_cid, td, ta), nb in block_list:
        for key in ((0, td), (1, ta)):
            if key not in raw_data:
                return None
            if key not in idx:
                idx[key] = len(keys)
                keys.append(key)
        if nb > 255:
            return None
        spec += bytes((idx[(0, td)], idx[(1, ta)], nb))
    if len(keys) > 64:
        return None
    tabs = bytearray()
    for key in keys:
        counts, syms = raw_data[key]
        tabs += bytes(counts) + struct.pack('<H', len(syms)) + bytes(syms)
    head = 2 + 256 * len(keys)
    rst = nmcu // dri if dri else 0
    out = None
    for factor in (3, 8):
        out = scan(d, ent, nmcu, dri, bytes(spec), bytes(tabs), head + factor * max(0, len(d) - ent) + rst + 64)
        if out is not None:
            break
    if out is None:
        return None
    end_pos, nrec = out[0], out[1]
    freq = {}
    for i, key in enumerate(keys):
        c = out[2 + 256 * i:2 + 256 * (i + 1)]
        fr = dict((s, n) for s, n in enumerate(c) if n)
        if fr:
            freq[key] = fr
    q = end_pos
    while q + 1 < len(d) and d[q] == 0xFF and d[q + 1] == 0xFF:
        q += 1
    if d[q:q + 2] != b'\xff\xd9':
        return False
    return _HuffAnalysis(d=d, segs=segs, nat=(keys, out[head:head + nrec]), freq=freq, end_ent=end_pos)


def _native_entropy(write, a, code_part):
    keys, recs = a['nat']
    codes = array('I', bytes(1024 * len(keys)))
    for i, key in enumerate(keys):
        for s, (c, L) in (code_part.get(key) or {}).items():
            if not (0 <= s < 256 and 1 <= L <= 16 and 0 <= c < (1 << L)):
                return None
            codes[256 * i + s] = (L << 16) | c
    return write(recs, codes, bytes(k[0] for k in keys), len(keys), 8 * len(recs) + 16)


def _entropy(seq, code_part):
    out = bytearray()
    acc = 0
    n = 0
    rst = 0
    for x in seq:
        if x is None:
            if n:
                k = 8 - n
                b = ((acc << k) | ((1 << k) - 1)) & 0xFF
                out.append(b)
                if b == 0xFF:
                    out.append(0)
                acc = 0
                n = 0
            out += bytes([0xFF, 0xD0 + rst])
            rst = (rst + 1) & 7
            continue
        key, s, extra, nb = x
        c, L = code_part[key][s]
        acc = (acc << L) | c
        n += L
        if nb:
            acc = (acc << nb) | extra
            n += nb
        while n >= 8:
            n -= 8
            b = (acc >> n) & 0xFF
            out.append(b)
            if b == 0xFF:
                out.append(0)
        acc &= (1 << n) - 1
    if n:
        k = 8 - n
        b = ((acc << k) | ((1 << k) - 1)) & 0xFF
        out.append(b)
        if b == 0xFF:
            out.append(0)
    return out


def analyze(d):
    d = bytes(d)
    segs, ent = _segmentos(d)
    dht = {}
    raw_data = {}
    comps = {}
    dri = 0
    sof = None
    for mk, a, b in segs:
        seg = d[a + 4:b]
        if mk in SOF_NOT_BASELINE:
            return None
        if mk == 0xC0:
            prec, hh, ww, nc = struct.unpack_from('>BHHB', seg, 0)
            if prec != 8:
                return None
            sof = (hh, ww)
            for i in range(nc):
                cid, hv, _tq = seg[6 + 3 * i:9 + 3 * i]
                comps[cid] = (hv >> 4, hv & 15)
        elif mk == 0xC4:
            for key, counts, syms, _ in _dht_tables(seg):
                dht[key] = _tab_decod(counts, syms)
                raw_data[key] = (counts, syms)
        elif mk == 0xDD:
            dri = struct.unpack_from('>H', seg, 0)[0]
    mk, a, b = segs[-1]
    sos = d[a + 4:b]
    ns = sos[0]
    if sof is None or sos[1 + 2 * ns:4 + 2 * ns] != b'\x00\x3f\x00':
        return None
    scan = [(sos[1 + 2 * i], sos[2 + 2 * i] >> 4, sos[2 + 2 * i] & 15) for i in range(ns)]
    hh, ww = sof
    hmax = max(x[0] for x in comps.values())
    vmax = max(x[1] for x in comps.values())
    if ns == 1:
        h, v = comps[scan[0][0]]
        cw = (ww * h + hmax - 1) // hmax
        ch = (hh * v + vmax - 1) // vmax
        nmcu = ((cw + 7) // 8) * ((ch + 7) // 8)
        block_list = [(scan[0], 1)]
    else:
        nmcu = ((ww + 8 * hmax - 1) // (8 * hmax)) * ((hh + 8 * vmax - 1) // (8 * vmax))
        block_list = [(sc, comps[sc[0]][0] * comps[sc[0]][1]) for sc in scan]
    if nmcu * max(1, sum(n for _sc, n in block_list)) > 8 * max(1, len(d) - ent):
        return None
    nat = _NATIVE_SOUND[0] if _NATIVE_SOUND[0] is not None else _native_sound()
    if nat:
        r = _analyze_native(nat[0], d, segs, ent, nmcu, dri, block_list, raw_data)
        if r is not None:
            return r or None
    lb = _LeBits(d, ent)
    seq = []
    ap = seq.append
    for mcu in range(nmcu):
        if dri and mcu and mcu % dri == 0:
            lb.alinha()
            if d[lb.p] != 0xFF or not (0xD0 <= d[lb.p + 1] <= 0xD7):
                raise ValueError('RST esperado')
            lb.p += 2
            ap(None)
        for (_cid, td, ta), nb in block_list:
            tdc = dht[(0, td)]
            tac = dht[(1, ta)]
            kdc = (0, td)
            kac = (1, ta)
            for _ in range(nb):
                s = _decod(lb, tdc)
                ap((kdc, s, lb.bits(s) if s else 0, s))
                k = 1
                while k < 64:
                    rs = _decod(lb, tac)
                    s = rs & 15
                    ap((kac, rs, lb.bits(s) if s else 0, s))
                    if s == 0:
                        if rs == 0xF0:
                            k += 16
                            continue
                        break
                    k += (rs >> 4) + 1
                if k > 64:
                    raise ValueError('too many coefficients in the block')
    lb.alinha()
    q = lb.p
    while q + 1 < len(d) and d[q] == 0xFF and d[q + 1] == 0xFF:
        q += 1
    if d[q:q + 2] != b'\xff\xd9':
        return None
    return {'d': d, 'segs': segs, 'seq': seq, 'end_ent': lb.p}


def frequencias(analises):
    freq = {}
    for a in analises:
        if 'nat' in a:
            for key, fr in a['freq'].items():
                f = freq.setdefault(key, {})
                for s, n in fr.items():
                    f[s] = f.get(s, 0) + n
            continue
        for x in a['seq']:
            if x is None:
                continue
            fr = freq.setdefault(x[0], {})
            fr[x[1]] = fr.get(x[1], 0) + 1
    return freq


def _otima(freq):
    f = [0] * 257
    for s, n in freq.items():
        f[s] = n
    f[256] = 1
    codesize = [0] * 257
    others = [-1] * 257
    live = [i for i in range(257) if f[i]]
    while True:
        c1 = -1
        v = 1 << 62
        for i in live:
            if f[i] <= v:
                v = f[i]
                c1 = i
        c2 = -1
        v = 1 << 62
        for i in live:
            if f[i] <= v and i != c1:
                v = f[i]
                c2 = i
        if c2 < 0:
            break
        f[c1] += f[c2]
        f[c2] = 0
        live.remove(c2)
        codesize[c1] += 1
        while others[c1] >= 0:
            c1 = others[c1]
            codesize[c1] += 1
        others[c1] = c2
        codesize[c2] += 1
        while others[c2] >= 0:
            c2 = others[c2]
            codesize[c2] += 1
    bits = [0] * 33
    for i in range(257):
        if codesize[i]:
            bits[codesize[i]] += 1
    for i in range(32, 16, -1):
        while bits[i] > 0:
            j = i - 2
            while bits[j] == 0:
                j -= 1
            bits[i] -= 2
            bits[i - 1] += 1
            bits[j + 1] += 2
            bits[j] -= 1
    i = 16
    while bits[i] == 0:
        i -= 1
    bits[i] -= 1
    huffval = [s for L in range(1, 33) for s in range(256) if codesize[s] == L]
    return bits[1:17], huffval


def optimal_tables(freq):
    return {k: _otima(v) for k, v in freq.items()}


def _codes(bits, huffval):
    tab = {}
    code = 0
    k = 0
    for L in range(1, 17):
        for _ in range(bits[L - 1]):
            tab[huffval[k]] = (code, L)
            k += 1
            code += 1
        code <<= 1
    return tab


def rewrite(a, tables):
    d, segs = a['d'], a['segs']
    code_part = {k: _codes(*v) for k, v in tables.items()}
    out = None
    if 'nat' in a:
        nat = _NATIVE_SOUND[0] if _NATIVE_SOUND[0] is not None else _native_sound()
        if nat:
            out = _native_entropy(nat[1], a, code_part)
    if out is None:
        out = _entropy(a['seq'], code_part)
    block_body = bytearray()
    for mk, p, q in segs:
        if mk == 0xC4:
            for key, _, _, raw_data in _dht_tables(d[p + 4:q]):
                if key not in tables:
                    block_body += raw_data
    for key in sorted(tables):
        bits, huffval = tables[key]
        block_body += bytes([key[0] << 4 | key[1]]) + bytes(bits) + bytes(huffval)
    res = bytearray()
    existing = False
    for mk, p, q in segs:
        if mk == 0xC4:
            if not existing:
                res += b'\xff\xc4' + struct.pack('>H', len(block_body) + 2) + block_body
                existing = True
            continue
        res += d[p:q]
    res += out
    res += d[a['end_ent']:]
    return bytes(res)


def same_pixels(j1, j2):
    from PIL import Image
    a = Image.open(io.BytesIO(j1))
    b = Image.open(io.BytesIO(j2))
    return a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()


def mipmaps_jpeg(c):
    mo = struct.unpack_from('<16I', c, 28)
    ms = struct.unpack_from('<16I', c, 92)
    hsz = struct.unpack_from('<I', c, 156)[0]
    return [c[160:160 + hsz] + c[o:o + s] for o, s in zip(mo, ms) if o and s]


def same_texture(a, b):
    if a == b:
        return True
    if not (a and b and a[:8] == b'BLP1\x00\x00\x00\x00' == b[:8] and a[8:28] == b[8:28]):
        return False
    ma, mb = mipmaps_jpeg(a), mipmaps_jpeg(b)
    return len(ma) == len(mb) and all(same_pixels(x, y) for x, y in zip(ma, mb))


def otimiza_blp(c, proof=True):
    c = bytes(c)
    if len(c) < 160 or c[:4] != b'BLP1' or struct.unpack_from('<I', c, 4)[0] != 0:
        return None, 'not a BLP1 JPEG'
    mo = list(struct.unpack_from('<16I', c, 28))
    ms = list(struct.unpack_from('<16I', c, 92))
    hsz = struct.unpack_from('<I', c, 156)[0]
    hdr = c[160:160 + hsz]
    ent = sorted(set((o, s) for o, s in zip(mo, ms) if o and s))
    if not ent:
        return None, 'no mipmap'
    pos = 160 + hsz
    joined = False
    for o, s in ent:
        if o < pos:
            return None, 'mipmaps overlap'
        if o + s > len(c):
            return None, 'a mipmap goes past the end'
        joined = joined or o != pos
        pos = o + s
    joined = joined or pos != len(c)
    jpegs = {e: hdr + c[e[0]:e[0] + e[1]] for e in ent}
    try:
        an = {e: analyze(j) for e, j in jpegs.items()}
    except Exception as ex:
        return None, 'decoding: %s: %s' % (type(ex).__name__, ex)
    if any(a is None for a in an.values()):
        return None, 'not baseline'
    in_header = [q <= hsz for a in an.values() for mk, p, q in a['segs'] if mk == 0xC4]
    if not in_header:
        return None, 'no DHT'
    if all(in_header):
        tab = optimal_tables(frequencias(an.values()))
        new_ones = {e: rewrite(a, tab) for e, a in an.items()}
        old = sum(q - p for mk, p, q in next(iter(an.values()))['segs'] if mk == 0xC4)
        first = next(iter(new_ones.values()))
        new = sum(q - p for mk, p, q in _segmentos(first)[0] if mk == 0xC4)
        nhsz = hsz + new - old
        method = 'joint table'
    elif not any(in_header):
        new_ones = {e: rewrite(a, optimal_tables(frequencias([a]))) for e, a in an.items()}
        nhsz = hsz
        method = 'table per mipmap'
    else:
        return None, 'DHT parte no cabecalho, parte no mipmap'
    nhdr = next(iter(new_ones.values()))[:nhsz]
    if any(nj[:nhsz] != nhdr for nj in new_ones.values()):
        return None, 'the header is no longer a common one'
    if proof:
        for e in ent:
            try:
                identical = same_pixels(jpegs[e], new_ones[e])
            except Exception as ex:
                return None, 'pixel proof: %s: %s' % (type(ex).__name__, ex)
            if not identical:
                return None, 'PIXEL DIFFERENT (not written)'
    out = bytearray(c[:156]) + struct.pack('<I', nhsz) + nhdr
    new_pos = {}
    for e in ent:
        block_body = new_ones[e][nhsz:]
        new_pos[e] = (len(out), len(block_body))
        out += block_body
    nmo, nms = [], []
    for o, s in zip(mo, ms):
        no, ns = new_pos[(o, s)] if (o and s) else (o, s)
        nmo.append(no)
        nms.append(ns)
    struct.pack_into('<16I', out, 28, *nmo)
    struct.pack_into('<16I', out, 92, *nms)
    if len(out) >= len(c):
        return None, 'did not get smaller'
    return bytes(out), 'ok, ' + method + (', mipmaps joined' if joined else '')

