# MPQ hashing, encryption and header scanning.
import os
import struct
import sys
from array import array


CRYPT = [0] * 0x500
_seed = 0x00100001
for _i in range(0x100):
    for _idx in range(_i, 0x500, 0x100):
        _seed = (_seed * 125 + 3) % 0x2AAAAB
        _t = (_seed & 0xFFFF) << 0x10
        _seed = (_seed * 125 + 3) % 0x2AAAAB
        _t |= _seed & 0xFFFF
        CRYPT[_idx] = _t


def _mix_key(key):
    return ((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) & 0xFFFFFFFF | (key >> 0x0B)


_NATIVE_DECRYPT = [None]


def _native_decrypt():
    if _NATIVE_DECRYPT[0] is None:
        try:
            import mpqcrypt
            _NATIVE_DECRYPT[0] = mpqcrypt.load_data() or False
        except Exception:
            _NATIVE_DECRYPT[0] = False
    return _NATIVE_DECRYPT[0]


def decrypt_bytes(data, key):
    native_lib = _NATIVE_DECRYPT[0] if _NATIVE_DECRYPT[0] is not None else _native_decrypt()
    if native_lib and len(data) >= 16:
        return native_lib(data, key)
    n = len(data) // 4
    src = array('I')
    src.frombytes(bytes(data[:n * 4]))
    crypt = CRYPT
    sd = 0xEEEEEEEE
    for i in range(n):
        sd = (sd + crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        pt = src[i] ^ ((key + sd) & 0xFFFFFFFF)
        src[i] = pt
        key = ((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) & 0xFFFFFFFF | (key >> 0x0B)
        sd = (pt + sd + (sd << 5) + 3) & 0xFFFFFFFF
    if sys.byteorder != 'little':
        src.byteswap()
    return src.tobytes() + bytes(data[n * 4:])


_CIPHER = [None]


def _native_cipher():
    if _CIPHER[0] is None:
        try:
            import mpqcrypt
            _CIPHER[0] = mpqcrypt.load_cipher() or False
        except Exception:
            _CIPHER[0] = False
    return _CIPHER[0]


def encrypt_bytes(data, key):
    native_lib = _CIPHER[0] if _CIPHER[0] is not None else _native_cipher()
    if native_lib and len(data) >= 16 and 0 <= key <= 0xFFFFFFFF:
        return native_lib(data, key)
    n = len(data) // 4
    src = array('I')
    src.frombytes(bytes(data[:n * 4]))
    if sys.byteorder != 'little':
        src.byteswap()
    crypt = CRYPT
    sd = 0xEEEEEEEE
    for i in range(n):
        sd = (sd + crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        pt = src[i]
        src[i] = pt ^ ((key + sd) & 0xFFFFFFFF)
        key = ((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) & 0xFFFFFFFF | (key >> 0x0B)
        sd = (pt + sd + (sd << 5) + 3) & 0xFFFFFFFF
    if sys.byteorder != 'little':
        src.byteswap()
    return src.tobytes() + bytes(data[n * 4:])


def decrypt(data, key):
    b = decrypt_bytes(data, key)
    return list(struct.unpack_from('<%dI' % (len(b) // 4), b, 0))


def encrypt(vals, key):
    return encrypt_bytes(struct.pack('<%dI' % len(vals), *vals), key)


MPQ_UPPERCASE = bytes(c - 32 if 0x61 <= c <= 0x7A else (0x5C if c == 0x2F else c) for c in range(256))
UPPER_SLASH = bytes(c - 32 if 0x61 <= c <= 0x7A else c for c in range(256))


_NATIVE_HASH = [None]


def _native_hash():
    if _NATIVE_HASH[0] is None:
        try:
            import mpqcrypt
            _NATIVE_HASH[0] = mpqcrypt.load_hash() or False
        except Exception:
            _NATIVE_HASH[0] = False
    return _NATIVE_HASH[0]


def hashstr(s, ht, bar=False):
    b = s if isinstance(s, (bytes, bytearray)) else s.encode('utf-8', 'surrogateescape')
    native = None if bar else (_NATIVE_HASH[0] if _NATIVE_HASH[0] is not None else _native_hash())
    if native:
        return native[0](bytes(b), ht)
    s1, s2 = 0x7FED7FED, 0xEEEEEEEE
    for c in b.translate(UPPER_SLASH if bar else MPQ_UPPERCASE):
        s1 = CRYPT[(ht << 8) + c] ^ ((s1 + s2) & 0xFFFFFFFF)
        s2 = (c + s1 + s2 + (s2 << 5) + 3) & 0xFFFFFFFF
    return s1


def hashstr_batch(name_list, ht, bar=False):
    native = None if bar else (_NATIVE_HASH[0] if _NATIVE_HASH[0] is not None else _native_hash())
    try:
        import numpy as np
    except ImportError:
        if native:
            return list(native[1]([bytes(n) for n in name_list], ht))
        return [hashstr(n, ht, bar) for n in name_list]
    if native:
        return np.frombuffer(native[1]([bytes(n) for n in name_list], ht), dtype=np.uint32)
    out = np.zeros(len(name_list), dtype=np.uint32)
    by_size = {}
    for i, b in enumerate(name_list):
        by_size.setdefault(len(b), []).append(i)
    crypt = np.array(CRYPT, dtype=np.uint32)
    uppercase = np.frombuffer(UPPER_SLASH if bar else MPQ_UPPERCASE, dtype=np.uint8)
    base = np.uint32(ht << 8)
    for sz, idx in by_size.items():
        m = len(idx)
        s1 = np.full(m, 0x7FED7FED, dtype=np.uint32)
        s2 = np.full(m, 0xEEEEEEEE, dtype=np.uint32)
        if sz:
            mat = uppercase[np.frombuffer(b''.join(name_list[i] for i in idx), dtype=np.uint8).reshape(m, sz)]
            for j in range(sz):
                c = mat[:, j].astype(np.uint32)
                s1 = crypt[base + c] ^ (s1 + s2)
                s2 = c + s1 + s2 + (s2 << np.uint32(5)) + np.uint32(3)
        out[np.array(idx, dtype=np.int64)] = s1
    return out


HASH_TABLE_KEY = hashstr('(hash table)', 3)
BLOCK_TABLE_KEY = hashstr('(block table)', 3)


class Header:
    pass


def _map_kind(d, fname=None):
    if fname and os.path.splitext(fname)[1].lower() in ('.w3x', '.w3m'):
        return 'wc3'
    if len(d) > 0x10 and d[:4] == b'HM3W' and d[4:8] == b'\0\0\0\0':
        return 'wc3'
    if len(d) > 0x40 and d[:2] == b'MZ':
        lfanew = struct.unpack_from('<I', d, 0x3C)[0]
        if 0 < lfanew < 0x10000 and lfanew + 4 + 20 <= len(d):
            if struct.unpack_from('<H', d, lfanew + 4 + 18)[0] & 0x2000:
                return 'wc3'
    return ''


def _v1_fields(h, d, o, sz):
    h.offset = o
    h.header_size, h.archive_size, h.version, h.block_shift = struct.unpack_from('<IIHH', d, o + 4)
    h.hash_pos, h.block_pos, h.hash_n, h.block_n = struct.unpack_from('<IIII', d, o + 16)
    h.hash_abs = (o + h.hash_pos) & 0xFFFFFFFF
    h.block_abs = (o + h.block_pos) & 0xFFFFFFFF
    h.valid = (0 < h.hash_n <= 0x100000 and 0 < h.block_n <= 0x100000
               and h.hash_abs + h.hash_n * 16 <= sz and h.block_abs + h.block_n * 16 <= sz)
    return h


def find_header(d, fname=None, byte_size=None):
    sz = len(d) if byte_size is None else byte_size
    wc3 = _map_kind(d, fname) == 'wc3'
    skipped = []
    for o in range(0, max(len(d) - 32 + 1, 0), 0x200):
        sig = d[o:o + 4]
        pos = o
        if sig == b'MPQ\x1b' and not wc3:
            ud_size, offs, head_line = struct.unpack_from('<III', d, o + 4)
            if head_line <= ud_size <= offs and o + offs + 32 < sz:
                pos = o + offs
                sig = d[pos:pos + 4]
            else:
                skipped.append((o, 'invalid user data'))
                continue
        elif sig == b'MPQ\x1b':
            skipped.append((o, 'user data (MPQ\\x1b): Warcraft III does not read it'))
            continue
        if sig != b'MPQ\x1a':
            continue
        if pos + 32 > len(d):
            break
        hsize = struct.unpack_from('<I', d, pos + 4)[0]
        if hsize < 0x20:
            skipped.append((pos, 'dwHeaderSize %#x < 0x20' % hsize))
            continue
        h = _v1_fields(Header(), d, pos, sz)
        if (pos + h.hash_pos) & 0xFFFFFFFF > sz or (pos + h.block_pos) & 0xFFFFFFFF > sz:
            skipped.append((pos, 'FAKE header: table outside the file (hash %#x, block %#x)'
                            % ((pos + h.hash_pos) & 0xFFFFFFFF, (pos + h.block_pos) & 0xFFFFFFFF)))
            continue
        h.user_data = o if pos != o else None
        h.wc3 = wc3
        return h, skipped
    return None, skipped


def file_header(file_path, block_entry=1 << 20):
    sz = os.path.getsize(file_path)
    with open(file_path, 'rb') as f:
        d = f.read(min(block_entry, sz))
        h, skipped = find_header(d, file_path, sz)
        if h is None and len(d) < sz:
            f.seek(0)
            d = f.read()
            h, skipped = find_header(d, file_path, sz)
    return h, skipped


class MPQError(SystemExit, Exception):
    pass


def header_offset(file_path):
    h, _p = file_header(file_path)
    if h is None:
        raise MPQError('MPQ header not found: %s' % file_path)
    return h.offset


def header_sector(block_shift):
    return (0x200 << ((block_shift & 0xFF) & 0x1F)) & 0xFFFFFFFF


def is_malformed(h):
    m = []
    if h.version != 0:
        m.append('wFormatVersion=%d (expected 0)' % h.version)
    if h.header_size != 0x20:
        m.append('dwHeaderSize=%#010x (expected 0x20)' % h.header_size)
    hs = 0x20
    if h.block_n > 1:
        if h.hash_pos <= hs or h.hash_pos & 0x80000000:
            m.append('dwHashTablePos=%#010x (<= header or bit 31)' % h.hash_pos)
        if h.block_pos <= hs or h.block_pos & 0x80000000:
            m.append('dwBlockTablePos=%#010x (<= header or bit 31)' % h.block_pos)
    if h.block_shift & 0xFF00:
        m.append('wSectorSize=%#06x (only the low byte counts)' % h.block_shift)
    return m


def decrypt_array(data, key):
    from array import array
    n = len(data) // 4
    native_lib = _NATIVE_DECRYPT[0] if _NATIVE_DECRYPT[0] is not None else _native_decrypt()
    if native_lib and n >= 4 and 0 <= key <= 0xFFFFFFFF:
        out = array('I')
        out.frombytes(native_lib(data[:n * 4], key))
        if sys.byteorder != 'little':
            out.byteswap()
        return out
    src = array('I')
    src.frombytes(bytes(data[:n * 4]))
    out = array('I', bytes(n * 4))
    crypt = CRYPT
    seed = 0xEEEEEEEE
    for i in range(n):
        seed = (seed + crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        pt = src[i] ^ ((key + seed) & 0xFFFFFFFF)
        out[i] = pt
        key = ((((~key) << 0x15) & 0xFFFFFFFF) + 0x11111111) & 0xFFFFFFFF | (key >> 0x0B)
        seed = (pt + seed + (seed << 5) + 3) & 0xFFFFFFFF
    return out


BIG_TABLE = 1 << 22


def read_tables(d, h, hash_key=HASH_TABLE_KEY, block_key=BLOCK_TABLE_KEY):
    base = getattr(h, 'offset', 0)
    hp = (base + h.hash_pos) & 0xFFFFFFFF
    bp = (base + h.block_pos) & 0xFFFFFFFF
    raw_h = d[hp:hp + h.hash_n * 16]
    raw_b = d[bp:bp + h.block_n * 16]
    ht = decrypt_array(raw_h, hash_key) if len(raw_h) > BIG_TABLE else decrypt(raw_h, hash_key)
    bt = decrypt_array(raw_b, block_key) if len(raw_b) > BIG_TABLE else decrypt(raw_b, block_key)
    return ht, bt
