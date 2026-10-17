# Replaces files in an MPQ archive in bulk.
import struct


_crypt = []


def _init_crypt():
    seed = 0x00100001
    tbl = [0] * 0x500
    for i in range(0x100):
        idx = i
        for _ in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            t1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            t2 = seed & 0xFFFF
            tbl[idx] = t1 | t2
            idx += 0x100
    return tbl


MPQ_UPPERCASE = bytes(c - 32 if 0x61 <= c <= 0x7A else (0x5C if c == 0x2F else c) for c in range(256))


def hash_string(s, htype):
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    b = s if isinstance(s, (bytes, bytearray)) else s.encode('utf-8', 'surrogateescape')
    for ch in b.translate(MPQ_UPPERCASE):
        seed1 = (_crypt[(htype << 8) + ch] ^ ((seed1 + seed2) & 0xFFFFFFFF)) & 0xFFFFFFFF
        seed2 = (ch + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1


def _mpqlib():
    import mpqlib
    return mpqlib


def decrypt(data, key):
    if 0 <= key <= 0xFFFFFFFF:
        return _mpqlib().decrypt_bytes(data, key)
    seed = 0xEEEEEEEE
    n = len(data) // 4
    vals = struct.unpack('<%dI' % n, data[:n * 4])
    res = []
    for v in vals:
        seed = (seed + _crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        ch = v ^ ((key + seed) & 0xFFFFFFFF)
        key = (((~key << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
        seed = (ch + seed + (seed << 5) + 3) & 0xFFFFFFFF
        res.append(ch)
    return struct.pack('<%dI' % n, *res) + data[n * 4:]


def encrypt(data, key):
    if 0 <= key <= 0xFFFFFFFF:
        return _mpqlib().encrypt_bytes(data, key)
    seed = 0xEEEEEEEE
    n = len(data) // 4
    vals = struct.unpack('<%dI' % n, data[:n * 4])
    res = []
    for ch in vals:
        seed = (seed + _crypt[0x400 + (key & 0xFF)]) & 0xFFFFFFFF
        v = ch ^ ((key + seed) & 0xFFFFFFFF)
        key = (((~key << 0x15) + 0x11111111) | (key >> 0x0B)) & 0xFFFFFFFF
        seed = (ch + seed + (seed << 5) + 3) & 0xFFFFFFFF
        res.append(v)
    return struct.pack('<%dI' % n, *res) + data[n * 4:]


def pack_compressed(content, sector):
    import zlib
    n = (len(content) + sector - 1) // sector
    blobs = []
    for s in range(n):
        chunk = content[s * sector:(s + 1) * sector]
        z = b'\x02' + zlib.compress(chunk, 9)
        blobs.append(z if len(z) < len(chunk) else chunk)
    offs = []
    pos = (n + 1) * 4
    for b in blobs:
        offs.append(pos)
        pos += len(b)
    offs.append(pos)
    return struct.pack('<%dI' % (n + 1), *offs) + b''.join(blobs)
