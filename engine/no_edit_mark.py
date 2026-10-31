# Writes the "not allowed to edit" marks (the file and the script comment) into a protected map without moving its other files.
import hashlib
import os
import struct

from no_edit import NAME, SCRIPT_TEXT, content, map_script_entry, of_archive, read, script_marked


FREE, DELETED = 0xFFFFFFFF, 0xFFFFFFFE


def mark_script(name, data):
    if script_marked(data):
        return data
    line = (b'-- ' if name.lower().endswith('.lua') else b'// ') + SCRIPT_TEXT.encode('ascii')
    eol = b'\r\n' if b'\r\n' in data else b'\r' if b'\r' in data else b'\n'
    good = b'\xef\xbb\xbf' if data.startswith(b'\xef\xbb\xbf') else b''
    return good + line + eol + data[len(good):]


def _encrypt_packed(packed, key, fsize, sector):
    import sector_pack
    n = (fsize + sector - 1) // sector
    m = n + 1
    offs = struct.unpack_from('<%dI' % m, packed, 0)
    out = bytearray(packed)
    out[:4 * m] = sector_pack.encrypt(bytes(out[:4 * m]), (key - 1) & 0xFFFFFFFF)
    for k in range(n):
        start, end = offs[k], offs[k + 1]
        out[start:end] = sector_pack.encrypt(bytes(out[start:end]), (key + k) & 0xFFFFFFFF)
    return bytes(out)


def _replace_script(path, name, bi, content):
    import mpqlib
    import mpqpatch
    import mpqread
    import sector_pack
    a = mpqread.Archive(path)
    if bi is None or bi >= len(a.blocks):
        raise SystemExit('the active script block is not in the block table: nothing written')
    old_fpos, old_csize, _old_fsize, old_flags = a.blocks[bi]
    flags = (old_flags & ~(sector_pack.MPQ_FILE_IMPLODE | sector_pack.MPQ_FILE_COMPRESS |
                           sector_pack.MPQ_FILE_SINGLE_UNIT | sector_pack.MPQ_FILE_SECTOR_CRC)) | \
        sector_pack.MPQ_FILE_COMPRESS
    packed = mpqpatch.pack_compressed(content, a.sector_size)
    inplace = len(packed) <= old_csize
    fpos = old_fpos if inplace else len(a.d) - a.h.offset
    if flags & sector_pack.MPQ_FILE_ENCRYPTED:
        key = sector_pack.key_from_name(name, fpos, len(content), flags)
        packed = _encrypt_packed(packed, key, len(content), a.sector_size)
    data = bytearray(a.d)
    if inplace:
        p = (a.h.offset + fpos) & 0xFFFFFFFF
        data[p:p + len(packed)] = packed
    else:
        data += packed
        struct.pack_into('<I', data, a.h.offset + 8, len(data) - a.h.offset)
    a.bt[bi * 4:bi * 4 + 4] = [fpos, len(packed), len(content), flags]
    bpos = (a.h.offset + a.h.block_pos) & 0xFFFFFFFF
    data[bpos:bpos + len(a.bt) * 4] = mpqlib.encrypt(a.bt, mpqlib.BLOCK_TABLE_KEY)
    with open(path, 'wb') as f:
        f.write(data)
    b = mpqread.Archive(path)
    if b.read(name, bi=bi) != content:
        raise SystemExit('the signed script does not read back in its own locale: nothing written')


def _update_script_attributes(path, bi, content, log):
    import mpqadd
    import mpqread
    a = mpqread.Archive(path)
    if a.find(mpqadd.ATTRIBUTES) is None:
        return
    try:
        data_bytes = a.read(mpqadd.ATTRIBUTES)
    except Exception:
        data_bytes = None
    new = mpqadd.attributes_with(data_bytes, len(a.blocks), [(bi, bytes(content))])
    del a
    if new is None:
        mpqadd.add_files(path, [], to_delete=[mpqadd.ATTRIBUTES], hero_attributes=False, log=log)
    else:
        mpqadd.add_files(path, [(mpqadd.ATTRIBUTES, new)], hero_attributes=False, log=log)


def _blocks(a):
    import mpqread
    out = {}
    base = getattr(a.h, 'offset', 0)
    for i in range(a.hash_n_read):
        h1, h2, lp, bi = a.ht[i * 4:i * 4 + 4]
        if bi in (FREE, DELETED) or (bi & mpqread.BLOCK_MASK) >= len(a.blocks):
            continue
        pos, cs, fs, fl = a.blocks[bi & mpqread.BLOCK_MASK]
        p = (base + pos) & 0xFFFFFFFF
        out.setdefault((h1, h2, lp), (a.d[p:p + cs], fs, fl, pos if fl & 0x00020000 else None))
    return out


def _uncut(b, fname=None):
    import mpqlib
    import sector_pack
    off, field_list = sector_pack.header_text(b, fname=fname)
    _magic, _hsize, _asize, _ver, _bshift, hoff, boff, hcount, _bcount = field_list
    hpos, bpos = (off + hoff) & 0xFFFFFFFF, (off + boff) & 0xFFFFFFFF
    if not (bpos < hpos and len(b) - hpos == (hcount - 1) * 16):
        raise SystemExit('the hash table runs past the end of the file, but not in the layout of the protector\'s '
                         'hash table cut: this map is not marked')
    vals = mpqlib.decrypt(b[hpos:], mpqlib.HASH_TABLE_KEY) + [FREE] * 4
    full = mpqlib.encrypt(vals, mpqlib.HASH_TABLE_KEY)
    if full[:len(b) - hpos] != b[hpos:]:
        raise SystemExit('the cut hash table does not encrypt back to its own bytes: this map is not marked')
    new = bytearray(b[:bpos]) + full + b[bpos:hpos]
    struct.pack_into('<I', new, off + 0x08, len(new) - off)
    struct.pack_into('<I', new, off + 0x10, bpos - off)
    struct.pack_into('<I', new, off + 0x14, bpos + hcount * 16 - off)
    return bytes(new)


def mark_copy(src, dst, log=None):
    import editor_lock
    import decoy_files
    import mpqadd
    import mpqlib
    import mpqread
    import sector_pack
    quiet = (lambda *a: None)
    log = log or quiet
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if os.path.normcase(src) == os.path.normcase(dst):
        raise SystemExit('the marked copy must be another file (the map is never changed)')
    if read(src):
        raise SystemExit('the map already carries the mark')
    a = mpqread.Archive(src)
    cut = a.hash_n_read < a.hash_n
    live = [a.ht[i * 4 + 3] for i in range(a.hash_n_read)]
    full = not any(bi in (FREE, DELETED) for bi in live)
    bit31 = any('dwBlockTablePos' in m or 'dwHashTablePos' in m for m in (mpqlib.is_malformed(a.h) or []))
    known = list(editor_lock.map_names(a))
    script_name, script, script_bi = map_script_entry(a)
    signed_script = mark_script(script_name, script) if script_name else None
    script_crypt_flags = 0
    if script_name:
        script_crypt_flags = a.blocks[script_bi][3] & (sector_pack.MPQ_FILE_ENCRYPTED | sector_pack.MPQ_FILE_FIX_KEY)
        pair = mpqread._hashes3(script_name)[1:]
        for i in range(a.hash_n_read):
            h1, h2, _lp, bi = a.ht[i * 4:i * 4 + 4]
            if bi not in (FREE, DELETED) and (bi & mpqread.BLOCK_MASK) == script_bi and (h1, h2) != pair:
                raise SystemExit('the active script shares its block with another file: this map is not marked')
    try:
        attributes_before = a.read('(attributes)') if a.find('(attributes)') is not None else None
    except Exception:
        attributes_before = None
    before = _blocks(a)
    decoy_seed = int(hashlib.sha256(a.d).hexdigest()[:8], 16)
    data = a.d
    del a
    special = set(mpqread._hashes3(n)[1:] for n in ('(attributes)', '(listfile)'))
    if script_name:
        special.add(mpqread._hashes3(script_name)[1:])
    expected = ['file'] + (['script'] if script_name else [])
    tmp = '%s.part%s' % os.path.splitext(dst)
    try:
        with open(tmp, 'wb') as f:
            f.write(_uncut(data, fname=src) if cut else data)
        mpqadd.add_files(tmp, [(NAME, content())], log=quiet, grow=known, together=cut, slack=2 if cut else 0)
        if script_name:
            _replace_script(tmp, script_name, script_bi, signed_script)
            _update_script_attributes(tmp, script_bi, signed_script, quiet)
        if cut:
            mpqadd.add_files(tmp, [], hero_attributes=False, together=True, log=quiet)
        if full:
            r = decoy_files.fill(tmp, seed=decoy_seed, log=quiet, spare_last=cut, together=cut)
            if r.get('action_code') == 'declined':
                raise SystemExit('the hash table was full and does not fill again: %s' % r.get('why'))
            log('the hash table filled again: %s' % r.get('summary'))
        if cut:
            with open(tmp, 'rb') as f:
                truncated = sector_pack.cut_hash(f.read(), log=quiet, fname=tmp)
            with open(tmp, 'wb') as f:
                f.write(truncated)
            log('the hash table cut again')
        c = mpqread.Archive(tmp)
        final = of_archive(c)
        if final is None or set(final['marks']) != set(expected):
            raise SystemExit('not all marks read in the written copy: %r' % (final and final['marks']))
        if script_name:
            if c.read(script_name, bi=script_bi) != signed_script or map_script_entry(c)[1] != signed_script:
                raise SystemExit('the signed script does not read back exactly in the game locale: nothing written')
            new_crypt_flags = c.blocks[script_bi][3] & \
                (sector_pack.MPQ_FILE_ENCRYPTED | sector_pack.MPQ_FILE_FIX_KEY)
            if new_crypt_flags != script_crypt_flags:
                raise SystemExit('the signed script lost its encryption flags: nothing written')
        if attributes_before is not None:
            try:
                attributes_after = c.read('(attributes)') if c.find('(attributes)') is not None else None
            except Exception as e:
                raise SystemExit('the written (attributes) does not read: nothing written') from e
            if attributes_after is None:
                raise SystemExit('the written (attributes) is missing: nothing written')
        after = _blocks(c)
        changed = [k for k, v in before.items() if k[:2] not in special and after.get(k) != v]
        if changed:
            raise SystemExit('the mark would change %d other file(s) of the map: nothing written' % len(changed))
        if cut and not c.hash_n_read < c.hash_n:
            raise SystemExit('the hash table did not come out cut again: nothing written')
        holes = [i for i in range(c.hash_n_read) if c.ht[i * 4 + 3] in (FREE, DELETED)]
        if full and holes:
            raise SystemExit(
                'the hash table did not come out full again (%d free entries): nothing written' % len(holes)
            )
        del c
        os.replace(tmp, dst)
        delivered = read(dst)
        if delivered is None or set(delivered['marks']) != set(expected):
            os.remove(dst)
            raise SystemExit('the delivered map does not expose every mark through its real filename: nothing written')
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    lost = ['the block table bit 31 marker'] if bit31 else []
    return {'cut': cut, 'full': full, 'lost': lost, 'script': script_name, 'marks': expected,
            'size_in': os.path.getsize(src), 'size_out': os.path.getsize(dst)}
