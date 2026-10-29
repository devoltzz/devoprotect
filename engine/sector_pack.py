# The MPQ pieces of a map that the recipe shares: the sector codec and the hash table cut.
import hashlib
import os
import re
import struct
import sys
import time
import zlib


try:
    import zopfli.zlib as _zopfli
except ImportError:
    _zopfli = None
try:
    import deflate as _libdeflate
except ImportError:
    _libdeflate = None

MPQ_FILE_IMPLODE = 0x00000100
MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_ENCRYPTED = 0x00010000
MPQ_FILE_FIX_KEY = 0x00020000
MPQ_FILE_SINGLE_UNIT = 0x01000000
MPQ_FILE_SECTOR_CRC = 0x04000000
MPQ_FILE_EXISTS = 0x80000000
HDR = '<4sIIHHIIII'
SLICE = 128
CODIFICADORES = ('auto', 'zopfli', 'libdeflate', 'zlib9', 'zlib6')


import mpqlib as _ML
hash_string = _ML.hashstr
decrypt = _ML.decrypt_bytes
encrypt = _ML.encrypt_bytes


SPECIAL_FILES = ('(listfile)', '(attributes)', '(signature)')


def key_from_name(fname, fpos, fsize, flags):
    hash_key = hash_string(fname.replace('/', '\\').split('\\')[-1], 3)
    if flags & MPQ_FILE_FIX_KEY:
        hash_key = ((hash_key + fpos) ^ fsize) & 0xFFFFFFFF
    return hash_key


def header_text(b, fname=None):
    import mpqlib
    h, _skipped = mpqlib.find_header(b, fname=fname)
    if h is None:
        raise SystemExit('MPQ signature not found (mpqlib.find_header)')
    return h.offset, struct.unpack_from(HDR, b, h.offset)


_NATIVE_SOUND = [None]


def _native_codec(code_part):
    if code_part not in ('zopfli', 'zlib9') or _libdeflate is not None:
        return None
    if _zopfli is not None and 'zlib-ng' in zlib.ZLIB_RUNTIME_VERSION:
        return None
    if _NATIVE_SOUND[0] is None or sys.platform == 'emscripten':
        try:
            import sector512_native
            _NATIVE_SOUND[0] = sector512_native.load_data() or False
        except Exception:
            _NATIVE_SOUND[0] = False
    return _NATIVE_SOUND[0] or None


def resolve_encoder(code_part):
    if code_part not in CODIFICADORES:
        raise SystemExit('--codificador=%s: use one of %s' % (code_part, ', '.join(CODIFICADORES)))
    if code_part == 'auto':
        code_part = 'zopfli' if (_zopfli or _native_codec('zopfli')) else 'libdeflate' if _libdeflate else 'zlib9'
        if code_part != 'zopfli':
            print(
                'NOTE: zopfli is not installed (pip install zopfli deflate): using %s, the map comes out bigger'
                % code_part
            )
    if code_part == 'zopfli' and not (_zopfli or _native_codec('zopfli')):
        raise SystemExit('--codificador=zopfli without the zopfli package (pip install zopfli)')
    if code_part == 'libdeflate' and not _libdeflate:
        raise SystemExit('--codificador=libdeflate without the deflate package (pip install deflate)')
    return code_part


def signature(code_part, margem):
    def version_num(pkg):
        try:
            from importlib.metadata import version
            return version(pkg)
        except Exception:
            return '?'
    if _native_codec(code_part):
        import sector512_native
        return '|'.join(['setor512/2', code_part, 'native', sector512_native.VERSION] +
                        (['margem=%d' % margem] if code_part == 'zopfli' else []))
    pieces = ['setor512/2', code_part, 'zlib=%s' % zlib.ZLIB_RUNTIME_VERSION]
    if code_part in ('zopfli', 'libdeflate'):
        pieces.append('deflate=%s' % version_num('deflate'))
    if code_part == 'zopfli':
        pieces += ['zopfli=%s' % version_num('zopfli'), 'margem=%d' % margem]
    return '|'.join(pieces)


def encode_sector(s, code_part, margem=8):
    L = len(s)
    nat = _native_codec(code_part) if L else None
    if nat:
        r = nat(s, L, margem, code_part)
        if r is not None:
            return r[0]
    if code_part == 'zlib6':
        z = zlib.compress(s, 6)
    else:
        z = zlib.compress(s, 9)
        if code_part in ('zopfli', 'libdeflate') and _libdeflate:
            z2 = _libdeflate.zlib_compress(s, 12)
            if len(z2) < len(z):
                z = z2
        if code_part == 'zopfli' and (margem < 0 or 1 + len(z) < L + margem):
            z3 = _zopfli.compress(s, numiterations=15, blocksplitting=False)
            if len(z3) < len(z):
                z = z3
    return b'\x02' + z if 1 + len(z) < L else s


def _slice(job):
    if len(job) < 4:
        raise ValueError(
            '_slice: (data, encoder, margin, sector); the default 512 sector left with the package (29/10/2026)'
        )
    data_bytes, code_part, margem, sector_bytes = job[:4]
    nat = _native_codec(code_part)
    if nat:
        r = nat(data_bytes, sector_bytes, margem, code_part)
        if r is not None:
            return r
    return [
        encode_sector(data_bytes[i : i + sector_bytes], code_part, margem)
        for i in range(0, len(data_bytes), sector_bytes)
    ]


class _Threads:
    def __init__(self, n):
        from concurrent.futures import ThreadPoolExecutor
        self.ex = ThreadPoolExecutor(n)

    def imap(self, fn, item_entries, chunksize=1):
        return self.ex.map(fn, item_entries)

    imap_unordered = imap

    def close(self):
        self.ex.shutdown(wait=True)

    def join(self):
        pass


def open_pool(n):
    if n <= 1 or sys.platform == 'emscripten':
        return None
    if getattr(sys, 'frozen', False):
        return _Threads(n)
    import multiprocessing as mp
    return mp.Pool(n)


def build_block(pieces):
    offs = []
    pos = 4 * (len(pieces) + 1)
    for p in pieces:
        offs.append(pos)
        pos += len(p)
    offs.append(pos)
    return struct.pack('<%dI' % len(offs), *offs) + b''.join(pieces)


class Cache:
    def __init__(self, folder):
        self.folder = folder
        self.in_use = set()

    def _path_of(self, inv_slot, hash_key):
        return os.path.join(self.folder, inv_slot, hash_key[:2], hash_key)

    ATTEMPTS = 5

    def read_data(self, inv_slot, hash_key):
        if not self.folder:
            return None
        p = self._path_of(inv_slot, hash_key)
        for k in range(self.ATTEMPTS):
            if not os.path.exists(p):
                return None
            try:
                with open(p, 'rb') as fh:
                    data_bytes = fh.read()
            except PermissionError:
                time.sleep(0.02 * (k + 1))
                continue
            self.in_use.add(os.path.normcase(os.path.abspath(p)))
            return data_bytes
        return None

    def save(self, inv_slot, hash_key, data_bytes):
        if not self.folder:
            return
        p = self._path_of(inv_slot, hash_key)
        mark = os.path.normcase(os.path.abspath(p))
        if os.path.isfile(p):
            self.in_use.add(mark)
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + '.tmp%d' % os.getpid()
        with open(tmp, 'wb') as fh:
            fh.write(data_bytes)
        for k in range(self.ATTEMPTS):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if os.path.isfile(p):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    break
                if k == self.ATTEMPTS - 1:
                    raise
                time.sleep(0.02 * (k + 1))
        self.in_use.add(mark)

    def prune(self):
        if not self.folder or not os.path.isdir(self.folder):
            return 0, 0
        n = sz = 0
        for root, _, files_ in os.walk(self.folder):
            for f in files_:
                if not re.fullmatch(r'[0-9a-f]{40}', f) or os.path.basename(root) != f[:2]:
                    continue
                p = os.path.normcase(os.path.abspath(os.path.join(root, f)))
                if p not in self.in_use:
                    sz += os.path.getsize(p)
                    os.remove(p)
                    n += 1
        return n, sz


def _key(data_bytes, enc_signature):
    return hashlib.sha1(data_bytes + b'\0' + enc_signature.encode('ascii')).hexdigest()


def _log(*a):
    print(*a, flush=True)


def _blp_um(content):
    import blp_huffman
    return blp_huffman.otimiza_blp(content)


def _e_blp_jpeg(c):
    return len(c) > 160 and c[:8] == b'BLP1\x00\x00\x00\x00'


def _cut_gate(htab, btab, bcount):
    hcount = len(htab) // 16
    if hcount < 2:
        raise SystemExit('cut-hash: the hash table has %d entry(ies), nothing to cut' % hcount)
    bi = struct.unpack_from('<I', htab, (hcount - 1) * 16 + 12)[0]
    bi_m = bi & 0x0FFFFFFF
    if bi < 0xFFFFFFFE and bi_m < bcount and struct.unpack_from('<I', btab, bi_m * 16 + 12)[0] & MPQ_FILE_EXISTS:
        raise SystemExit('cut-hash: the LAST entry of the hash table points at the live block %d (the cut '
                         'would eat a real file): use another map' % bi_m)


def cut_hash(b, to_verify=True, stats=None, log=_log, fname=None):
    t0 = time.time()
    details = stats if stats is not None else {}
    import mpqlib
    off, field_list = header_text(b, fname=fname)
    magic, hsize, asize, ver, bshift, hoff, boff, hcount, bcount = field_list
    if ver != 0:
        raise SystemExit('cut-hash: MPQ version %d: this cut only handles version 1' % (ver + 1))
    if hcount & (hcount - 1):
        raise SystemExit('cut-hash: the hash table is not a power of 2 (%d entries): the game probes with '
                         '`size - 1`' % hcount)
    hpos, bpos = (off + hoff) & 0xFFFFFFFF, (off + boff) & 0xFFFFFFFF
    if bpos != hpos + hcount * 16:
        raise SystemExit('cut-hash: the block table does not come right after the hash table (hash at 0x%x, block at '
                         '0x%x): run it on an MPQ repacked by this script' % (hpos, bpos))
    btab = decrypt(b[bpos:], hash_string('(block table)', 3))
    htab = decrypt(b[hpos:bpos], hash_string('(hash table)', 3))
    _cut_gate(htab, btab, bcount)
    reg_hash = bytes(b[hpos:bpos])
    reg_bt = bytes(b[bpos:])
    log('cut-hash: %d declared entries, the last one (slot %d) dead: the BT goes where the hash was and '
        'the hash stays at the end with (hash_n-1)*16' % (hcount, hcount - 1))
    new = bytearray(b[:hpos])
    new += reg_bt
    hash_pos_rel = len(new) - off
    new += reg_hash[:-16]
    struct.pack_into('<I', new, off + 0x08, len(new) - off)
    struct.pack_into('<I', new, off + 0x10, hash_pos_rel)
    struct.pack_into('<I', new, off + 0x14, hpos - off)
    out = bytes(new)
    details.update({'entry': len(b), 'output': len(out), 'hash_n': hcount,
                    'physical': (hcount - 1) * 16, 'cut_slot': hcount - 1,
                    'seconds': round(time.time() - t0, 2)})
    if to_verify:
        hd2 = mpqlib.find_header(out, fname='cut.w3x')[0]
        if hd2 is None or hd2.offset != off:
            raise SystemExit('CHECK FAILED: the header of the cut map is not found by the scan (or it moved)')
        if hd2.hash_n != hcount or hd2.hash_pos != (hpos + len(reg_bt)) - off:
            raise SystemExit('CHECK FAILED: the header of the cut map says hash_n %d (was %d) or hash at 0x%x '
                             '(was %d)' % (hd2.hash_n, hcount, hd2.hash_pos, (hpos + len(reg_bt)) - off))
        _forbidden = sorted(set(range(off + 0x08, off + 0x0C)) | set(range(off + 0x10, off + 0x14))
                            | set(range(off + 0x14, off + 0x18)))
        if hd2.hash_n != hcount or hd2.hash_pos != (hpos + len(reg_bt)) - off:
            raise SystemExit('CHECK FAILED: the header of the cut map says hash_n %d (was %d) or hash at 0x%x '
                             '(was %d)' % (hd2.hash_n, hcount, hd2.hash_pos, (hpos + len(reg_bt)) - off))
        data_region, bt_region, hash_region = out[off + 0x20:hpos], out[hpos:off + hd2.hash_pos], \
            out[off + hd2.hash_pos:]
        diff = [i for i in range(hpos) if out[i] != b[i]]
        if not set(diff) <= set(_forbidden):
            raise SystemExit('CHECK FAILED: the header changed outside the three fields of the surgery: %s'
                             % [hex(i) for i in diff[:8]])
        if hd2.archive_size != len(out) - off or hd2.block_abs != hpos:
            raise SystemExit('CHECK FAILED: the header of the cut map says size %d (was %d) or block at '
                             '0x%x (was 0x%x)' % (hd2.archive_size, len(out) - off, hd2.block_abs, hpos))
        if data_region != b[off + 0x20:hpos] or bt_region != reg_bt or hash_region != reg_hash[:-16]:
            raise SystemExit('CHECK FAILED: the surgery moved bytes beyond the table swap')
        if len(hash_region) != (hcount - 1) * 16:
            raise SystemExit('CHECK FAILED: the physical cut hash is %d B, not (hash_n-1)*16'
                             % len(hash_region))
        ht2 = decrypt(hash_region, hash_string('(hash table)', 3))
        if ht2 != htab[:len(ht2)]:
            raise SystemExit('CHECK FAILED: the symbols of the hash table would change meaning with the cut')
        log('check: the surgery was checked byte by byte (data intact, BT in place, hash at the end with '
            '%d physical)' % (hcount - 1))
    return out

