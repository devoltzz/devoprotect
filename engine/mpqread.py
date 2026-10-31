# Reads MPQ archives with the same rules as the game.
import bz2
import collections
import struct
import zlib
import os

import mpqlib as M
import pkware


FLAG_IMPLODE = 0x00000100
FLAG_COMPRESS = 0x00000200
FLAG_ENCRYPT = 0x00010000
FLAG_FIXKEY = 0x00020000
FLAG_SINGLE = 0x01000000
FLAG_EXISTS = 0x80000000
FLAGS_W3X = 0x00000100 | 0x00000200 | 0x00010000 | 0x00020000 | 0x02000000 | 0x04000000 | 0x10000000 | 0x80000000
BLOCK_MASK = 0x0FFFFFFF
LONG_PROBE = 256
VALID_FOR_GAME_ONLY = 'not compressed; the stored size is wrong and the game does not use it'
VALID_SLACK = 'compressed; the sector table ends before the stored size and the game does not read the slack'
VALID_FOR_GAME = (VALID_FOR_GAME_ONLY, VALID_SLACK)


_CACHE = collections.OrderedDict()
_CACHE_BYTES = [0]
CACHE_MAX = 96 << 20
CACHE_CHUNK_MAX = 4 << 20


def _crypt(data, key):
    data = bytes(data)
    k = (key, data)
    r = _CACHE.get(k)
    if r is not None:
        _CACHE.move_to_end(k)
        return r
    r = M.decrypt_bytes(data, key)
    if len(data) <= CACHE_CHUNK_MAX:
        _CACHE[k] = r
        _CACHE_BYTES[0] += 2 * len(data) + 100
        while _CACHE_BYTES[0] > CACHE_MAX and _CACHE:
            (_k, old), _v = _CACHE.popitem(last=False)
            _CACHE_BYTES[0] -= 2 * len(old) + 100
    return r


def inflate(body, expected=None):
    ceiling = expected + 1 if expected is not None else None
    for wbits, payload in ((zlib.MAX_WBITS, body), (-15, body[2:])):
        try:
            d = zlib.decompressobj(wbits)
            out = d.decompress(payload, ceiling) if ceiling else d.decompress(payload)
        except zlib.error:
            continue
        if ceiling and len(out) > expected:
            raise ValueError('inflate: the stream gives more than the %d B of the sector' % expected)
        if d.eof:
            return out
    raise ValueError('inflate failed: %s' % body[:8].hex())


def bunzip(body, expected=None):
    d = bz2.BZ2Decompressor()
    out = d.decompress(body, expected + 1) if expected is not None else d.decompress(body)
    if expected is not None and len(out) > expected:
        raise ValueError('bzip2: the stream gives more than the %d B of the sector' % expected)
    if not d.eof:
        raise ValueError('bzip2: incomplete stream')
    return out


def key_from_name(name, off, fs, fl):
    plain_name = name.replace('/', '\\').split('\\')[-1]
    key = M.hashstr(plain_name, 3)
    if fl & FLAG_FIXKEY:
        key = ((key + off) ^ fs) & 0xFFFFFFFF
    return key


SOUND_MASKS = (0x01, 0x40, 0x80, 0x41, 0x81)
FILE_SIZE_CAP = 1 << 30


def decompress_sector(sector, expected):
    if len(sector) == expected:
        return sector
    if pkware.is_implode(sector):
        return pkware.decompress(sector, expected=expected)
    mask = sector[0]
    body = sector[1:]
    if mask == 0x02:
        return inflate(body, expected)
    if mask == 0x08:
        return pkware.decompress(sector, expected=expected)
    if mask == 0x00:
        return body
    if mask == 0x10:
        return bunzip(body, expected)
    if mask == 0x20:
        return decompress_sparse(body, expected)
    if mask == 0x22:
        return decompress_sparse(inflate(body, expected + expected // 64 + 16), expected)
    if mask == 0x30:
        return decompress_sparse(bunzip(body, expected + expected // 64 + 16), expected)
    if mask in SOUND_MASKS or mask == 0x12:
        import mpq_wave
        return mpq_wave.decompress_sector_chain(sector, expected)
    try:
        return inflate(sector, expected)
    except ValueError:
        import mpq_wave
        try:
            return mpq_wave.decompress_sector_chain(sector, expected)
        except Exception:
            pass
        raise


def decompress_sparse(b, expected=None):
    if len(b) < 5:
        raise ValueError('sparse: short stream')
    n = struct.unpack_from('>I', b, 0)[0]
    if expected is not None and n > expected:
        raise ValueError('sparse: %d B > expected %d' % (n, expected))
    out = bytearray()
    i = 4
    while i < len(b) and len(out) < n:
        c = b[i]
        i += 1
        if c & 0x80:
            k = (c & 0x7F) + 1
            if i + k > len(b):
                raise ValueError('sparse: chunk goes past the end')
            out += b[i:i + k]
            i += k
        else:
            out += bytes((c & 0x7F) + 3)
    return bytes(out[:n])


def _sector_prefix(chunk, wanted, fl, whole, expected_len):
    mask = chunk[0] if chunk else None
    try:
        if fl & FLAG_COMPRESS and mask == 0x02:
            return zlib.decompressobj().decompress(chunk[1:], wanted)
        if fl & FLAG_COMPRESS and mask == 0x10:
            return bz2.BZ2Decompressor().decompress(chunk[1:], wanted)
        if not fl & FLAG_COMPRESS or mask == 0x08:
            return pkware.decompress(chunk, expected=wanted)
        if whole:
            d = decompress_by_flag(chunk, expected_len, fl)
            return d if len(d) == expected_len else None
    except Exception:
        return None
    return None


def table_like_stormlib(offs, nsec, sector_bytes, table_size):
    for i in range(nsec):
        if offs[i + 1] < offs[i]:
            return 'sector table out of order at sector %d (%d > %d)' % (i, offs[i], offs[i + 1])
        if offs[i + 1] - offs[i] > sector_bytes:
            return 'sector %d has %d B, more than the sector size of the file (%d)' % (
                i,
                offs[i + 1] - offs[i],
                sector_bytes,
            )
    if (offs[0] & 0xFFFFFFFC) > table_size and offs[0] > table_size + 0x400:
        return 'the sector table starts at %d, more than 0x400 past its size (%d)' % (offs[0], table_size)
    return None


def decompress_by_flag(sector_bytes, expected_len, fl):
    if fl & FLAG_COMPRESS:
        return decompress_sector(sector_bytes, expected_len)
    return pkware.decompress(sector_bytes, expected=expected_len)


_NATIVE_KEYS = [None]


def _native_keys():
    if _NATIVE_KEYS[0] is None:
        try:
            import mpqcrypt
            _NATIVE_KEYS[0] = mpqcrypt.load_keys() or False
        except Exception:
            _NATIVE_KEYS[0] = False
    return _NATIVE_KEYS[0]


def _detect_all(enc0, enc1, d0, accept1):
    native = _NATIVE_KEYS[0] if _NATIVE_KEYS[0] is not None else _native_keys()
    if native:
        for saved, v in native(enc0, enc1, d0):
            if accept1(v):
                yield saved
        return
    k12 = ((enc0 ^ d0) - 0xEEEEEEEE) & 0xFFFFFFFF
    for i in range(0x100):
        k1 = (k12 - M.CRYPT[0x400 + i]) & 0xFFFFFFFF
        k2 = (0xEEEEEEEE + M.CRYPT[0x400 + (k1 & 0xFF)]) & 0xFFFFFFFF
        if enc0 ^ ((k1 + k2) & 0xFFFFFFFF) != d0:
            continue
        saved = k1
        k1 = M._mix_key(k1)
        k2 = (d0 + k2 + (k2 << 5) + 3) & 0xFFFFFFFF
        k2 = (k2 + M.CRYPT[0x400 + (k1 & 0xFF)]) & 0xFFFFFFFF
        if accept1(enc1 ^ ((k1 + k2) & 0xFFFFFFFF)):
            yield saved


def _detect(enc0, enc1, d0, accept1):
    return next(_detect_all(enc0, enc1, d0, accept1), None)


def detect_sector_key(table, sector_len, table_size):
    return next(_sector_keys(table, sector_len, table_size), None)


def detect_sector_keys(table, sector_len, table_size):
    return list(_sector_keys(table, sector_len, table_size))


def _sector_keys(table, sector_len, table_size):
    if len(table) < 8:
        return
    e0, e1 = struct.unpack_from('<II', table, 0)
    for d0 in range(table_size, table_size + 4):
        for k in _detect_all(e0, e1, d0, lambda v, d0=d0: v <= sector_len + d0):
            yield (k + 1) & 0xFFFFFFFF


KNOWN_CONTENTS = (
    (0x584C444D, lambda v: v == 0x53524556),
    (0x31504C42, lambda v: v in (0, 1)),
    (0x46464952, None),
    (0x00905A4D, lambda v: v == 3),
    (0x6D783F3C, lambda v: v == 0x6576206C),
)


def detect_content_key(data_bytes, file_size):
    if len(data_bytes) < 8:
        return None
    e0, e1 = struct.unpack_from('<II', data_bytes, 0)
    for d0, accept in KNOWN_CONTENTS:
        if accept is None:
            accept = (lambda v: v == file_size - 8)
        k = _detect(e0, e1, d0, accept)
        if k is not None:
            return k
    return None


_VALID_MEMO = {}
_VALID_MEMO_LIMIT = 1 << 19
_READ_CACHE = collections.OrderedDict()
_READ_CACHE_SIZE = [0]
_READ_CACHE_LIMIT = 96 << 20
_READ_DONE = set()
_READ_DONE_LIMIT = 1 << 20
_READ_CACHE_ITEM_MAX = 8 << 20


_HASHES3 = {}
_TABLES_CACHE = collections.OrderedDict()
_TABLES_MIN_BLOCKS = 1 << 16
_TABLES_CAP = 2


def _hashes3(name, bar=False):
    hash_key = (name, 1) if bar else name
    r = _HASHES3.get(hash_key)
    if r is None:
        r = tuple(M.hashstr(name, t, bar) for t in (0, 1, 2))
        if len(_HASHES3) > (1 << 18):
            _HASHES3.clear()
        _HASHES3[hash_key] = r
    return r


def _file_identity(path):
    try:
        st = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)


def read_as_game(a, fname):
    try:
        r = a.find_locale(fname) if a.find(fname) else None
        return a.read(fname, bi=r[1]) if r else None
    except Exception:
        return None


def listfile_names(a):
    lf = read_as_game(a, '(listfile)')
    return [lx.strip().replace('/', '\\') for lx in (lf or b'').decode('utf-8', 'surrogateescape').splitlines()
            if lx.strip()]


class Archive:
    VALIDATED_LIMIT = 1 << 17

    def __init__(self, path):
        self.path = path
        self._identity = _file_identity(path)
        self.d = open(path, 'rb').read()
        self.h, self.skipped = M.find_header(self.d, path)
        if self.h is None:
            raise M.MPQError('no valid MPQ header')
        if M.header_sector(self.h.block_shift) == 0:
            raise M.MPQError('invalid sector size in the MPQ header (wSectorSize gives sector 0)')
        self.hash_n = self.h.hash_n & 0x0FFFFFFF
        self.block_n = self.h.block_n & 0x0FFFFFFF
        hm = M.Header()
        hm.__dict__.update(self.h.__dict__)
        hm.hash_n, hm.block_n = self.hash_n, self.block_n
        bitmask = FLAGS_W3X if getattr(self.h, 'wc3', False) else 0xFFFFFFFF
        hash_key = None
        if self.block_n >= _TABLES_MIN_BLOCKS:
            base = getattr(hm, 'offset', 0)
            hp = (base + hm.hash_pos) & 0xFFFFFFFF
            bp = (base + hm.block_pos) & 0xFFFFFFFF
            hash_key = (self.d[hp:hp + hm.hash_n * 16], self.d[bp:bp + hm.block_n * 16], bitmask)
        stored_value = _TABLES_CACHE.get(hash_key) if hash_key is not None else None
        if stored_value is not None:
            _TABLES_CACHE.move_to_end(hash_key)
            ht, bt, block_list = stored_value
            self.ht, self.bt, self.blocks = ht[:], bt[:], list(block_list)
        else:
            self.ht, self.bt = M.read_tables(self.d, hm)
            end_pos = 4 * min(self.block_n, len(self.bt) // 4)
            bt = self.bt
            self.blocks = list(
                zip(bt[0:end_pos:4], bt[1:end_pos:4], bt[2:end_pos:4], [f & bitmask for f in bt[3:end_pos:4]])
            )
            if hash_key is not None:
                _TABLES_CACHE[hash_key] = (self.ht[:], self.bt[:], list(self.blocks))
                while len(_TABLES_CACHE) > _TABLES_CAP:
                    _TABLES_CACHE.popitem(last=False)
        self.is_malformed = bool(M.is_malformed(self.h))
        self.hash_n_read = len(self.ht) // 4
        self._idx = None
        self._validated = {}

    @property
    def sector_size(self):
        return M.header_sector(self.h.block_shift)

    def hash_entries(self, name):
        bar = '/' in name
        es = self._probe(*_hashes3(name.replace('/', '\\')))
        if not es and bar:
            es = self._probe(*_hashes3(name, True))
        return es

    def _probe(self, h0, h1, h2):
        hn = self.hash_n
        if hn != self.hash_n_read or hn & (hn - 1) or self._idx is not None:
            return self._index_entries(h0, h1, h2)
        idx = h0 & (hn - 1)
        out = []
        for probe in range(hn):
            if probe == LONG_PROBE:
                return self._index_entries(h0, h1, h2)
            i = (idx + probe) & (hn - 1)
            fh, ft, bl, bi = self.ht[i * 4:i * 4 + 4]
            if fh == h1 and ft == h2 and (bi & BLOCK_MASK) < len(self.blocks):
                out.append((i, bl & 0xFFFF, (bl >> 16) & 0xFF, bi & BLOCK_MASK, (bl >> 24) & 0xFF))
            elif bi == 0xFFFFFFFF:
                break
        return out

    def _index_entries(self, h0, h1, h2):
        import bisect
        if self._idx is not None and self._idx_blocks != len(self.blocks):
            self._idx = None
        if self._idx is None:
            self._idx_blocks = len(self.blocks)
            idx = {}
            free_slots = []
            ht = self.ht
            nb = len(self.blocks)
            for i in range(self.hash_n_read):
                bi = ht[i * 4 + 3]
                if bi == 0xFFFFFFFF:
                    free_slots.append(i)
                elif (bi & BLOCK_MASK) < nb:
                    idx.setdefault((ht[i * 4], ht[i * 4 + 1]), []).append(i)
            self._idx, self._free = idx, free_slots
        hn = self.hash_n
        if hn & (hn - 1):
            return self._mask_probe(h0, h1, h2)
        slot = h0 & (hn - 1)
        ceiling = hn
        if self._free:
            k = bisect.bisect_left(self._free, slot)
            f = self._free[k] if k < len(self._free) else self._free[0] + hn
            ceiling = (f - slot) % hn if f != slot else 0
        out = []
        for i in self._idx.get((h1, h2), ()):
            dist = (i - slot) % hn
            if dist < ceiling:
                bl, bi = self.ht[i * 4 + 2], self.ht[i * 4 + 3]
                out.append((dist, (i, bl & 0xFFFF, (bl >> 16) & 0xFF, bi & BLOCK_MASK, (bl >> 24) & 0xFF)))
        return [e for _d, e in sorted(out)]

    def _mask_probe(self, h0, h1, h2):
        cands = self._idx.get((h1, h2))
        if not cands:
            return []
        tgt = set(cands)
        bitmask = self.hash_n - 1
        i = h0 & bitmask
        seen, out = set(), []
        missing_items = len(tgt)
        while i not in seen:
            seen.add(i)
            if i in tgt:
                bl, bi = self.ht[i * 4 + 2], self.ht[i * 4 + 3]
                out.append((i, bl & 0xFFFF, (bl >> 16) & 0xFF, bi & BLOCK_MASK, (bl >> 24) & 0xFF))
                missing_items -= 1
                if not missing_items:
                    break
            elif i < self.hash_n_read and self.ht[i * 4 + 3] == 0xFFFFFFFF:
                break
            i = (i + 1) & bitmask
        return out

    def find(self, name):
        es = self.hash_entries(name)
        if not es:
            return None
        neutrals = [e for e in es if e[1] == 0 and e[2] == 0]
        e = neutrals[-1] if neutrals else es[0]
        if not self.exists(e[3]):
            return None
        return e[0], e[3]

    def exists(self, bi):
        if bi >= len(self.blocks):
            return False
        off, _cs, fs, fl = self.blocks[bi]
        if not fl & FLAG_EXISTS:
            return False
        if self.is_malformed and fs >= 0x80000000:
            return False
        return (self.h.offset + off) & 0xFFFFFFFF < len(self.d)

    def pointed_blocks(self):
        ht, nb = self.ht, len(self.blocks)
        matches = set()
        for i in range(self.hash_n_read):
            bi = ht[4 * i + 3]
            if bi >= 0xFFFFFFFE:
                continue
            bi &= 0x0FFFFFFF
            if bi < nb and bi not in matches and self.exists(bi):
                matches.add(bi)
        return sorted(matches)

    def find_locale(self, name):
        r = self.find(name)
        if r is None or self.validate(r[1], name)[0] == 'ok':
            return r
        other_entries = [e for e in self.hash_entries(name) if e[1] != 0 and e[3] != r[1]]
        other_entries.sort(key=lambda e: e[1] != 0x409)
        seen = set()
        for e in other_entries:
            if e[3] not in seen:
                seen.add(e[3])
                if self.validate(e[3], name)[0] == 'ok':
                    return e[0], e[3]
        return r

    def unnamed_key(self, bi):
        off, cs, fs, fl = self.blocks[bi]
        if not fl & FLAG_ENCRYPT or fl & FLAG_SINGLE or not fs:
            return None
        p = (self.h.offset + off) & 0xFFFFFFFF
        if not fl & (FLAG_IMPLODE | FLAG_COMPRESS):
            return detect_content_key(self.d[p:p + 8], fs)
        ntab = (fs + self.sector_size - 1) // self.sector_size + 1 + (1 if fl & 0x04000000 else 0)
        for k in detect_sector_keys(self.d[p:p + 8], self.sector_size, ntab * 4):
            if _validate_block(self, bi, None, _key=k)[0] == 'ok':
                return k
        return None

    def read(self, name, bi=None, hash_key=None):
        if bi is None:
            r = self.find(name)
            if not r:
                return None
            bi = r[1]
        if hash_key is not None or not self._identity or bi >= len(self.blocks):
            return self._read_uncached(name, bi, hash_key)
        k = (self._identity, self.h.offset, bi, self.blocks[bi], name)
        x = _READ_CACHE.get(k)
        if x is not None:
            _READ_CACHE.move_to_end(k)
            return x
        x = self._read_uncached(name, bi, hash_key)
        if x is not None and len(_READ_DONE) < _READ_DONE_LIMIT:
            _READ_DONE.add(k)
        if type(x) is bytes and len(x) <= _READ_CACHE_ITEM_MAX:
            _READ_CACHE[k] = x
            _READ_CACHE_SIZE[0] += len(x)
            while _READ_CACHE_SIZE[0] > _READ_CACHE_LIMIT and _READ_CACHE:
                _k, v = _READ_CACHE.popitem(last=False)
                _READ_CACHE_SIZE[0] -= len(v)
        return x

    def already_read(self, name, bi=None):
        if not self._identity:
            return False
        if bi is None:
            r = self.find(name)
            if not r:
                return False
            bi = r[1]
        return bi < len(self.blocks) and (self._identity, self.h.offset, bi, self.blocks[bi], name) in _READ_DONE

    def _read_uncached(self, name, bi, hash_key=None):
        if bi >= len(self.blocks):
            return None
        off, cs, fs, fl = self.blocks[bi]
        if not (fl & FLAG_EXISTS) or bi >= 0xFFFFFFFE:
            return None
        if fs == 0:
            return b''
        p = (self.h.offset + off) & 0xFFFFFFFF
        key = None
        if fl & FLAG_ENCRYPT:
            key = hash_key if hash_key is not None else key_from_name(name, off, fs, fl)

        sec = self.sector_size
        nsec = (fs + sec - 1) // sec
        compressed = bool(fl & (FLAG_IMPLODE | FLAG_COMPRESS))
        if fs > FILE_SIZE_CAP:
            raise ValueError(
                'block %d: the declared size (%d B) is above the limit of %d MB' % (bi, fs, FILE_SIZE_CAP >> 20)
            )

        if fl & FLAG_SINGLE:
            data = self.d[p:p + cs]
            if key is not None:
                data = _crypt(data, key)
            if compressed:
                data = decompress_sector(data, fs)
            return data[:fs]

        if not compressed:
            if p + fs > len(self.d):
                raise ValueError('block %d: the uncompressed file (%d B) goes past the end of the MPQ' % (bi, fs))
            data_bytes = self.d[p:p + fs]
            if key is None:
                return bytes(data_bytes)
            out = bytearray()
            for s in range(nsec):
                out += _crypt(data_bytes[s * sec:(s + 1) * sec], (key + s) & 0xFFFFFFFF)
            return bytes(out[:fs])
        ntab = nsec + 1 + (1 if fl & 0x04000000 else 0)
        tb = self.d[p:p + ntab * 4]
        if len(tb) < ntab * 4:
            raise ValueError('block %d: smaller than the sector table (%d B)' % (bi, len(tb)))
        if key is not None:
            tb = _crypt(tb, (key - 1) & 0xFFFFFFFF)
        offs = struct.unpack_from('<%dI' % (nsec + 1), tb, 0)
        invalid = table_like_stormlib(offs, nsec, sec, ntab * 4)
        if invalid:
            raise ValueError('block %d: %s' % (bi, invalid))
        out = bytearray()
        for s in range(nsec):
            begin = (p + offs[s]) & 0xFFFFFFFF
            n = offs[s + 1] - offs[s]
            chunk = self.d[begin:begin + n]
            if len(chunk) < n:
                raise ValueError('block %d: sector %d goes past the end of the file' % (bi, s))
            expected = min(sec, fs - s * sec)
            if key is not None:
                chunk = _crypt(chunk, (key + s) & 0xFFFFFFFF)
            if n >= expected:
                out += chunk[:expected]
            elif n == 0:
                out += bytes(expected)
            else:
                data_bytes = decompress_by_flag(chunk, expected, fl)
                if len(data_bytes) < expected:
                    data_bytes += bytes(expected - len(data_bytes))
                out += data_bytes[:expected]
        return bytes(out[:fs])

    def interval(self, bi, fname=None):
        off, cs, fs, fl = self.blocks[bi]
        p = (self.h.offset + off) & 0xFFFFFFFF
        if not cs_unknown(cs, p, len(self.d)):
            return p, p + cs
        if fs == 0:
            return p, p
        if not fl & (FLAG_IMPLODE | FLAG_COMPRESS) or fl & FLAG_SINGLE:
            return p, p + fs
        nsec = (fs + self.sector_size - 1) // self.sector_size
        ntab = nsec + 1 + (1 if fl & 0x04000000 else 0)
        tb = self.d[p:p + ntab * 4]
        if len(tb) < ntab * 4:
            return p, p + fs
        if fl & FLAG_ENCRYPT:
            key = key_from_name(fname, off, fs, fl) if fname else detect_sector_key(tb[:8], self.sector_size,
                                                                                    ntab * 4)
            if key is None:
                return p, p + fs
            tb = _crypt(tb, (key - 1) & 0xFFFFFFFF)
        return p, p + struct.unpack_from('<I', tb, (ntab - 1) * 4)[0]

    def validate_light(self, bi, fname):
        if not self.exists(bi):
            return 'invalid', 'the block does not exist (IsValidHashEntry1)'
        off, _cs, fs, fl = self.blocks[bi]
        if fs == 0:
            return 'ok', b''
        p = (self.h.offset + off) & 0xFFFFFFFF
        sec = self.sector_size
        key = key_from_name(fname, off, fs, fl) if fl & FLAG_ENCRYPT else None
        comp = bool(fl & (FLAG_IMPLODE | FLAG_COMPRESS))
        try:
            if fl & FLAG_SINGLE or not comp:
                if p + min(fs, sec) > len(self.d):
                    return 'invalid', 'runs past the end of the file'
                if fl & FLAG_SINGLE and comp:
                    data_bytes = self.read(fname, bi=bi) if fs <= (4 << 20) else b''
                    return (
                        ('ok', data_bytes[:4096])
                        if fs > (4 << 20) or len(data_bytes) == fs
                        else ('invalid', 'single unit')
                    )
                first = self.d[p:p + min(fs, sec)]
                if key is not None:
                    first = _crypt(first, key)
                return 'ok', first[:4096]
            nsec = (fs + sec - 1) // sec
            ntab = nsec + 1 + (1 if fl & 0x04000000 else 0)
            tb = self.d[p:p + ntab * 4]
            if len(tb) < ntab * 4:
                return 'invalid', 'smaller than the sector table'
            if key is not None:
                tb = _crypt(tb, (key - 1) & 0xFFFFFFFF)
            offs = struct.unpack_from('<%dI' % (nsec + 1), tb, 0)
            if not ntab * 4 <= offs[0] <= ntab * 4 + 0x400:
                return 'invalid', 'the sector table does not start at its own size'
            invalid = table_like_stormlib(offs, nsec, sec, ntab * 4)
            if invalid:
                return 'invalid', invalid
            begin = (p + offs[0]) & 0xFFFFFFFF
            n = offs[1] - offs[0]
            if begin + n > len(self.d):
                return 'invalid', 'the 1st sector runs past the end of the file'
            exp_len = min(sec, fs)
            chunk = self.d[begin:begin + min(n, 65536)]
            if key is not None:
                chunk = _crypt(chunk, key)
            if n >= exp_len:
                return 'ok', chunk[:4096]
            wanted = min(exp_len, 4096)
            data_bytes = _sector_prefix(chunk, wanted, fl, n <= 65536, exp_len)
            if data_bytes is None or len(data_bytes) < wanted:
                return 'invalid', 'the 1st sector does not decompress'
            return 'ok', data_bytes[:4096]
        except Exception as e:
            return 'invalid', 'the 1st sector does not decompress (%s)' % str(e)[:60]

    def validate(self, bi, fname=None):
        k = (bi, fname)
        r = self._validated.get(k)
        if r is None:
            memo_key = (self._identity, self.h.offset, bi, self.blocks[bi] if bi < len(self.blocks) else None, fname) \
                if self._identity else None
            r = _VALID_MEMO.get(memo_key) if memo_key else None
            if r is None:
                r = _validate_block(self, bi, fname)
                if memo_key and len(_VALID_MEMO) < _VALID_MEMO_LIMIT:
                    _VALID_MEMO[memo_key] = r
            if len(self._validated) < self.VALIDATED_LIMIT:
                self._validated[k] = r
        return r

    def _region(self, bi, fname):
        if bi is None or bi >= len(self.blocks):
            return None
        off, cs, fs, fl = self.blocks[bi]
        if not (fl & FLAG_EXISTS):
            return None
        p = (self.h.offset + off) & 0xFFFFFFFF
        key = key_from_name(fname, off, fs, fl) if fl & FLAG_ENCRYPT else None
        if fs == 0:
            n = 0
        elif fl & FLAG_SINGLE:
            if cs_unknown(cs, p, len(self.d)):
                return None
            n = cs
        elif not fl & (FLAG_IMPLODE | FLAG_COMPRESS):
            n = fs
        else:
            n = end_by_sector_table(self, bi, fname)
            if n is None:
                return None
        if p + n > len(self.d):
            return None
        return p, n, key, fs, fl

    def same_data(self, other, fname, bi=None, other_bi=None):
        if bi is None:
            r = self.find(fname)
            bi = r[1] if r else None
        if other_bi is None:
            r = other.find(fname)
            other_bi = r[1] if r else None
        a, b = self._region(bi, fname), other._region(other_bi, fname)
        if a is None or b is None or a[1:] != b[1:]:
            return False
        if not a[1]:
            return True
        return memoryview(self.d)[a[0]:a[0] + a[1]] == memoryview(other.d)[b[0]:b[0] + b[1]]


def end_by_sector_table(a, bi, fname):
    off, _cs, fs, fl = a.blocks[bi]
    if not fl & (FLAG_IMPLODE | FLAG_COMPRESS) or fl & FLAG_SINGLE or not fs:
        return None
    p = (a.h.offset + off) & 0xFFFFFFFF
    ntab = (fs + a.sector_size - 1) // a.sector_size + 1 + (1 if fl & 0x04000000 else 0)
    tb = a.d[p:p + ntab * 4]
    if len(tb) < ntab * 4:
        return None
    if fl & FLAG_ENCRYPT:
        tb = _crypt(tb, (key_from_name(fname, off, fs, fl) - 1) & 0xFFFFFFFF)
    offs = struct.unpack_from('<%dI' % ntab, tb, 0)
    if offs[0] != ntab * 4 or any(offs[s] > offs[s + 1] for s in range(ntab - 1)) or p + offs[-1] > len(a.d):
        return None
    return offs[-1]


def cs_unknown(cs, pos, byte_size):
    return cs == 0xFFFFFFFF or pos + cs > byte_size


def _validate_block(a, bi, fname=None, _key=None):
    off, cs, fs, fl = a.blocks[bi]
    if not fl & FLAG_EXISTS:
        return 'invalid', 'block without the exists flag'
    p = (a.h.offset + off) & 0xFFFFFFFF
    cs_known = not cs_unknown(cs, p, len(a.d))
    if not cs_known:
        cs = len(a.d) - p
    comp = bool(fl & (FLAG_IMPLODE | FLAG_COMPRESS))
    if fname is not None and not comp and not fl & FLAG_SINGLE and cs != fs and fs:
        if p + fs > len(a.d):
            return 'invalid', 'data past the end of the file'
        return 'ok', VALID_FOR_GAME_ONLY
    if p + cs > len(a.d):
        return 'invalid', 'data past the end of the file'
    if fs == 0:
        return 'ok', 'empty'
    if fs > FILE_SIZE_CAP:
        return 'invalid', 'the declared size (%d B) is above the limit of %d MB' % (fs, FILE_SIZE_CAP >> 20)
    def raw(i=0, j=None):
        end_pos = cs if j is None else min(j, cs)
        return a.d[p + i:p + end_pos] if i < end_pos else b''

    sec = a.sector_size
    nsec = (fs + sec - 1) // sec
    ntab = nsec + 1 + (1 if fl & 0x04000000 else 0)
    key = None
    if fl & FLAG_ENCRYPT:
        if fname is not None:
            key = key_from_name(fname, off, fs, fl)
        elif fl & FLAG_SINGLE:
            return 'uncertain', 'encrypted, single unit, without a name'
        elif comp and _key is not None:
            key = _key
        elif comp:
            keys = detect_sector_keys(raw(0, 8), sec, ntab * 4)
            if not keys:
                return 'invalid', 'encrypted without a name: no key makes the sector table start at its own size'
            if len(keys) > 1:
                first = None
                for k in keys:
                    r = _validate_block(a, bi, None, _key=k)
                    if r[0] == 'ok':
                        return r
                    first = first or r
                return first
            key = keys[0]
        else:
            key = detect_content_key(raw(0, 8), fs)
            if key is None:
                return 'uncertain', 'encrypted, uncompressed, without a name and without the start of a known format'

    def sector_bytes(chunk, exp_len, s):
        if len(chunk) > exp_len:
            return 'sector %d has %d B, more than the %d of the file' % (s, len(chunk), exp_len)
        if comp and len(chunk) < exp_len:
            try:
                out = decompress_sector(chunk, exp_len)
            except Exception as e:
                if 'not supported' in str(e):
                    raise
                return 'sector %d does not decompress (%s)' % (s, str(e)[:60])
            if len(out) != exp_len:
                return 'sector %d decompresses to %d B, expected %d' % (s, len(out), exp_len)
        return None

    try:
        if fl & FLAG_SINGLE:
            data = _crypt(raw(), key) if key is not None else raw()
            if not comp or cs == fs:
                return ('ok', 'single unit') if cs == fs else ('invalid', 'single unit with %d B of %d' % (cs, fs))
            m = sector_bytes(data, fs, 0)
            return ('invalid', m) if m else ('ok', 'compressed single unit')
        if not comp:
            if cs != fs:
                return 'invalid', 'not compressed with %d B stored for %d' % (cs, fs)
            return 'ok', 'not compressed'
        tb = raw(0, ntab * 4)
        if len(tb) < ntab * 4:
            return 'invalid', 'block smaller than the sector table'
        if key is not None:
            tb = _crypt(tb, (key - 1) & 0xFFFFFFFF)
        offs = struct.unpack_from('<%dI' % ntab, tb, 0)
        if offs[0] != ntab * 4:
            return 'invalid', 'the sector table does not start at its own size (%d, expected %d)' % (offs[0], ntab * 4)
        if any(offs[s] > offs[s + 1] for s in range(ntab - 1)):
            return 'invalid', 'sector table out of order'
        slack = False
        if offs[ntab - 1] != cs and (cs_known or offs[ntab - 1] > cs):
            if fname is None or p + offs[ntab - 1] > len(a.d):
                return 'invalid', 'the sector table ends at %d, the block has %d' % (offs[ntab - 1], cs)
            slack = True
            if offs[ntab - 1] > cs:
                cs = offs[ntab - 1]
        for s in [nsec - 1] + list(range(nsec - 1)):
            chunk = raw(offs[s], offs[s + 1])
            if key is not None:
                chunk = _crypt(chunk, (key + s) & 0xFFFFFFFF)
            m = sector_bytes(chunk, min(sec, fs - s * sec), s)
            if m:
                return 'invalid', m
        return 'ok', VALID_SLACK if slack else '%d sector(s)' % nsec
    except Exception as e:
        return 'uncertain', 'the reader cannot read it: %s' % str(e)[:80]

