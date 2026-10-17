# Makes a map smaller without losing anything: recompression, lossless BLP, duplicates once.
import collections
import contextlib
import hashlib
import io
import multiprocessing
import os
import struct
import sys
import time
import zlib

import mpqlib as M
import mpqread
import sector_pack


SHIFT = 7
MAX_SHIFT = 15
FREE, DELETED = 0xFFFFFFFF, 0xFFFFFFFE
MASK = mpqread.BLOCK_MASK
F_EXISTS = mpqread.FLAG_EXISTS
F_COMPRESS = mpqread.FLAG_COMPRESS
F_ENCRYPT = mpqread.FLAG_ENCRYPT
F_SINGLE = mpqread.FLAG_SINGLE
F_IMPLODE = mpqread.FLAG_IMPLODE
F_CRC = 0x04000000
SPECIAL = ('(listfile)', '(attributes)', '(signature)')
MAP_INFO = ('war3map.w3i', 'war3campaign.w3f')
KINDS = (('models', ('.mdx', '.mdl')),
         ('textures', ('.blp', '.tga', '.dds', '.png', '.jpg', '.jpeg')),
         ('sounds', ('.wav', '.mp3', '.flac', '.ogg')),
         ('scripts', ('.j', '.lua', '.ai', '.pld')),
         ('data', ('.w3e', '.w3i', '.wtg', '.wct', '.wts', '.w3u', '.w3t', '.w3a', '.w3b', '.w3d', '.w3h', '.w3q',
                   '.doo', '.w3r', '.w3c', '.w3s', '.shd', '.mmp', '.wpm', '.imp', '.slk', '.txt', '.fdf', '.toc',
                   '.ini', '.w3o')))
SAMPLE = 4 << 20
OPTIONS = {'recompress': True, 'blp': True, 'dedup': True}
POOL_PACK = {'zopfli': 256 << 10}
POOL_PACK_OTHER = 16 << 20
POOL_BLP = 128 << 10
BLP_WHY = {'not a BLP1 JPEG': 'not a BLP1 JPEG', 'no mipmap': 'no mipmap',
           'layout not contiguous': 'mipmaps not in order', 'sobra no fim': 'extra bytes at the end',
           'decodificacao': 'does not decode', 'not baseline': 'not baseline JPEG (progressive or other)',
           'no DHT': 'no Huffman table', 'DHT parte no cabecalho': 'tables in the header and in the mipmaps',
           'the header is no longer a common one': 'the shared header would differ',
           'PIXEL DIFERENTE': 'the pixels would differ', 'did not get smaller': 'not smaller'}


def _nothing(*_a, **_k):
    pass


def _kind(name, data=None):
    if name:
        low = name.lower()
        if low in SPECIAL:
            return 'data'
        ext = os.path.splitext(low)[1]
    else:
        import carver
        ext = carver.identify(data or b'')[1]
    return next((k for k, exts in KINDS if ext in exts), 'other')


def _open(path):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return mpqread.Archive(path), None
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return None, 'The map does not open (%s).' % (str(e) or type(e).__name__)


def _layout(a):
    hn = a.h.hash_n
    if a.h.version != 0:
        return 'The archive header is not a normal MPQ v1 header (a protected map): run "Fix map" on it first.'
    if hn != a.hash_n or hn != a.hash_n_read or not hn or hn & (hn - 1):
        return 'The hash table does not fit in the file (a protected map): run "Fix map" on it first.'
    if a.h.block_n != a.block_n or len(a.bt) // 4 < a.block_n:
        return 'The block table does not fit in the file (a protected map): run "Fix map" on it first.'
    return None


def _names(a):
    import mpq_check
    import mpqnames
    out = {}
    names = mpqread.listfile_names(a)
    seen = set()
    for n in list(SPECIAL) + list(MAP_INFO) + list(mpqnames.BASE_NAMES) + list(mpq_check.PROBES) + names:
        if n.lower() in seen:
            continue
        seen.add(n.lower())
        try:
            for e in a.hash_entries(n):
                if n not in out.setdefault(e[3], []):
                    out[e[3]].append(n)
        except Exception:
            pass
    return out


def _first(names, bi):
    return (names.get(bi) or [None])[0]


def _pointed(a):
    out = set()
    for i in range(a.hash_n_read):
        bi = a.ht[i * 4 + 3]
        if bi not in (FREE, DELETED) and (bi & MASK) < len(a.blocks):
            out.add(bi & MASK)
    return out


def _read(a, bi, names):
    key, name = None, ''
    if a.blocks[bi][3] & F_ENCRYPT:
        name = next((n for n in names if a.validate(bi, n)[0] == 'ok'), '')
        if not name:
            key = a.unnamed_key(bi)
            if key is None:
                raise ValueError('encrypted and no file name is known')
    d = a.read(name, bi=bi, hash_key=key)
    if d is None or len(d) != a.blocks[bi][2]:
        raise ValueError('does not read')
    return d


def _load(a, progress):
    names = _names(a)
    kept = sorted(bi for bi in _pointed(a) if a.exists(bi))
    data, bad = {}, []
    for k, bi in enumerate(kept):
        if k % 500 == 0:
            progress('Reading the files %d/%d' % (k, len(kept)))
        try:
            data[bi] = _read(a, bi, names.get(bi) or ())
        except Exception as e:
            bad.append((bi, _first(names, bi), str(e)[:80] or type(e).__name__))
    return kept, data, names, bad


def _raw(a, bi, sector):
    off, cs, fs, fl = a.blocks[bi]
    if fl & (F_ENCRYPT | F_SINGLE):
        return None
    p = (a.h.offset + off) & 0xFFFFFFFF
    if mpqread.cs_unknown(cs, p, len(a.d)):
        return None
    if not fs:
        return p, 0
    if not fl & (F_IMPLODE | F_COMPRESS):
        return (p, fs) if cs == fs else None
    nsec = (fs + a.sector_size - 1) // a.sector_size
    if a.sector_size != sector and (nsec != 1 or fs > sector):
        return None
    ntab = nsec + 1 + (1 if fl & F_CRC else 0)
    if cs < 4 * ntab:
        return None
    offs = struct.unpack_from('<%dI' % ntab, a.d, p)
    if offs[0] != 4 * ntab or offs[-1] != cs or any(offs[k] > offs[k + 1] for k in range(ntab - 1)):
        return None
    return p, cs


def _out_shift(a, options):
    if options.get('sector_shift'):
        s = int(options['sector_shift'])
        if not 1 <= s <= MAX_SHIFT:
            raise ValueError('sector_shift must be 1 to %d' % MAX_SHIFT)
        return s
    own = a.h.block_shift
    if not options['recompress'] and 1 <= own <= MAX_SHIFT:
        return own
    return own if SHIFT < own <= MAX_SHIFT else SHIFT


def _sampled(a, kept, data, kinds, sha, stored, sector):
    est = {}
    for kind in set(kinds.values()):
        bis = sorted((bi for bi in kept if kinds[bi] == kind), key=lambda b: sha[b])
        num = den = total = 0
        for bi in bis:
            if total >= SAMPLE:
                break
            total += len(data[bi])
            r = _raw(a, bi, sector)
            n = len(_pack({0: data[bi]}, sector, 'zlib9', None, _nothing)[0][0])
            num += min(n, r[1]) if r is not None else n
            den += stored[bi][1]
        ratio = float(num) / den if den else 1.0
        for bi in bis:
            est[bi] = stored[bi][1] * ratio
    return est


def _choose_shift(a, kept, data, kinds, sha, stored, opts):
    shift = _out_shift(a, opts)
    own = a.h.block_shift
    if opts.get('sector_shift') or not 1 <= own < shift:
        return shift, None
    big = _sampled(a, kept, data, kinds, sha, stored, 512 << shift)
    small = _sampled(a, kept, data, kinds, sha, stored, 512 << own)
    return (own, small) if sum(small.values()) < sum(big.values()) else (shift, big)


def _facts(a, kept, data, names):
    sha = dict((bi, hashlib.sha1(data[bi]).digest()) for bi in kept)
    kinds = dict((bi, _kind(_first(names, bi), data[bi])) for bi in kept)
    stored = dict((bi, _stored(a, bi)) for bi in kept)
    return sha, kinds, stored


def _not_a_map(kept, names):
    if not any(n.lower() in MAP_INFO for bi in kept for n in names.get(bi, ())):
        return 'The archive tables do not describe a map (no war3map.w3i): run "Fix map" on it first.'
    return None


def _encoder(opts):
    if not opts['recompress']:
        return 'zlib9'
    with contextlib.redirect_stdout(io.StringIO()):
        return sector_pack.resolve_encoder(opts.get('encoder') or 'auto')


def _workers(options):
    n = options.get('workers')
    if n:
        return max(1, int(n))
    teto = os.environ.get('DEVOPROTECT_WORKERS')
    if teto and teto.isdigit():
        return max(1, int(teto))
    if getattr(sys, 'frozen', False) or sys.platform == 'emscripten':
        return 1
    return os.cpu_count() or 1


def _pool(n):
    if n <= 1:
        return None
    try:
        return multiprocessing.Pool(n)
    except Exception:
        return None


def _cache():
    pasta = os.environ.get('DEVOPROTECT_SHRINK_CACHE')
    if not pasta:
        import memo
        base = memo.folder()
        pasta = os.path.join(base, 'shrink') if base else None
    return sector_pack.Cache(pasta) if pasta else None


def _fora_do_cache(items, sector, cod):
    cache = _cache()
    if cache is None:
        return sum(map(len, items.values()))
    assin = '%s|setor=%d' % (sector_pack.signature(cod, 8), sector)
    return sum(len(c) for c in items.values() if c and cache.read_data('shrink', sector_pack._key(c, assin)) is None)


def _fatia_n(args):
    i, job = args
    return i, sector_pack._slice(job)


def _pack(items, sector, cod, pool, progress):
    out, jobs, owner = {}, [], []
    step = sector_pack.SLICE * sector
    cache = _cache()
    assin = '%s|setor=%d' % (sector_pack.signature(cod, 8), sector)
    chaves = {}
    for k, c in items.items():
        if not c:
            out[k] = (b'', F_EXISTS)
            continue
        if cache is not None:
            chaves[k] = sector_pack._key(c, assin)
            achado = cache.read_data('shrink', chaves[k])
            if achado is not None:
                out[k] = (achado, F_EXISTS | F_COMPRESS)
                continue
        for s in range(0, len(c), step):
            jobs.append((c[s:s + step], cod, 8, sector))
            owner.append(k)
    feitas = [None] * len(jobs)
    total_kb = max(1, sum(len(j[0]) for j in jobs) // 1024)
    feito = 0
    res = pool.imap_unordered(_fatia_n, enumerate(jobs), chunksize=4) if pool else map(_fatia_n, enumerate(jobs))
    for n, (i, r) in enumerate(res):
        feitas[i] = r
        feito += len(jobs[i][0])
        if n % 20 == 0:
            progress('Compressing %d/%d' % (feito // 1024, total_kb))
    parts = collections.defaultdict(list)
    for k, r in zip(owner, feitas):
        parts[k].extend(r)
    for n, (k, ps) in enumerate(parts.items()):
        if n % 20 == 0:
            progress('Storing the compressed files %d/%d' % (n, len(parts)))
        out[k] = (sector_pack.build_block(ps), F_EXISTS | F_COMPRESS)
        if k in chaves:
            try:
                cache.save('shrink', chaves[k], out[k][0])
            except OSError:
                pass
    return out


def _blp(items, pool, progress):
    keys = list(items)
    res = pool.imap(sector_pack._blp_um, [items[k] for k in keys], chunksize=2) if pool else \
        map(sector_pack._blp_um, [items[k] for k in keys])
    out = {}
    for n, (k, r) in enumerate(zip(keys, res)):
        if n % 50 == 0:
            progress('Rewriting textures %d/%d' % (n, len(keys)))
        out[k] = r
    return out


def _part(path):
    base, ext = os.path.splitext(path)
    return base + '.part' + (ext or '.w3x')


def _stored(a, bi):
    ini, fim = a.interval(bi)
    return ini, max(0, min(fim, len(a.d)) - ini)


def _fail(res, msg, t0):
    res.update({'state': 'failed', 'error': msg, 'seconds': round(time.time() - t0, 1)})
    return res


def _plan(a, kept, data, opts, sector, cod, progress, sha):
    group_of = dict((bi, sha[bi] if opts['dedup'] else bi) for bi in kept)
    members = collections.OrderedDict()
    for bi in kept:
        members.setdefault(group_of[bi], []).append(bi)
    raws = dict((bi, _raw(a, bi, sector)) for bi in kept)
    by_sha = dict((sha[bi], data[bi]) for bi in kept)
    workers = _workers(opts)
    pool = None
    new, reasons = {}, collections.Counter()
    try:
        if opts['blp']:
            todo = dict((h, c) for h, c in by_sha.items() if sector_pack._e_blp_jpeg(c))
            if workers > 1 and sum(map(len, todo.values())) > POOL_BLP:
                pool = _pool(workers)
            for h, (nb, why) in _blp(todo, pool, progress).items():
                reasons[why.split(' (')[0].split(',')[0].split(':')[0]] += 1
                if nb is not None:
                    new[h] = nb
        pack = {}
        for g, m in members.items():
            h = sha[m[0]]
            if opts['recompress'] or all(raws[bi] is None for bi in m):
                pack[('old', h)] = by_sha[h]
            if h in new:
                pack[('new', h)] = new[h]
        if pool is None and workers > 1 and _fora_do_cache(pack, sector, cod) > POOL_PACK.get(cod, POOL_PACK_OTHER):
            pool = _pool(workers)
        packed = _pack(pack, sector, cod, pool, progress)
    finally:
        if pool:
            pool.close()
            pool.join()
    plan, rewritten, blp_saved = {}, set(), 0
    for g, m in members.items():
        h = sha[m[0]]
        cands = [(raws[bi][1], 0, ('raw', raws[bi][0], raws[bi][1], a.blocks[bi][3])) for bi in m
                 if raws[bi] is not None]
        if ('old', h) in packed:
            b, fl = packed[('old', h)]
            cands.append((len(b), 1, ('packed', b, fl)))
        best = min(cands, key=lambda c: (c[0], c[1]))
        content = data[m[0]]
        if h in new:
            b, fl = packed[('new', h)]
            if len(b) < best[0]:
                blp_saved += best[0] - len(b)
                best, content = (len(b), 1, ('packed', b, fl)), new[h]
                rewritten.add(g)
            else:
                reasons['not smaller in the archive'] += 1
        plan[g] = (best[2], content)
    reasons.pop('ok', None)
    kept_why = collections.Counter()
    for why, n in reasons.items():
        kept_why[BLP_WHY.get(why, why if why == 'not smaller in the archive' else 'other')] += n
    blp = {'textures': sum(1 for c in by_sha.values() if sector_pack._e_blp_jpeg(c)) if opts['blp'] else 0,
           'rewritten': len(set(sha[members[g][0]] for g in rewritten)), 'bytes': blp_saved, 'kept': dict(kept_why)}
    return group_of, members, plan, rewritten, blp


def _prefix(a):
    return 512 if a.d[:4] == b'HM3W' and a.h.offset > 512 else a.h.offset


def _write(part, a, kept, group_of, plan, shift):
    off = _prefix(a)
    hn, bn = a.hash_n, a.block_n
    entries = [0] * (4 * bn)
    written = {}
    with open(part, 'wb') as fh:
        fh.write(a.d[:off])
        fh.write(b'\0' * 32)
        pos = 32
        for bi in kept:
            g = group_of[bi]
            if g not in written:
                how = plan[g][0]
                if how[0] == 'raw':
                    fh.write(a.d[how[1]:how[1] + how[2]])
                    written[g] = (pos, how[2], how[3])
                else:
                    fh.write(how[1])
                    written[g] = (pos, len(how[1]), how[2])
                pos += written[g][1]
            wp, wl, wf = written[g]
            entries[4 * bi:4 * bi + 4] = [wp, wl, len(plan[g][1]), wf]
        hpos = pos
        hp = a.h.hash_abs
        fh.write(a.d[hp:hp + 16 * hn])
        bpos = hpos + 16 * hn
        fh.write(M.encrypt(entries, M.BLOCK_TABLE_KEY))
        fh.seek(off)
        fh.write(struct.pack('<4sIIHHIIII', b'MPQ\x1a', 32, bpos + 16 * bn, 0, shift, hpos, bpos, hn, bn))
    return dict((g, w[1]) for g, w in written.items())


def _verify(part, a, kept, data, group_of, plan, rewritten, names, shift, progress):
    import blp_huffman
    b, err = _open(part)
    if b is None:
        return err, None
    off = _prefix(a)
    if b.d[:off] != a.d[:off]:
        return 'the bytes before the archive changed', None
    magic, hs, arch, ver, bs, hpos, bpos, hn, bn = struct.unpack_from('<4sIIHHIIII', b.d, off)
    if b.h.offset != off or b.skipped or b.is_malformed:
        return 'the reader does not find the header written', None
    if (magic, hs, ver, bs, arch) != (b'MPQ\x1a', 32, 0, shift, len(b.d) - off):
        return 'the header is not the normal one', None
    if hpos + 16 * hn != bpos or bpos + 16 * bn != arch or hn != a.hash_n or bn != a.block_n:
        return 'the tables are not where the header says', None
    if b.hash_n_read != hn or list(b.ht) != list(a.ht):
        return 'the hash table changed', None
    keep = set(kept)
    for k, bi in enumerate(kept):
        if k % 500 == 0:
            progress('Checking the files %d/%d' % (k, len(kept)))
        try:
            d = b.read('', bi=bi)
        except Exception as e:
            return 'block %d does not read back (%s)' % (bi, e), None
        if group_of[bi] in rewritten:
            if d != plan[group_of[bi]][1] or not blp_huffman.same_texture(data[bi], d):
                return 'block %d (a rewritten texture) does not decode to the same pixels' % bi, None
        elif d != data[bi]:
            return 'block %d does not read back equal' % bi, None
    for bi in range(len(b.blocks)):
        if bi not in keep and b.exists(bi):
            return 'block %d is alive and should not be' % bi, None
    for n in sorted(set(n for ns in names.values() for n in ns)):
        r = a.find(n)
        if r != b.find(n):
            return '%s is not found on the same block' % n, None
        if r is None or r[1] not in keep:
            continue
        x, y = a.read(n, bi=r[1]), b.read(n, bi=r[1])
        if x != y and not (group_of[r[1]] in rewritten and blp_huffman.same_texture(x, y)):
            return '%s does not read back equal by its name' % n, None
    try:
        import stormlib_dll
    except ImportError:
        return '', 'not checked (no DLL)'
    r = stormlib_dll.opens(part)
    if r.get('opens') is False or r.get('is_malformed'):
        return 'StormLib does not open it normally (%s)' % (r.get('err') or 'malformed'), None
    return '', ('opens' if r.get('opens') else 'not checked (no DLL)')


def _report_sizes(a, kept, kinds, members, written, plan):
    by_kind, seen = {}, set()
    for bi in kept:
        k = by_kind.setdefault(kinds[bi], {'files': 0, 'before': 0, 'after': 0})
        k['files'] += 1
        st = _stored(a, bi)
        if st not in seen:
            seen.add(st)
            k['before'] += st[1]
    for g, n in written.items():
        by_kind[kinds[members[g][0]]]['after'] += n
    keep = set(kept)
    orphans = [bi for bi in range(len(a.blocks)) if bi not in keep and a.exists(bi)]
    orphan_bytes = 0
    for bi in orphans:
        st = _stored(a, bi)
        if st not in seen:
            seen.add(st)
            orphan_bytes += st[1]
    tables = 32 + 16 * (a.hash_n + a.block_n)
    used = sum(k['before'] for k in by_kind.values())
    return {'by_kind': by_kind, 'tables': tables,
            'dropped': {'orphan_blocks': len(orphans), 'orphan_bytes': orphan_bytes,
                        'unused_bytes': max(0, len(a.d) - a.h.offset - tables - used - orphan_bytes),
                        'before_the_archive': a.h.offset - _prefix(a)},
            'dedup': {'files': sum(len(m) - 1 for m in members.values()),
                      'bytes': sum((len(m) - 1) * written[g] for g, m in members.items())},
            'stored_as_is': sum(1 for how, _c in plan.values() if how[0] == 'raw'),
            'packed': sum(1 for how, _c in plan.values() if how[0] == 'packed')}


LIMIT = 512 << 20
LOSSY_TARGET = LIMIT - (6 << 20)
LOSSY_MIN_SIDE = 512


def _half_texture(name, data):
    import io
    import tempfile
    from PIL import Image
    low = name.lower()
    try:
        if low.endswith('.blp'):
            import blpread
            import blpwrite
            info = blpread.header_bytes(data, name)
            w, h = info['map_width'], info['map_height']
            if max(w, h) < LOSSY_MIN_SIDE:
                return None
            try:
                im = blpread.read_bytes(data, 1, info, name)[0] if info['sizes'][1] else None
            except Exception:
                im = None
            if im is None or im.size != (max(1, w // 2), max(1, h // 2)):
                im = blpread.read_bytes(data, 0, info, name)[0].resize((max(1, w // 2), max(1, h // 2)), Image.LANCZOS)
            fd, tmp = tempfile.mkstemp(suffix='.blp')
            os.close(fd)
            try:
                blpwrite.save_blp(im, tmp, quality=90, alpha_bits=8 if info['alpha_bits'] else 0)
                with open(tmp, 'rb') as f:
                    out = f.read()
            finally:
                os.remove(tmp)
        elif low.endswith('.tga'):
            im = Image.open(io.BytesIO(data))
            if max(im.size) < LOSSY_MIN_SIDE:
                return None
            im = im.resize((max(1, im.width // 2), max(1, im.height // 2)), Image.LANCZOS)
            b = io.BytesIO()
            im.save(b, 'TGA', rle=True)
            out = b.getvalue()
        else:
            return None
    except Exception:
        return None
    return out if len(out) < len(data) else None


def _small_wav(data):
    import io
    import wave
    try:
        import numpy as np
        with wave.open(io.BytesIO(data)) as w:
            ch, width, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
            if width not in (1, 2) or (ch == 1 and rate <= 22050):
                return None
            raw = w.readframes(n)
    except Exception:
        return None
    try:
        a = np.frombuffer(raw, dtype=np.uint8 if width == 1 else np.int16).astype(np.float32)
        if width == 1:
            a = (a - 128.0) * 256.0
        a = a.reshape(-1, ch).mean(axis=1)
        if rate > 22050:
            k = rate / 22050.0
            a = np.interp(np.arange(0, len(a) - 1, k), np.arange(len(a)), a)
            rate = 22050
        b = io.BytesIO()
        with wave.open(b, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.clip(a, -32768, 32767).astype(np.int16).tobytes())
        out = b.getvalue()
    except Exception:
        return None
    return out if len(out) < len(data) else None


def lossy(path_in, path_out, need, progress=None):
    p = progress or _nothing
    res = {'state': 'failed', 'textures': 0, 'sounds': 0, 'saved': 0, 'files': [], 'error': None}
    a, err = _open(path_in)
    if a is None:
        res['error'] = err
        return res
    p('Finding the art')
    unprotect = sys.modules.get('name_recovery')
    if unprotect is not None:
        with unprotect.quiet():
            every = unprotect.map_names(a)
    else:
        every = sorted(set(n for ns in _names(a).values() for n in ns))
    cands, seen = [], set()
    for n in every:
        if not n.lower().endswith(('.blp', '.tga', '.wav')):
            continue
        r = a.find(n)
        if r is None or r[1] in seen:
            continue
        seen.add(r[1])
        cands.append((_stored(a, r[1])[1], n))
    cands.sort(reverse=True)
    repl = []
    done = 0
    for k, (stored, n) in enumerate(cands):
        if res['saved'] >= need:
            break
        if k % 10 == 0:
            p('Making the art smaller %d/%d' % (min(res['saved'], need) >> 10, max(need >> 10, 1)))
        data = a.read(n)
        if not data:
            continue
        new = _small_wav(data) if n.lower().endswith('.wav') else _half_texture(n, data)
        if new is None:
            continue
        after = len(zlib.compress(new, 6))
        if after >= stored:
            continue
        repl.append((n, new))
        res['saved'] += stored - after
        res['files'].append((n, stored, after))
        res['sounds' if n.lower().endswith('.wav') else 'textures'] += 1
        done += 1
    if not repl:
        res['state'] = 'nothing_to_do'
        return res
    import shutil
    import mpqadd
    p('Writing the smaller art')
    part = _part(path_out)
    try:
        shutil.copyfile(path_in, part)
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            mpqadd.add_files(part, repl, [])
        b = mpqread.Archive(part)
        for n, new in repl:
            if b.read(n) != new:
                raise RuntimeError('%s did not come back as it was written' % n)
        os.replace(part, path_out)
    except Exception as e:
        if os.path.exists(part):
            os.remove(part)
        res['error'] = 'The smaller art was not written (%s).' % (str(e) or type(e).__name__)
        return res
    res['state'] = 'done'
    return res


def shrink(path_in, path_out, options=None, progress=None):
    opts = dict(options or {})
    want_lossy = bool(opts.pop('lossy', False))
    res = _with_lines(_lossy_after(path_in, path_out, opts, progress, want_lossy))
    return res


def _with_lines(res):
    lines = []
    if res.get('state') == 'done' and res.get('size_before') and res.get('size_after'):
        lines.append('%.1f MiB -> %.1f MiB.' % (res['size_before'] / 1048576.0, res['size_after'] / 1048576.0))
    lo = res.get('lossy')
    if lo:
        if lo.get('state') == 'done' and not lo.get('error'):
            lines.append('With loss, since the map was above 512 MiB: %d texture(s) at half size, %d sound(s) mono at '
                         '22 kHz.' % (lo.get('textures') or 0, lo.get('sounds') or 0))
        else:
            lines.append('The art was not made smaller: %s' % (lo.get('error') or 'nothing could be made smaller'))
        if res.get('size_after') and res['size_after'] > LIMIT:
            lines.append('Still above 512 MiB: the game will not open it.')
    if lines:
        res['summary_lines'] = lines
    return res


def _lossy_after(path_in, path_out, opts, progress, want_lossy):
    res = _shrink(path_in, path_out, opts, progress)
    if not want_lossy or res.get('state') not in ('done', 'nothing_to_do'):
        return res
    cur = path_out if res['state'] == 'done' else path_in
    size = os.path.getsize(cur)
    if size <= LIMIT:
        return res
    p = progress or _nothing
    import job_progress
    tmp = _part(path_out) + '.lossy.w3x'
    try:
        with job_progress.stage('lossy'):
            lo = lossy(cur, tmp, size - LOSSY_TARGET, p)
        res['lossy'] = dict((k, lo[k]) for k in ('state', 'textures', 'sounds', 'saved', 'error'))
        res['lossy']['files'] = lo['files'][:200]
        if lo['state'] != 'done':
            return res
        with job_progress.stage('again'):
            again = _shrink(tmp, path_out, opts, progress)
        if again.get('state') != 'done':
            res['lossy']['error'] = again.get('error') or 'the lossless shrink after it did not finish'
            return res
        again['lossy'] = res['lossy']
        again['size_before'] = res.get('size_before', again.get('size_before'))
        return again
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _shrink(path_in, path_out, options=None, progress=None):
    t0 = time.time()
    p = progress or _nothing
    opts = dict(OPTIONS)
    opts.update(options or {})
    res = {'state': 'failed', 'options': dict((k, bool(opts[k])) for k in OPTIONS)}
    if os.path.abspath(path_in) == os.path.abspath(path_out):
        return _fail(res, 'The output must be a new file.', t0)
    p('Reading the map')
    a, err = _open(path_in)
    if a is None:
        return _fail(res, err, t0)
    why = _layout(a)
    if why:
        return _fail(res, why, t0)
    try:
        _out_shift(a, opts)
        cod = _encoder(opts)
    except ValueError as e:
        return _fail(res, str(e), t0)
    except SystemExit:
        return _fail(res, 'The encoder %r is unknown or not installed (use one of %s).' % (
            opts.get('encoder'), ', '.join(sector_pack.CODIFICADORES)), t0)
    if opts['blp']:
        try:
            import PIL
        except ImportError:
            opts['blp'] = False
            res['blp_skipped'] = 'Pillow is not installed'
    try:
        kept, data, names, bad = _load(a, p)
        if bad:
            return _fail(res, '%d file(s) do not read (%s): unprotect or repair the map first.' % (
                len(bad), ', '.join(n or 'block %d' % bi for bi, n, _w in bad[:3])), t0)
        why = _not_a_map(kept, names)
        if why:
            return _fail(res, why, t0)
        sha, kinds, stored = _facts(a, kept, data, names)
        p('Choosing the sector size')
        shift = _choose_shift(a, kept, data, kinds, sha, stored, opts)[0]
        group_of, members, plan, rewritten, blp = _plan(a, kept, data, opts, 512 << shift, cod, p, sha)
    except Exception as e:
        return _fail(res, 'The map could not be prepared (%s).' % (str(e) or type(e).__name__), t0)
    res.update({'size_before': len(a.d), 'sector_before': a.sector_size, 'sector_after': 512 << shift,
                'encoder': cod, 'blp': blp})
    part = _part(path_out)
    try:
        p('Writing the new map')
        written = _write(part, a, kept, group_of, plan, shift)
        res['size_after'] = os.path.getsize(part)
        res.update(_report_sizes(a, kept, kinds, members, written, plan))
        if res['size_after'] >= res['size_before']:
            os.remove(part)
            res.update(state='nothing_to_do', seconds=round(time.time() - t0, 1))
            return res
        p('Checking the new map')
        why, storm = _verify(part, a, kept, data, group_of, plan, rewritten, names, shift, p)
        if why:
            raise RuntimeError(why)
        os.replace(part, path_out)
    except Exception as e:
        if os.path.exists(part):
            os.remove(part)
        return _fail(res, 'The check of the new map failed (%s).' % (str(e) or type(e).__name__), t0)
    if rewritten:
        res['attributes'] = _redo_attributes(path_out, p)
    res.update(state='done', checked=len(kept), stormlib=storm, seconds=round(time.time() - t0, 1))
    p('Done')
    return res


def _redo_attributes(path_out, p):
    import attributes_check
    tmp = path_out + '.attributes.part'
    try:
        r = attributes_check.fix(path_out, tmp, progress=p)
    except Exception as e:
        r = {'state': 'failed', 'error': str(e) or type(e).__name__}
    if r.get('state') == 'done':
        os.replace(tmp, path_out)
        return {'state': 'redone', 'files': r.get('fixed', 0)}
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    out = {'state': r.get('state') or 'failed', 'files': 0}
    if r.get('error'):
        out['error'] = 'the (attributes) of the rewritten textures could not be redone (%s): the game may call the ' \
                       'map corrupted; run "Redo the file checksums" on it' % r['error']
    return out

