# Reads, as data, the strings of a Lua map script whose literals are stored encoded.
import itertools
import re


MARK = b'--W3P'
RX_DECRYPTOR = re.compile(rb'local function (_\w+)\(a,b\)local k,s,i0')
RX_ESC = re.compile(rb'\\(x[0-9A-Fa-f]{2}|\d{1,3}|.)', re.S)
RX_ID = re.compile(rb'^[A-Za-z_][A-Za-z0-9_]*$')
RX_QZ = re.compile(rb'local (_\w+)=(\d+) local (_\w+)=(\d+) local _W=')


def is_w3p(body_text):
    return body_text[:len(MARK)] == MARK


def lua_literal(b):
    def tr(m):
        e = m.group(1)
        if e[:1] == b'x':
            return bytes([int(e[1:], 16)])
        if e[:1].isdigit():
            return bytes([int(e) & 255])
        return {b'n': b'\n', b't': b'\t', b'r': b'\r', b'a': b'\a', b'b': b'\b', b'f': b'\f', b'v': b'\v',
                b'\\': b'\\', b'"': b'"', b"'": b"'", b'\n': b'\n'}.get(e, e)
    return RX_ESC.sub(tr, b)


def decrypt(a, b, T, q, z, W):
    if b is not None:
        k, s, i0, is_binary = a, b, 1, False
    else:
        is_binary = a[:1] == b'\x01'
        if is_binary:
            k, s, i0 = a[1] * 256 + a[2], a, 4
        else:
            k, s, i0 = int(a[1:5], 16), a, 6
    bg = k % 32749
    ai = (bg * T + W + q) % 32749 + 1
    ci = (bg + T * z) % 32749 + 1
    di = (ai * ci + 20) % 32749 + 1
    if is_binary:
        vals = list(s[i0 - 1:])
    else:
        hx = s[i0 - 1:]
        vals = [int(hx[i:i + 2], 16) for i in range(0, len(hx) - 1, 2)]
    out = bytearray()
    for v in vals:
        ti, ui = ai, ci
        ai, ci = ci, di
        di = (ui * di + ti + 20) % 32749
        out.append((v - di + 256) % 256)
    return bytes(out)


def _wrap(x, bits):
    m = (1 << bits) - 1
    x &= m
    return x - (1 << bits) if x >> (bits - 1) else x


def _prelude(body_text):
    end_pos = body_text.find(b'local function _H(')
    return body_text[:end_pos if end_pos > 0 else 20000]


def _calls(body_text, env_only=False):
    pre = _prelude(body_text)
    name_list = RX_DECRYPTOR.findall(pre)
    if not name_list:
        return []
    height = b'|'.join(re.escape(n) for n in name_list)
    if env_only:
        rx = re.compile(rb'_ENV\[(?:' + height + rb')\("((?:[^"\\]|\\.)*)"\)\]')
        return [(None, lua_literal(m.group(1))) for m in rx.finditer(body_text)]
    rx = re.compile(rb'\b(?:' + height + rb')\(\s*(?:(\d+)\s*,\s*)?"((?:[^"\\]|\\.)*)"\s*\)')
    return [(int(m.group(1)) if m.group(1) else None, lua_literal(m.group(2))) for m in rx.finditer(body_text)]


def _attempt(pair, T, q, z, W):
    k, s = pair
    try:
        return decrypt(k, s, T, q, z, W) if k is not None else decrypt(s, None, T, q, z, W)
    except (ValueError, IndexError):
        return None


def w3p_constants(body_text, sample_size=300):
    if not is_w3p(body_text):
        return None
    pre = _prelude(body_text)
    m = RX_QZ.search(pre)
    q, z = (int(m.group(2)), int(m.group(4))) if m else (23, 5)
    oracle = _calls(body_text, env_only=True)[:sample_size]
    if not oracle:
        return None
    best = None
    seen = set()
    for bits in (32, 64):
        maxint = (1 << (bits - 1)) - 1
        minint = -(1 << (bits - 1))
        for fn, gd, third in itertools.product((1, minint, 0, maxint, -1), range(5, 20), range(5, 20)):
            left = _wrap(_wrap(fn * 2896, bits) + gd * 1376, bits)
            right = _wrap(third * 3195 + (maxint % 97) * 3797, bits)
            T = (_wrap(left ^ right, bits) % 32749) + 1
            W = ((maxint % 97) * (gd + third)) % 32749 + 1
            if (T, W) in seen:
                continue
            seen.add((T, W))
            ok = sum(1 for pair in oracle if RX_ID.match(_attempt(pair, T, q, z, W) or b''))
            if best is None or ok > best[4]:
                best = (T, q, z, W, ok, len(oracle))
            if ok == len(oracle):
                return best
    return best if best and best[4] * 10 >= best[5] * 9 else None


def texts(body_text):
    c = w3p_constants(body_text)
    if not c:
        return []
    T, q, z, W = c[:4]
    out, seen = [], set()
    for pair in _calls(body_text):
        t = _attempt(pair, T, q, z, W)
        if t is not None and t not in seen:
            seen.add(t)
            out.append(t)
    return out


RX_W3P_PATH = re.compile(r'[\w\\/ .\-()\[\]]{1,180}\.[A-Za-z0-9]{2,4}')


def paths(body_text):
    out = set()
    for t in texts(body_text):
        s = t.decode('latin-1')
        for p in RX_W3P_PATH.findall(s):
            p = p.strip().replace('/', '\\')
            out.add(p)
            if ' ' in p:
                out.add(p.rsplit(' ', 1)[1])
    return sorted(out)
