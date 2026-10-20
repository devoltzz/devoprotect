# Rewrites a map archive with 512-byte sectors and the best encoder for each sector.
import bz2
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
SECTOR_NEW = 512
TETO = 512 * 1024 * 1024
SLICE = 128
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CACHE = os.path.join(os.path.dirname(HERE), 'cache', 'sector512')
CODIFICADORES = ('auto', 'zopfli', 'libdeflate', 'zlib9', 'zlib6')


import mpqlib as _ML
hash_string = _ML.hashstr
decrypt = _ML.decrypt_bytes
encrypt = _ML.encrypt_bytes


def decompresses(sector_bytes, expected_len=None):
    if not sector_bytes:
        return b''
    as_method, data_bytes = sector_bytes[0], sector_bytes[1:]
    if as_method == 0x02:
        return zlib.decompress(data_bytes)
    if as_method == 0x10:
        return bz2.decompress(data_bytes)
    if as_method == 0x08:
        import pkware
        return pkware.decompress(sector_bytes, expected=expected_len)
    if as_method & 0xC1:
        import mpq_wave
        try:
            return mpq_wave.decompress_sector_chain(sector_bytes, expected_len)
        except mpq_wave.WaveError as e:
            raise SystemExit('sound sector with mask 0x%02x: %s' % (as_method, e))
    raise SystemExit('unsupported compression method: 0x%02x (zlib=0x02, bzip2=0x10, pkware=0x08, '
                     'sound=0x01/0x40/0x80)' % as_method)


def _explode(sector_bytes, expected_len):
    import pkware
    return pkware.decompress(sector_bytes, expected=expected_len)


def read_block(b, off, sector_bytes, fpos, csize, fsize, flags, hash_key=None):
    base = (off + fpos) & 0xFFFFFFFF
    cipher = flags & MPQ_FILE_ENCRYPTED
    if cipher and hash_key is None:
        raise SystemExit('encrypted block at %d: this script does not decrypt it (it needs the file name)' % fpos)
    implode = flags & MPQ_FILE_IMPLODE
    if flags & MPQ_FILE_SINGLE_UNIT:
        data_bytes = b[base:base + csize]
        if cipher:
            data_bytes = decrypt(data_bytes, hash_key)
        if (flags & (MPQ_FILE_COMPRESS | MPQ_FILE_IMPLODE)) and csize < fsize:
            return _explode(data_bytes, fsize) if implode else decompresses(data_bytes, fsize)
        return bytes(data_bytes)
    n = (fsize + sector_bytes - 1) // sector_bytes
    if not (flags & (MPQ_FILE_COMPRESS | MPQ_FILE_IMPLODE)):
        if not cipher:
            return bytes(b[base:base + fsize])
        return b''.join(
            decrypt(b[base + k * sector_bytes : base + min((k + 1) * sector_bytes, fsize)], (hash_key + k) & 0xFFFFFFFF)
            for k in range(n)
        )
    extra = 2 if (flags & MPQ_FILE_SECTOR_CRC) else 1
    table = b[base:base + 4 * (n + extra)]
    if cipher:
        table = decrypt(table, (hash_key - 1) & 0xFFFFFFFF)
    offs = struct.unpack_from('<%dI' % (n + extra), table, 0)
    out = bytearray()
    for i in range(n):
        s = b[base + offs[i]:base + offs[i + 1]]
        if cipher:
            s = decrypt(s, (hash_key + i) & 0xFFFFFFFF)
        expected_len = min(sector_bytes, fsize - i * sector_bytes)
        if len(s) == expected_len:
            out += s
        elif implode:
            out += _explode(s, expected_len)
        else:
            out += decompresses(s, expected_len)
    if len(out) != fsize:
        raise SystemExit('block at %d: %d bytes read, %d expected' % (fpos, len(out), fsize))
    return bytes(out)


SPECIAL_FILES = ('(listfile)', '(attributes)', '(signature)')


def key_from_name(fname, fpos, fsize, flags):
    hash_key = hash_string(fname.replace('/', '\\').split('\\')[-1], 3)
    if flags & MPQ_FILE_FIX_KEY:
        hash_key = ((hash_key + fpos) ^ fsize) & 0xFFFFFFFF
    return hash_key


def _table_closes(offs, n, csize, sector_bytes):
    if offs[0] != 4 * len(offs) or offs[-1] != csize:
        return False
    for k in range(len(offs) - 1):
        if offs[k + 1] < offs[k] or (k < n and offs[k + 1] - offs[k] > sector_bytes):
            return False
    return True


def pairs_of_names(name_list=()):
    pairs = {}
    for fname in tuple(SPECIAL_FILES) + tuple(name_list):
        n = fname.replace('/', '\\')
        pairs.setdefault((hash_string(n, 1), hash_string(n, 2)), fname)
    return pairs


def pointed_to(htab):
    out = {}
    for k in range(len(htab) // 16):
        n1, n2, _loc, _plat, evidence = struct.unpack_from('<IIHHI', htab, k * 16)
        out.setdefault(evidence, set()).add((n1, n2))
    return out


def special_key(b, off, sector_bytes, htab, bi, fpos, csize, fsize, flags, pairs=None, point_at=None):
    if point_at is None:
        point_at = pointed_to(htab).get(bi, set())
    if pairs is None:
        pairs = pairs_of_names()
    candidates = sorted(set(pairs[p] for p in point_at if p in pairs),
                        key=lambda n: (SPECIAL_FILES.index(n) if n in SPECIAL_FILES else len(SPECIAL_FILES), n))
    is_compressed = flags & (MPQ_FILE_COMPRESS | MPQ_FILE_IMPLODE)
    for fname in candidates:
        hash_key = key_from_name(fname, fpos, fsize, flags)
        if flags & MPQ_FILE_SINGLE_UNIT:
            if is_compressed and csize < fsize:
                try:
                    if len(read_block(b, off, sector_bytes, fpos, csize, fsize, flags, hash_key)) != fsize:
                        continue
                except (Exception, SystemExit):
                    continue
            return fname, hash_key
        if not is_compressed:
            return fname, hash_key
        n = (fsize + sector_bytes - 1) // sector_bytes
        m = n + (2 if flags & MPQ_FILE_SECTOR_CRC else 1)
        if 4 * m > csize:
            continue
        base = (off + fpos) & 0xFFFFFFFF
        offs = struct.unpack('<%dI' % m, decrypt(b[base:base + 4 * m], (hash_key - 1) & 0xFFFFFFFF))
        if _table_closes(offs, n, csize, sector_bytes):
            return fname, hash_key
    return None


def header_text(b):
    import mpqlib
    h, _skipped = mpqlib.find_header(b)
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
    data_bytes, code_part, margem = job[:3]
    sector_bytes = job[3] if len(job) > 3 else SECTOR_NEW
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


def encrypt_block(data_bytes, hash_key, fsize, flags):
    if flags & MPQ_FILE_COMPRESS:
        n = (fsize + SECTOR_NEW - 1) // SECTOR_NEW
        m = n + 1
        offs = struct.unpack_from('<%dI' % m, data_bytes, 0)
        out = bytearray(data_bytes)
        out[0:4 * m] = encrypt(bytes(data_bytes[0:4 * m]), (hash_key - 1) & 0xFFFFFFFF)
        for k in range(n):
            a, b = offs[k], offs[k + 1]
            out[a:b] = encrypt(bytes(data_bytes[a:b]), (hash_key + k) & 0xFFFFFFFF)
        return bytes(out)
    n = (fsize + SECTOR_NEW - 1) // SECTOR_NEW
    out = bytearray(data_bytes)
    for k in range(n):
        a = k * SECTOR_NEW
        b = min(a + SECTOR_NEW, fsize)
        out[a:b] = encrypt(bytes(data_bytes[a:b]), (hash_key + k) & 0xFFFFFFFF)
    return bytes(out)


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


def _update_attributes(htab, hcount, bcount, content, replaced, details, log):
    import mpqadd
    ha, hb = hash_string(mpqadd.ATTRIBUTES, 1), hash_string(mpqadd.ATTRIBUTES, 2)
    hash_entries = [k for k in range(hcount) if struct.unpack_from('<II', htab, k * 16) == (ha, hb)
                    and struct.unpack_from('<I', htab, k * 16 + 12)[0] < bcount]
    block_list = sorted(set(struct.unpack_from('<I', htab, k * 16 + 12)[0] for k in hash_entries) & set(content))
    if not block_list:
        return htab, None
    bi = block_list[0]
    new = mpqadd.attributes_with(content[bi], bcount, [(i, content[i]) for i in replaced])
    if new is not None:
        content[bi] = new
        details['hero_attributes'] = 'redone: CRC32/MD5 of %d rewritten block(s)' % len(replaced)
        log('  (attributes): CRC32/MD5 redone for the %d rewritten BLPs' % len(replaced))
        return htab, None
    htab = bytearray(htab)
    for k in hash_entries:
        struct.pack_into('<I', htab, k * 16 + 12, 0xFFFFFFFE)
    del content[bi]
    details['hero_attributes'] = 'removed (a format that cannot be redone; stale, the game refuses the map)'
    log('  (attributes): not in the StormLib format, removed (stale, the game refuses the map)')
    return htab, bi


def protect_bytes(
    b,
    blp=False,
    encoder='auto',
    margem=8,
    dedup=True,
    raw_data=False,
    cache=DEFAULT_CACHE,
    workers=None,
    to_verify=True,
    stats=None,
    prune=False,
    log=_log,
    orphan_blocks=False,
    no_listfile=False,
    variant=(),
    name_list=(),
    cipher=(),
):
    t0 = time.time()
    details = stats if stats is not None else {}
    if set(variant) - {'header_text', 'high-sector', 'bit31'}:
        raise SystemExit('--variant=%s: valid values are header,high-sector,bit31' % sorted(variant))
    code_part = resolve_encoder(encoder)
    enc_signature = signature(code_part, margem)
    ca = Cache(cache)
    off, field_list = header_text(b)
    magic, hsize, asize, ver, bshift, hoff, boff, hcount, bcount = field_list
    if ver != 0:
        raise SystemExit(
            'MPQ version %d: this script only handles version 1 (the format of Warcraft III maps)' % (ver + 1)
        )
    import mpqlib
    sector_bytes = mpqlib.header_sector(bshift)
    log('input: %d bytes; header at 0x%x, sector %d, %d blocks; encoder %s%s%s' % (
        len(b), off, sector_bytes, bcount, code_part, ', blp' if blp else '', ', cache ' + cache if cache else ''))
    hpos, bpos = (off + hoff) & 0xFFFFFFFF, (off + boff) & 0xFFFFFFFF
    htab = decrypt(b[hpos:hpos + hcount * 16], hash_string('(hash table)', 3))
    btab = bytearray(decrypt(b[bpos:bpos + bcount * 16], hash_string('(block table)', 3)))
    in_use = None
    if orphan_blocks or no_listfile:
        htab = bytearray(htab)
        if no_listfile:
            ha, hb = hash_string('(listfile)', 1), hash_string('(listfile)', 2)
            for k in range(hcount):
                x, y, _l, _p, bi = struct.unpack_from('<IIHHI', htab, k * 16)
                if x == ha and y == hb and bi < bcount:
                    struct.pack_into('<I', htab, k * 16 + 12, 0xFFFFFFFE)
        in_use = set(
            bi for bi in (struct.unpack_from('<I', htab, k * 16 + 12)[0] for k in range(hcount)) if bi < bcount
        )
        details['orphaned_blocks'] = sum(
            1
            for i in range(bcount)
            if struct.unpack_from('<I', btab, i * 16 + 12)[0] & MPQ_FILE_EXISTS and i not in in_use
        )
        log('  %d orphan block(s) (no entry in the hash table) will not be written%s' % (
            details['orphaned_blocks'], '; (listfile) removed' if no_listfile else ''))

    content = {}
    deciphered = {}
    pairs = pairs_of_names(name_list)
    if cipher is True:
        encrypt_names = list(dict.fromkeys(list(name_list) + list(SPECIAL_FILES)))
    elif cipher:
        encrypt_names = list(cipher)
    else:
        encrypt_names = []
    encrypt_pairs = pairs_of_names(encrypt_names) if encrypt_names else {}
    key_of = {}
    encrypt_skipped = 0
    by_block = None
    for i in range(bcount):
        fpos, csize, fsize, flags = struct.unpack_from('<IIII', btab, i * 16)
        if flags & MPQ_FILE_EXISTS and (in_use is None or i in in_use):
            hash_key = None
            if flags & MPQ_FILE_ENCRYPTED:
                if by_block is None:
                    by_block = pointed_to(htab)
                finding = special_key(b, off, sector_bytes, htab, i, fpos, csize, fsize, flags, pairs=pairs,
                                      point_at=by_block.get(i, set()))
                if finding:
                    deciphered[i], hash_key = finding
            content[i] = read_block(b, off, sector_bytes, fpos, csize, fsize, flags, hash_key)
            if encrypt_pairs:
                if by_block is None:
                    by_block = pointed_to(htab)
                all_items = by_block.get(i, set())
                names_i = sorted(set(encrypt_pairs[p] for p in all_items if p in encrypt_pairs))
                if names_i and len(names_i) == len(all_items):
                    ks = set(key_from_name(n, 0, 0, 0) for n in names_i)
                    if len(ks) == 1:
                        key_of[i] = ks.pop()
                    else:
                        encrypt_skipped += 1
                else:
                    encrypt_skipped += 1
    if key_of:
        details['encrypted_count'] = len(key_of)
        details['encrypt_skipped'] = encrypt_skipped
        log('  %d block(s) encrypted by name (%d without a safe key: unknown name or two keys)'
            % (len(key_of), encrypt_skipped))
    log('  %d live blocks, %d bytes uncompressed (%.1f s)' % (len(content), sum(map(len, content.values())),
                                                              time.time() - t0))
    if deciphered:
        details['deciphered'] = dict((str(i), fname) for i, fname in sorted(deciphered.items()))
        log('  encrypted blocks decrypted by name: %s' % ', '.join(
            '%s (block %d)' % (fname, i) for i, fname in sorted(deciphered.items())))
    removed = set()
    pool = open_pool(workers or os.cpu_count() or 1)
    try:
        details['blp_rewritten'] = []
        details['blp_reasons'] = {}
        if blp:
            import blp_huffman
            blp_signature = blp_huffman.VERSION
            targets = [i for i, c in content.items() if _e_blp_jpeg(c)]
            unique_names = {}
            for i in targets:
                unique_names.setdefault(hashlib.sha1(content[i]).hexdigest(), i)
            resultado = {}
            missing_items = []
            for h, i in unique_names.items():
                finding = ca.read_data('blp', _key(content[i], blp_signature))
                if finding is None:
                    missing_items.append(h)
                elif finding.startswith(b'MANTIDO:'):
                    resultado[h] = (None, finding[8:].decode('utf-8', 'replace'))
                else:
                    resultado[h] = (finding, 'ok (cache)')
            t1 = time.time()
            item_entries = [content[unique_names[h]] for h in missing_items]
            outputs = pool.imap(_blp_um, item_entries, chunksize=2) if pool else map(_blp_um, item_entries)
            for k, (h, (new, why)) in enumerate(zip(missing_items, outputs)):
                resultado[h] = (new, why)
                orig = content[unique_names[h]]
                ca.save('blp', _key(orig, blp_signature), new if new is not None else b'MANTIDO:' + why.encode())
                if (k + 1) % 500 == 0:
                    log('  blp: %d/%d (%.0f s)' % (k + 1, len(missing_items), time.time() - t1))
            before = after_diag = 0
            for i in targets:
                new, why = resultado[hashlib.sha1(content[i]).hexdigest()]
                reason_key = why.split(' (')[0].split(',')[0]
                details['blp_reasons'][reason_key] = details['blp_reasons'].get(reason_key, 0) + 1
                if new is not None:
                    before += len(content[i])
                    after_diag += len(new)
                    content[i] = new
                    details['blp_rewritten'].append(i)
            log(
                '  blp: %d of %d BLP1 JPEG rewritten, %d -> %d bytes (%+.2f%%); %s'
                % (
                    len(details['blp_rewritten']),
                    len(targets),
                    before,
                    after_diag,
                    100.0 * (after_diag - before) / max(1, before),
                    ', '.join('%s: %d' % kv for kv in sorted(details['blp_reasons'].items())),
                )
            )
            if details['blp_rewritten']:
                htab, stripped = _update_attributes(
                    htab, hcount, bcount, content, details['blp_rewritten'], details, log
                )
                if stripped is not None:
                    removed.add(stripped)

        sha = {i: hashlib.sha1(c).hexdigest() for i, c in content.items()}
        first = {}
        for i in sorted(content):
            first.setdefault(sha[i] if dedup else i, i)
        unique_names = sorted(first.values())
        block_entry = {}
        pend = []
        for i in unique_names:
            finding = ca.read_data('block_list', _key(content[i], enc_signature))
            if finding is not None:
                block_entry[i] = finding
            else:
                pend.append(i)
        n_set = sum((len(content[i]) + SECTOR_NEW - 1) // SECTOR_NEW for i in pend)
        log('  pack: %d unique files, %d from the cache, %d to compress (%d sectors)' % (
            len(unique_names), len(unique_names) - len(pend), len(pend), n_set))
        t2 = time.time()
        jobs = []
        owner = []
        for i in pend:
            c = content[i]
            for a in range(0, len(c), SLICE * SECTOR_NEW):
                jobs.append((c[a:a + SLICE * SECTOR_NEW], code_part, margem))
                owner.append(i)
            if not c:
                block_entry[i] = build_block([])
        outputs = pool.imap(_slice, jobs, chunksize=4) if pool else map(_slice, jobs)
        pieces = {}
        remaining_count = {}
        for i in owner:
            remaining_count[i] = remaining_count.get(i, 0) + 1
        done_list = 0
        for i, res in zip(owner, outputs):
            pieces.setdefault(i, []).extend(res)
            remaining_count[i] -= 1
            if remaining_count[i] == 0:
                block_entry[i] = build_block(pieces.pop(i))
                ca.save('block_list', _key(content[i], enc_signature), block_entry[i])
            done_list += 1
            if done_list % 2000 == 0:
                log('  ... %d/%d slices (%.0f s)' % (done_list, len(jobs), time.time() - t2))
        for i in pend:
            if i not in block_entry:
                block_entry[i] = build_block([])
                ca.save('block_list', _key(content[i], enc_signature), block_entry[i])
    finally:
        if pool:
            pool.close()
            pool.join()

    base = off
    if 'bit31' in variant:
        inv_slot = (bcount * 16 + 0x1FF) & ~0x1FF
        off = base + inv_slot
        details['variant_bit31'] = {'table_at': base, 'header_at': off, 'inv_slot': inv_slot}
    out = bytearray(b[:min(len(b), off)])
    if len(out) < off:
        out += bytearray(off - len(out))
    if off > base:
        out[base:off] = bytearray(off - base)
    out += b'\x00' * 0x20
    new_one = bytearray(btab)
    pos_of = {}
    n_raw = n_dup = dup_saved = 0
    for i in sorted(content):
        fpos, csize, fsize, flags = struct.unpack_from('<IIII', btab, i * 16)
        c = content[i]
        u = first[sha[i] if dedup else i]
        new_flags = (flags | MPQ_FILE_COMPRESS) & ~(MPQ_FILE_SINGLE_UNIT | MPQ_FILE_SECTOR_CRC | MPQ_FILE_IMPLODE |
                                                    MPQ_FILE_ENCRYPTED | MPQ_FILE_FIX_KEY)
        key_i = key_of.get(i)
        if key_i is not None:
            new_flags |= MPQ_FILE_ENCRYPTED
        data_bytes = block_entry[u]
        if raw_data and len(data_bytes) >= len(c):
            data_bytes = c
            new_flags &= ~MPQ_FILE_COMPRESS
        if key_i is not None:
            data_bytes = encrypt_block(data_bytes, key_i, len(c), new_flags)
        if u != i and (u, new_flags, key_i or 0) in pos_of:
            pos, sz = pos_of[(u, new_flags, key_i or 0)]
            n_dup += 1
            dup_saved += sz
        else:
            pos, sz = len(out) - off, len(data_bytes)
            out += data_bytes
            pos_of[(u, new_flags, key_i or 0)] = (pos, sz)
            if not new_flags & MPQ_FILE_COMPRESS:
                n_raw += 1
        struct.pack_into('<IIII', new_one, i * 16, pos, sz, len(c), new_flags)
    for i in range(bcount):
        if i not in content and (in_use is not None or i in removed):
            struct.pack_into('<IIII', new_one, i * 16, 0, 0, 0, 0)
    n_hoff = len(out) - off
    out += encrypt(bytes(htab), hash_string('(hash table)', 3))
    if 'bit31' in variant:
        tb = encrypt(bytes(new_one), hash_string('(block table)', 3))
        out[base:base + len(tb)] = tb
        n_boff = (base - off) & 0xFFFFFFFF
    else:
        n_boff = len(out) - off
        out += encrypt(bytes(new_one), hash_string('(block table)', 3))
    v_hsize, v_sector, v_boff = 0x20, 0, n_boff
    if variant:
        if 'header_text' in variant:
            v_hsize = 0x21
        if 'high-sector' in variant:
            v_sector = 0x0100
        details['variant'] = sorted(variant)
        log('variant: %s (MALFORMED mark; at sector 512 StormLib already refuses the file: no extra barrier)'
            % ', '.join(sorted(variant)))
    struct.pack_into(HDR, out, off, b'MPQ\x1a', v_hsize, len(out) - off, 0, v_sector, n_hoff, v_boff, hcount, bcount)
    out = bytes(out)
    details.update({'entry': len(b), 'output': len(out), 'encoder': code_part, 'signature': enc_signature,
                    'duplicates': n_dup, 'duplicates_bytes': dup_saved, 'uncompressed': n_raw,
                    'block_list': len(content), 'encrypted_count': len(key_of), 'encrypt_skipped': encrypt_skipped,
                    'seconds': round(time.time() - t0, 1)})
    log('output: %d bytes (%+.1f%% over the input); %d duplicates written once (-%d bytes)%s; %.0f s' % (
        len(out), 100.0 * (len(out) - len(b)) / len(b), n_dup, dup_saved,
        ', %d uncompressed' % n_raw if raw_data else '', time.time() - t0))
    if len(out) > TETO:
        log('WARNING: %d bytes, above the 512 MiB ceiling (%d): the map disappears from the lobby' % (len(out), TETO))

    if to_verify:
        off2, fields2 = header_text(out)
        if fields2[4] & 0xFF != 0:
            raise SystemExit(
                'CHECK FAILED: the sector exponent of the output is not 0 (the low byte, the one that counts)'
            )
        boff2 = (off2 + fields2[6]) & 0xFFFFFFFF
        btab2 = decrypt(out[boff2:boff2 + fields2[8] * 16], hash_string('(block table)', 3))
        bad_ones = 0
        for i, c in content.items():
            fpos, csize, fsize, flags = struct.unpack_from('<IIII', btab2, i * 16)
            encrypted = bool(flags & MPQ_FILE_ENCRYPTED)
            if encrypted != (i in key_of):
                bad_ones += 1
                continue
            if hashlib.sha1(read_block(out, off2, 512, fpos, csize, fsize, flags,
                                       key_of.get(i))).hexdigest() != sha[i]:
                bad_ones += 1
        if bad_ones:
            raise SystemExit('CHECK FAILED: %d block(s) different from expected' % bad_ones)
        log('check: %d blocks read back from the output, all as expected%s' % (
            len(content), ' (%d encrypted by name)' % len(key_of) if key_of else ''))
    if variant:
        import mpqlib
        h2 = mpqlib.find_header(out, fname='protected.w3x')[0]
        m2 = mpqlib.is_malformed(h2)
        combined = ' '.join(m2)
        still_missing = [v for v in variant if (v == 'header_text' and 'dwHeaderSize' not in combined)
                         or (v == 'high-sector' and 'wSectorSize' not in combined)
                         or (v == 'bit31' and 'dwBlockTablePos' not in combined)]
        if still_missing:
            raise SystemExit('VARIANT FAILED: the diagnosis does not report %s (the mark was not written): %s'
                             % (still_missing, m2))
        details['variant_diagnostic'] = m2
        log(
            'variant: the MPQ_FLAG_MALFORMED diagnosis reports %s (the mark; at sector 512 StormLib does not even open it)'
            % m2
        )
    details['cache_used'] = len(ca.in_use)
    if prune:
        n, sz = ca.prune()
        details['cache_pruned'] = n
        log('cache: %d entries this assembly did not use deleted (%d bytes)' % (n, sz))
    return out


def _cut_gate(htab, btab, bcount):
    hcount = len(htab) // 16
    if hcount < 2:
        raise SystemExit('cut-hash: the hash table has %d entry(ies), nothing to cut' % hcount)
    bi = struct.unpack_from('<I', htab, (hcount - 1) * 16 + 12)[0]
    bi_m = bi & 0x0FFFFFFF
    if bi < 0xFFFFFFFE and bi_m < bcount and struct.unpack_from('<I', btab, bi_m * 16 + 12)[0] & MPQ_FILE_EXISTS:
        raise SystemExit('cut-hash: the LAST entry of the hash table points at the live block %d (the cut '
                         'would eat a real file): use another map' % bi_m)


def cut_hash(b, to_verify=True, stats=None, log=_log):
    t0 = time.time()
    details = stats if stats is not None else {}
    import mpqlib
    off, field_list = header_text(b)
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


def _same_file(a, b):
    return os.path.normcase(os.path.realpath(os.path.abspath(a))) == os.path.normcase(
        os.path.realpath(os.path.abspath(b))
    )


def protect(entry, output, to_verify=True, **options):
    if _same_file(entry, output):
        raise SystemExit('the output cannot be the input map itself')
    b = open(entry, 'rb').read()
    details = {}
    out = protect_bytes(b, to_verify=to_verify, stats=details, **options)
    with open(output, 'wb') as fh:
        fh.write(out)
    print('written: %s (%d bytes, %.1f MiB)' % (output, len(out), len(out) / 1048576.0))
    return details
