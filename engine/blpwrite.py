# Writes BLP1 textures, JPEG or paletted.
import io
import struct

from PIL import Image, ImageChops
from PIL.JpegImagePlugin import zigzag_index



QTABLE = [
    40,
    28,
    25,
    40,
    60,
    100,
    128,
    153,
    30,
    30,
    35,
    48,
    65,
    145,
    150,
    138,
    35,
    33,
    40,
    60,
    100,
    143,
    173,
    140,
    35,
    43,
    55,
    73,
    128,
    218,
    200,
    155,
    45,
    55,
    93,
    140,
    170,
    255,
    255,
    193,
    60,
    88,
    138,
    160,
    203,
    255,
    255,
    230,
    123,
    160,
    195,
    218,
    255,
    255,
    255,
    253,
    180,
    230,
    238,
    245,
    255,
    250,
    255,
    248,
]


LUMA_K = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
          14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
          49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
QTABLE_HIGH = [max(1, (v * 20 + 50) // 100) for v in LUMA_K]


def qtable_of_bytes(d):
    hs = struct.unpack_from('<I', d, 156)[0]
    offs = struct.unpack_from('<16I', d, 28)
    sizes = struct.unpack_from('<16I', d, 92)
    jpg = d[160:160 + hs] + d[offs[0]:offs[0] + sizes[0]]
    p = 2
    while p + 4 <= len(jpg) and jpg[p] == 0xFF:
        m = jpg[p + 1]
        txt_ln = struct.unpack('>H', jpg[p + 2:p + 4])[0]
        if m == 0xDB and p + 5 + 64 <= len(jpg) and not (jpg[p + 4] >> 4):
            raw = jpg[p + 5:p + 5 + 64]
            return [raw[i] for i in zigzag_index]
        if m == 0xDA:
            break
        p += 2 + txt_ln
    return None


def _scaled_table(scale, base=None):
    return [max(1, min(255, int(round(v * scale)))) for v in (QTABLE if base is None else base)]


def _patch_component_ids(data):
    out = bytearray(data)
    p = 2
    while p + 4 <= len(out):
        if out[p] != 0xFF:
            break
        m = out[p + 1]
        txt_ln = struct.unpack('>H', bytes(out[p + 2:p + 4]))[0]
        if m == 0xC0:
            n = out[p + 9]
            for i in range(n):
                out[p + 10 + i * 3] = i
        elif m == 0xDA:
            n = out[p + 4]
            for i in range(n):
                out[p + 5 + i * 2] = i
            break
        p += 2 + txt_ln
    return bytes(out)


def _jpeg_bgra(im, quality, base=None):
    r, g, b, a = im.split()
    cmyk = Image.merge('CMYK', tuple(ImageChops.invert(c) for c in (b, g, r, a)))
    buf = io.BytesIO()
    cmyk.save(buf, 'JPEG', qtables=[_scaled_table(quality / 100.0, base)] * 4, subsampling=0)
    data = _patch_component_ids(buf.getvalue())
    out = bytearray(data[:2])
    p = 2
    while p + 4 <= len(data):
        if data[p] != 0xFF:
            out += data[p:]
            break
        marker = data[p + 1]
        if marker == 0xDA:
            out += data[p:]
            break
        seglen = struct.unpack('>H', data[p + 2:p + 4])[0]
        seg = data[p:p + 2 + seglen]
        if not (marker == 0xEE and seg[4:9] == b'Adobe'):
            out += seg
        p += 2 + seglen
    return bytes(out)


def blp_jpeg_bytes(im, quality=90, alpha_bits=None, mipmaps=True, extra=None, qtable=None):
    im = im.convert('RGBA')
    w, h = im.size
    if alpha_bits is None:
        alpha_bits = 8 if im.getextrema()[3][0] < 255 else 0
    if alpha_bits == 0:
        r, g, b, a = im.split()
        im = Image.merge('RGBA', (r, g, b, Image.new('L', im.size, 255)))
    levels = []
    cur = im
    while True:
        levels.append(_jpeg_bgra(cur, quality if not levels else int(quality * 1.3), qtable))
        if not mipmaps or (cur.width == 1 and cur.height == 1) or len(levels) == 16:
            break
        cur = cur.resize((max(1, cur.width // 2), max(1, cur.height // 2)), Image.LANCZOS)
    header_size = 156 + 4
    offs = []
    sizes = []
    pos = header_size
    for lv in levels:
        offs.append(pos)
        sizes.append(len(lv))
        pos += len(lv)
    offs += [0] * (16 - len(offs))
    sizes += [0] * (16 - len(sizes))
    hdr = b'BLP1' + struct.pack('<IIIIII', 0, alpha_bits, w, h, 4 if extra is None else extra, 1 if mipmaps else 0)
    hdr += struct.pack('<16I', *offs) + struct.pack('<16I', *sizes) + struct.pack('<I', 0)
    return len(levels), hdr + b''.join(levels)


def save_blp(im, path, quality=90, alpha_bits=None, mipmaps=True, extra=None):
    n, data_bytes = blp_jpeg_bytes(im, quality, alpha_bits, mipmaps, extra)
    with open(path, 'wb') as f:
        f.write(data_bytes)
    return n, len(data_bytes)


def blp_palette_bytes(im, alpha_bits=None, mipmaps=True, extra=5, given_palette=None):
    import numpy as np
    im = im.convert('RGBA')
    w, h = im.size
    px = np.asarray(im, dtype=np.uint8)
    if alpha_bits is None:
        alpha_bits = 8 if int(px[..., 3].min()) < 255 else 0
    if alpha_bits not in (0, 8):
        raise ValueError('alpha_bits %r: the paletted writer here writes 0 or 8' % alpha_bits)
    colors = hash_key = None
    if given_palette is not None:
        pal = np.frombuffer(given_palette, np.uint8, 1024).reshape(256, 4).copy()
    else:
        hash_key = (px[..., 0].astype(np.uint32) << 16) | (px[..., 1].astype(np.uint32) << 8) | px[..., 2]
        colors = np.unique(hash_key)
        if len(colors) > 256:
            return None
        pal = np.zeros((256, 4), np.uint8)
        pal[:len(colors), 0] = colors & 0xFF
        pal[:len(colors), 1] = (colors >> 8) & 0xFF
        pal[:len(colors), 2] = (colors >> 16) & 0xFF
        pal[len(colors):, :3] = pal[0, :3]
        pal[:, 3] = 255
    rgb_pal = np.ascontiguousarray(pal[:, [2, 1, 0]])
    im_pal = Image.new('P', (1, 1))
    im_pal.putpalette(rgb_pal.reshape(-1).tolist())
    level_list = []
    cur = im
    while True:
        if not level_list and colors is not None:
            idx = np.searchsorted(colors, hash_key).astype(np.uint8)
            alfa = px[..., 3]
        else:
            q = cur.convert('RGB').quantize(palette=im_pal, dither=Image.Dither.NONE)
            idx = np.asarray(q, dtype=np.uint8)
            alfa = np.asarray(cur.getchannel('A'), dtype=np.uint8)
        level_list.append(idx.tobytes() + (alfa.tobytes() if alpha_bits == 8 else b''))
        if not mipmaps or (cur.width == 1 and cur.height == 1) or len(level_list) == 16:
            break
        cur = cur.resize((max(1, cur.width // 2), max(1, cur.height // 2)), Image.LANCZOS)
    pos = 156 + 1024
    offs, sizes = [], []
    for lv in level_list:
        offs.append(pos)
        sizes.append(len(lv))
        pos += len(lv)
    offs += [0] * (16 - len(offs))
    sizes += [0] * (16 - len(sizes))
    hdr = b'BLP1' + struct.pack('<IIIIII', 1, alpha_bits, w, h, extra, 1 if mipmaps else 0)
    hdr += struct.pack('<16I', *offs) + struct.pack('<16I', *sizes)
    return hdr + pal.tobytes() + b''.join(level_list)


def save_blp_fit(im, path, max_bytes, alpha_bits=None, mipmaps=True, extra=None, qmin=100, qmax=300):
    lo, hi = qmin, qmax
    best = None
    while lo <= hi:
        q = (lo + hi) // 2
        n, size = save_blp(im, path, q, alpha_bits, mipmaps, extra)
        if size <= max_bytes:
            best = (q, size)
            hi = q - 1
        else:
            lo = q + 1
    if best is None:
        n, size = save_blp(im, path, qmin, alpha_bits, mipmaps, extra)
        return qmin, size
    save_blp(im, path, best[0], alpha_bits, mipmaps, extra)
    return best
