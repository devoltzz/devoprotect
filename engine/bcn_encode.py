# Encodes an image as a DDS texture (DXT1 or DXT5) with every mipmap.
import io
import struct

import numpy as np


_W = np.array([1.0, 1.0, 1.0], dtype=np.float32)
_T4 = np.array([0.0, 1.0, 1.0 / 3.0, 2.0 / 3.0], dtype=np.float32)
_T3 = np.array([0.0, 1.0, 0.5], dtype=np.float32)


def _blocks(a):
    h, w, c = a.shape
    return a.reshape(h // 4, 4, w // 4, 4, c).transpose(0, 2, 1, 3, 4).reshape(-1, 16, c)


def _padded(a):
    h, w = a.shape[:2]
    ph, pw = (-h) % 4, (-w) % 4
    if ph or pw:
        a = np.pad(a, ((0, ph), (0, pw), (0, 0)), mode='edge')
    return a


def _q565(c):
    r = np.clip(np.rint(c[:, 0] * 31.0 / 255.0), 0, 31).astype(np.int32)
    g = np.clip(np.rint(c[:, 1] * 63.0 / 255.0), 0, 63).astype(np.int32)
    b = np.clip(np.rint(c[:, 2] * 31.0 / 255.0), 0, 31).astype(np.int32)
    v = (r << 11) | (g << 5) | b
    ex = np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], 1).astype(np.float32)
    return v, ex


def _axis(px, weight):
    total = weight.sum(1, keepdims=True)
    total = np.where(total > 0, total, 1.0)
    mean = (px * weight[..., None]).sum(1) / total
    d = (px - mean[:, None, :]) * np.sqrt(weight)[..., None]
    cov = np.einsum('nki,nkj->nij', d, d)
    v = cov[:, :, 1] + cov[:, :, 0] * 0.5 + cov[:, :, 2] * 0.25 + 1e-6
    for _ in range(8):
        v = np.einsum('nij,nj->ni', cov, v)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        v = v / np.where(n > 0, n, 1.0)
    return mean, v


_IDX4 = np.array([0, 2, 3, 1])
_IDX3 = np.array([0, 2, 1])


def _nearest(px, ex0, ex1, weight, steps):
    d = ex1 - ex0
    dd = (d * d).sum(1)
    t = ((px - ex0[:, None, :]) * d[:, None, :]).sum(2) / np.where(dd > 0, dd, 1.0)[:, None]
    k = np.clip(np.rint(t * steps), 0, steps).astype(np.int64)
    tq = k.astype(np.float32) / steps
    rec = ex0[:, None, :] + tq[..., None] * d[:, None, :]
    e = ((((px - rec) ** 2) * _W).sum(2) * weight).sum(1)
    return (_IDX4 if steps == 3 else _IDX3)[k], e


def _least_squares(px, weight, t_of_i):
    a = (1.0 - t_of_i) * weight
    b = t_of_i * weight
    aa = (a * (1.0 - t_of_i)).sum(1)
    bb = (b * t_of_i).sum(1)
    ab = (a * t_of_i).sum(1)
    ax = (a[..., None] * px).sum(1)
    bx = (b[..., None] * px).sum(1)
    detail = aa * bb - ab * ab
    ok = np.abs(detail) > 1e-6
    detail = np.where(ok, detail, 1.0)
    c0 = (ax * bb[:, None] - bx * ab[:, None]) / detail[:, None]
    c1 = (bx * aa[:, None] - ax * ab[:, None]) / detail[:, None]
    return np.clip(c0, 0, 255), np.clip(c1, 0, 255), ok


def _color(px, weight, three):
    mean, direction = _axis(px, weight)
    proj = ((px - mean[:, None, :]) * direction[:, None, :]).sum(2)
    hi_p = np.where(weight > 0, proj, -np.inf).max(1)
    lo_p = np.where(weight > 0, proj, np.inf).min(1)
    hi_p = np.where(np.isfinite(hi_p), hi_p, 0.0)
    lo_p = np.where(np.isfinite(lo_p), lo_p, 0.0)
    e0 = np.clip(mean + direction * hi_p[:, None], 0, 255)
    e1 = np.clip(mean + direction * lo_p[:, None], 0, 255)
    best = None
    any_three = bool(three.any())
    for rnd in range(3):
        v0, ex0 = _q565(e0)
        v1, ex1 = _q565(e1)
        i, err = _nearest(px, ex0, ex1, weight, 3)
        if any_three:
            i3, err3 = _nearest(px, ex0, ex1, weight, 2)
            i = np.where(three[:, None], i3, i)
            err = np.where(three, err3, err)
        if best is None:
            best = [v0, v1, i, err]
        else:
            better = err < best[3]
            for k, new in enumerate((v0, v1, i, err)):
                best[k] = np.where(better[:, None], new, best[k]) if new.ndim == 2 else np.where(better, new,
                                                                                                    best[k])
        if rnd == 2:
            break
        tt = np.where(three[:, None], _T3[np.minimum(i, 2)], _T4[i])
        c0, c1, ok = _least_squares(px, weight, tt)
        e0 = np.where(ok[:, None], c0, e0)
        e1 = np.where(ok[:, None], c1, e1)
    v0, v1, i, _err = best
    swap4 = (~three) & (v0 < v1)
    swap3 = three & (v0 > v1)
    swap = swap4 | swap3
    map4 = np.array([1, 0, 3, 2])
    map3 = np.array([1, 0, 2, 3])
    i = np.where(swap4[:, None], map4[i], np.where(swap3[:, None], map3[i], i))
    v0, v1 = np.where(swap, v1, v0), np.where(swap, v0, v1)
    same = (~three) & (v0 == v1)
    i = np.where(same[:, None], 0, i)
    i = np.where(three[:, None] & (weight == 0), 3, i)
    return v0, v1, i


def _color_bytes(v0, v1, i):
    bits = (i.astype(np.uint32) << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    out = np.zeros((v0.shape[0], 8), dtype=np.uint8)
    out[:, 0:2] = v0.astype('<u2').view(np.uint8).reshape(-1, 2)
    out[:, 2:4] = v1.astype('<u2').view(np.uint8).reshape(-1, 2)
    out[:, 4:8] = bits.astype('<u4').view(np.uint8).reshape(-1, 4)
    return out


def _alpha(al):
    a = al.astype(np.float32)
    hi, lo = a.max(1), a.min(1)
    pal8 = np.stack([hi, lo] + [((7 - k) * hi + k * lo) / 7.0 for k in range(1, 7)], 1)
    pal8 = np.rint(pal8)
    d8 = (a[:, :, None] - pal8[:, None, :]) ** 2
    i8 = d8.argmin(2)
    e8 = np.take_along_axis(d8, i8[..., None], 2)[..., 0].sum(1)
    mid = (a > 0) & (a < 255)
    lo6 = np.where(mid, a, 255.0).min(1)
    hi6 = np.where(mid, a, 0.0).max(1)
    no_mid = ~mid.any(1)
    lo6 = np.where(no_mid, 0.0, lo6)
    hi6 = np.where(no_mid, 255.0, hi6)
    pal6 = np.stack([lo6, hi6] + [((5 - k) * lo6 + k * hi6) / 5.0 for k in range(1, 5)] +
                    [np.zeros_like(lo6), np.full_like(lo6, 255.0)], 1)
    pal6 = np.rint(pal6)
    d6 = (a[:, :, None] - pal6[:, None, :]) ** 2
    i6 = d6.argmin(2)
    e6 = np.take_along_axis(d6, i6[..., None], 2)[..., 0].sum(1)
    use6 = e6 < e8
    a0 = np.where(use6, lo6, hi).astype(np.uint8)
    a1 = np.where(use6, hi6, lo).astype(np.uint8)
    i = np.where(use6[:, None], i6, i8).astype(np.uint64)
    i = np.where(((~use6) & (a0 == a1))[:, None], 0, i)
    return a0, a1, i, np.where(use6, e6, e8)


def _alpha_palette(a0, a1):
    x0, x1 = a0.astype(np.float32), a1.astype(np.float32)
    p8 = np.stack([x0, x1] + [((7 - k) * x0 + k * x1) / 7.0 for k in range(1, 7)], 1)
    p6 = np.stack([x0, x1] + [((5 - k) * x0 + k * x1) / 5.0 for k in range(1, 5)] +
                  [np.zeros_like(x0), np.full_like(x0, 255.0)], 1)
    return np.rint(np.where((a0 > a1)[:, None], p8, p6))


def _alpha_fit(a, a0, a1):
    words = _alpha_palette(a0, a1)
    d = (a[:, :, None] - words[:, None, :]) ** 2
    i = d.argmin(2)
    return i.astype(np.uint64), np.take_along_axis(d, i[..., None], 2)[..., 0].sum(1)


def _alpha_sse(a, a0, a1, i):
    words = _alpha_palette(a0, a1)
    return ((a - np.take_along_axis(words, i.astype(np.int64), 1)) ** 2).sum(1)


def _alpha_bytes(a0, a1, i):
    bits = (i.astype(np.uint64) << (3 * np.arange(16, dtype=np.uint64))).sum(1).astype(np.uint64)
    out = np.zeros((a0.shape[0], 8), dtype=np.uint8)
    out[:, 0] = a0
    out[:, 1] = a1
    out[:, 2:8] = bits.astype('<u8').view(np.uint8).reshape(-1, 8)[:, :6]
    return out


def _ex565(v):
    r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], 1).astype(np.float32)


def _color_sse(px, weight, v0, v1, i):
    ex0, ex1 = _ex565(v0), _ex565(v1)
    rec = ex0[:, None, :] + (ex1 - ex0)[:, None, :] * _T4[i][..., None]
    return ((((px - rec) ** 2) * _W).sum(2) * weight).sum(1)


RDO_REL = 0.5
RDO_ABS = 192.0
RDO_ALPHA_ABS = 64.0
RDO_NEIGHBOURS = ((1, 0), (0, 1), (2, 0), (-1, 1), (1, 1), (3, 0), (4, 0))


def _rdo(px, weight, al, v0, v1, i, err, wb, rdo, blocked, alpha=None):
    n = v0.shape[0]
    allowed = err * (1.0 + RDO_REL * rdo) + RDO_ABS * rdo
    if alpha is not None:
        a0, a1, ai, aerr = alpha
        a_allowed = aerr * (1.0 + RDO_REL * rdo) + RDO_ALPHA_ABS * rdo
    col = np.arange(n) % wb
    for _pass in range(2):
        for k, (dx, dy) in enumerate(RDO_NEIGHBOURS):
            shift = dx + dy * wb
            if shift <= 0 or shift >= n:
                continue
            src = np.arange(n) - shift
            ok = (src >= 0) & (col - dx >= 0) & (col - dx < wb)
            src = np.where(ok, src, 0)
            ok &= ~blocked & ~blocked[src]
            n0, n1, ni = v0[src], v1[src], i[src]
            if k < 2:
                full = ok & (_color_sse(px, weight, n0, n1, ni) <= allowed)
                ei, ee = _nearest(px, _ex565(n0), _ex565(n1), weight, 3)
                ends = ok & ~full & (ee <= allowed)
            else:
                full = ends = np.zeros(n, bool)
                ei = i
            same = v0 == v1
            idx = ok & ~full & ~ends & ~same & (_color_sse(px, weight, v0, v1, ni) <= allowed)
            v0 = np.where(full | ends, n0, v0)
            v1 = np.where(full | ends, n1, v1)
            i = np.where(full[:, None], ni, np.where(ends[:, None], ei, np.where(idx[:, None], ni, i)))
            if alpha is not None and k < 2:
                m0, m1, mi = a0[src], a1[src], ai[src]
                okk = (np.arange(n) - shift >= 0) & (col - dx >= 0) & (col - dx < wb)
                afull = okk & (_alpha_sse(al, m0, m1, mi) <= a_allowed)
                fi, fe = _alpha_fit(al, m0, m1)
                aends = okk & ~afull & (fe <= a_allowed)
                a0 = np.where(afull | aends, m0, a0)
                a1 = np.where(afull | aends, m1, a1)
                ai = np.where(afull[:, None], mi, np.where(aends[:, None], fi, ai))
    if alpha is not None:
        return v0, v1, i, (a0, a1, ai)
    return v0, v1, i, None


def _level(rgba, fmt, rdo=0.0):
    padded = _padded(rgba)
    wb = padded.shape[1] // 4
    b = _blocks(padded.astype(np.float32))
    px, al = b[:, :, :3], b[:, :, 3]
    if fmt == 'dxt1':
        transp = al < 128
        three_blk = transp.any(1)
        weight = np.where(transp, 0.0, 1.0).astype(np.float32)
        v0, v1, i = _color(px, weight, three_blk)
        if rdo > 0:
            err = np.where(three_blk, 0.0, _color_sse(px, weight, v0, v1, np.minimum(i, 3)))
            v0, v1, i, _a = _rdo(px, weight, al, v0, v1, i, err, wb, rdo, three_blk)
        return _color_bytes(v0, v1, i).tobytes()
    weight = np.ones(al.shape, np.float32)
    v0, v1, i = _color(px, weight, np.zeros(al.shape[0], bool))
    a0, a1, ai, aerr = _alpha(al)
    if rdo > 0:
        err = _color_sse(px, weight, v0, v1, i)
        v0, v1, i, (a0, a1, ai) = _rdo(px, weight, al, v0, v1, i, err, wb, rdo, np.zeros(al.shape[0], bool),
                                       alpha=[a0, a1, ai, aerr])
    return np.concatenate([_alpha_bytes(a0, a1, ai), _color_bytes(v0, v1, i)], 1).tobytes()


def format_of(rgba):
    a = rgba[:, :, 3]
    return 'dxt1' if bool(((a == 255) | (a == 0)).all()) else 'dxt5'


def mipmaps(rgba):
    out = [rgba]
    cur = rgba.astype(np.float32)
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        h, w = cur.shape[:2]
        if h > 1:
            cur = (cur[0::2] + cur[1::2]) * 0.5
        if w > 1:
            cur = (cur[:, 0::2] + cur[:, 1::2]) * 0.5
        out.append(np.clip(np.rint(cur), 0, 255).astype(np.uint8))
    return out


def header(w, h, levels, fmt, size0):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000
    caps = 0x1000 | (0x400000 | 0x8 if levels > 1 else 0)
    pf = struct.pack('<II4s5I', 32, 0x4, fmt.upper().encode(), 0, 0, 0, 0, 0)
    return b'DDS ' + struct.pack('<7I', 124, flags, h, w, size0, 0, levels) + b'\0' * 44 + pf + \
        struct.pack('<5I', caps, 0, 0, 0, 0)


def encode(im, fmt='auto', rdo=0.0):
    rgba = np.asarray(im.convert('RGBA'), dtype=np.uint8)
    h, w = rgba.shape[:2]
    if h % 4 or w % 4:
        raise ValueError('the side (%dx%d) is not a multiple of 4' % (w, h))
    if fmt == 'auto':
        fmt = format_of(rgba)
    levels = [_level(m, fmt, rdo) for m in mipmaps(rgba)]
    return header(w, h, len(levels), fmt, len(levels[0])) + b''.join(levels), fmt


def psnr(a, b, alpha=True):
    x = np.asarray(a.convert('RGBA'), dtype=np.float32)
    y = np.asarray(b.convert('RGBA'), dtype=np.float32)
    vis = ~((x[:, :, 3] == 0) & (y[:, :, 3] == 0))
    d = (x - y) ** 2
    d[:, :, :3] *= vis[..., None]
    d = d if alpha else d[:, :, :3]
    mse = float(d.mean())
    return float('inf') if mse == 0 else 10.0 * np.log10(255.0 * 255.0 / mse)


def decode(data):
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im.load()
    return im.convert('RGBA')

