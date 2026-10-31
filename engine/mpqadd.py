# Adds and replaces files inside an existing MPQ archive.
import os
import struct

import mpqpatch as m
import mpqlib as _ML


MPQ_FILE_EXISTS = 0x80000000
MPQ_FILE_COMPRESS = 0x00000200


def _block_uses(htab, hcount):
    uses = {}
    for i in range(hcount):
        n1, n2, _loc, _plat, bi = struct.unpack_from('<IIHHI', htab, i * 16)
        if bi not in (0xFFFFFFFF, 0xFFFFFFFE):
            uses.setdefault(bi & 0x0FFFFFFF, set()).add((n1, n2))
    return uses


FREE, DELETED = 0xFFFFFFFF, 0xFFFFFFFE
HASH_MAX = 1 << 19


def grow_table(htab, hcount, known, factor=2):
    n = hcount * factor
    t = bytearray(htab) * factor
    by_name = {}
    order = []
    for s in range(hcount):
        a1, a2, _l, _p, bi = struct.unpack_from('<IIHHI', htab, s * 16)
        if bi in (FREE, DELETED) or (a1, a2) not in known:
            continue
        if (a1, a2) not in by_name:
            order.append((a1, a2))
        by_name.setdefault((a1, a2), []).append(s)
    deleted = struct.pack('<IIHHI', 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, DELETED)
    for pair, slots in by_name.items():
        for s in slots:
            for c in range(factor):
                t[(c * hcount + s) * 16:(c * hcount + s + 1) * 16] = deleted
    relocated = 0
    for pair in order:
        h0 = known[pair]
        slots = by_name[pair]
        begin = h0 & (hcount - 1)
        slots.sort(key=lambda s: (s - begin) % hcount)
        i = h0 & (n - 1)
        for s in slots:
            for _k in range(n):
                bi = struct.unpack_from('<I', t, i * 16 + 12)[0]
                if bi in (DELETED, FREE):
                    break
                i = (i + 1) & (n - 1)
            t[i * 16:(i + 1) * 16] = htab[s * 16:(s + 1) * 16]
            relocated += 1
            i = (i + 1) & (n - 1)
    return bytes(t), n, relocated


def _touches(begin, end_pos, regions):
    return any(i < end_pos and begin < f for i, f in regions)


def _known_pairs(name_list):
    out = {}
    for fname in list(name_list) + ['(listfile)', '(attributes)', '(signature)']:
        n = fname.replace('/', '\\')
        out[(_ML.hashstr(n, 1), _ML.hashstr(n, 2))] = _ML.hashstr(n, 0)
    return out


def format(path, why=False):
    def failure(body_text):
        return (None, body_text) if why else None
    if os.path.isdir(path):
        return failure('it is a folder, not a file')
    try:
        sz = os.path.getsize(path)
        if sz == 0:
            return failure('the file is empty, 0 bytes')
        h, _skipped = _ML.file_header(path)
        if h is None:
            return failure('not an MPQ file: no MPQ header the game opens')
        with open(path, 'rb') as f:
            f.seek(h.offset)
            head_line = f.read(14)
    except FileNotFoundError:
        return failure('the file does not exist')
    except OSError as e:
        return failure('the file does not open: %s' % (e.strerror or e))
    except Exception as e:
        return failure('the MPQ header does not read: %s: %s' % (type(e).__name__, e))
    if len(head_line) < 14:
        return failure('the MPQ header is cut short')
    version_num = struct.unpack('<4sIIH', head_line)[3]
    return (version_num, None) if why else version_num


ATTRIBUTES = '(attributes)'
ATTR_CRC32, ATTR_FILETIME, ATTR_MD5, ATTR_PATCH = 1, 2, 4, 8


def attributes_with(data_bytes, n_blocks, replacements):
    import hashlib
    import zlib
    if not data_bytes or len(data_bytes) < 8:
        return None
    version_num, flags = struct.unpack_from('<II', data_bytes)
    if version_num != 100 or flags & ~0xF:
        return None
    by = 4 * bool(flags & ATTR_CRC32) + 8 * bool(flags & ATTR_FILETIME) + 16 * bool(flags & ATTR_MD5)

    def byte_size(n):
        return 8 + n * by + ((n + 7) // 8 if flags & ATTR_PATCH else 0)
    old = next((n for n in range(n_blocks + 1) if byte_size(n) == len(data_bytes)), None)
    if old is None:
        return None
    pos, vectors = 8, {}
    for bit, map_width in ((ATTR_CRC32, 4), (ATTR_FILETIME, 8), (ATTR_MD5, 16)):
        if flags & bit:
            vectors[bit] = [data_bytes[pos + map_width * i:pos + map_width * (i + 1)] for i in range(old)] + \
                [bytes(map_width)] * (n_blocks - old)
            pos += map_width * old
    patch = bytearray(data_bytes[pos:pos + (old + 7) // 8] if flags & ATTR_PATCH else b'')
    patch += bytes((n_blocks + 7) // 8 - len(patch)) if flags & ATTR_PATCH else b''
    for block_entry, file_data_bytes in replacements:
        if 0 <= block_entry < n_blocks:
            if flags & ATTR_CRC32:
                vectors[ATTR_CRC32][block_entry] = struct.pack('<I', zlib.crc32(file_data_bytes) & 0xFFFFFFFF)
            if flags & ATTR_MD5:
                vectors[ATTR_MD5][block_entry] = hashlib.md5(file_data_bytes).digest()
    return struct.pack('<II', version_num, flags) + b''.join(b''.join(vectors[b]) for b in (ATTR_CRC32, ATTR_FILETIME,
                                                                                         ATTR_MD5) if b in vectors) + \
        bytes(patch)


def _update_attributes(path, repl, to_delete, all_entries, log):
    name_list = set(n.replace('/', '\\').lower() for n, _d in repl) | set(
        n.replace('/', '\\').lower() for n in to_delete
    )
    if ATTRIBUTES in name_list:
        return None
    import mpqread
    a = mpqread.Archive(path)
    if a.find(ATTRIBUTES) is None:
        return None
    try:
        data_bytes = a.read(ATTRIBUTES)
    except Exception:
        data_bytes = None
    replacements = []
    for fname, file_data_bytes in repl:
        n = fname.replace('/', '\\')
        block_list = [e[3] for e in a.hash_entries(n)] if all_entries else []
        r = a.find(n)
        if r is not None:
            block_list.append(r[1] if isinstance(r, tuple) else r)
        replacements += [(b, bytes(file_data_bytes)) for b in dict.fromkeys(block_list)]
    new = attributes_with(data_bytes, len(a.blocks), replacements)
    del a
    with open(path, 'r+b') as f:
        if new is None:
            log(
                'mpqadd: the (attributes) does not read as StormLib writes it; it is removed (out of date, the game refuses the map)'
            )
            return _add_to_open_file(f, path, [], [ATTRIBUTES], False, False, False, log, None, None, 0)
        return _add_to_open_file(f, path, [(ATTRIBUTES, new)], [], False, False, False, log, None, None, 0)


def add_files(
    path,
    repl,
    to_delete=(),
    reset=False,
    all_entries=False,
    fake_count=False,
    log=print,
    no_slot=None,
    grow=None,
    slack=0,
    hero_attributes=True,
    weight=(),
    together=False,
):
    with open(path, 'r+b') as f:
        sz = _add_to_open_file(
            f, path, repl, to_delete, reset, all_entries, fake_count, log, no_slot, grow, slack, weight, together
        )
    if hero_attributes and repl:
        new = _update_attributes(path, repl, to_delete, all_entries, log)
        if new is not None:
            sz = new
    return sz


class _NoFreeIndex:
    def __init__(self, htab, hcount):
        self.n = hcount
        self.by_pair = {}
        self.deleted_slots = []
        for s in range(hcount):
            n1, n2, _l, _p, bi = struct.unpack_from('<IIHHI', htab, s * 16)
            if bi == 0xFFFFFFFE:
                self.deleted_slots.append(s)
            else:
                self.by_pair.setdefault((n1, n2), []).append(s)

    @classmethod
    def if_needed(cls, htab, hcount):
        for s in range(hcount):
            if struct.unpack_from('<I', htab, s * 16 + 12)[0] == 0xFFFFFFFF:
                return None
        return cls(htab, hcount)

    def lookup(self, ia, pair):
        import bisect
        if self.n & (self.n - 1):
            my_parts, deleted_here = set(self.by_pair.get(pair, ())), set(self.deleted_slots)
            slots, first_free_slot, i, seen = [], None, ia, set()
            while i not in seen:
                seen.add(i)
                if i in my_parts:
                    slots.append(i)
                elif first_free_slot is None and i in deleted_here:
                    first_free_slot = i
                i = (i + 1) & (self.n - 1)
            return slots, first_free_slot
        slots = sorted(self.by_pair.get(pair, ()), key=lambda s: (s - ia) % self.n)
        k = bisect.bisect_left(self.deleted_slots, ia)
        if k < len(self.deleted_slots):
            return slots, self.deleted_slots[k]
        return slots, (self.deleted_slots[0] if self.deleted_slots else None)

    def dropped(self, s, pair):
        import bisect
        if s in self.by_pair.get(pair, ()):
            self.by_pair[pair].remove(s)
        bisect.insort(self.deleted_slots, s)

    def occupy(self, s, pair):
        import bisect
        k = bisect.bisect_left(self.deleted_slots, s)
        if k < len(self.deleted_slots) and self.deleted_slots[k] == s:
            del self.deleted_slots[k]
        self.by_pair.setdefault(pair, []).append(s)


def _add_to_open_file(f, path, repl, to_delete, reset, all_entries, fake_count, log, no_slot, grow, slack, weight=(),
                      together=False):
    m._crypt = m._init_crypt()
    head = f.read(4096)
    off = _ML.header_offset(path)
    if off + 32 > len(head):
        f.seek(0)
        head = f.read(off + 32)
    magic, hsize, asize, ver, bshift, hoff, boff, hcount, bcount = struct.unpack_from('<4sIIHHIIII', head, off)
    if ver != 0:
        raise AssertionError('MPQ v1 only')
    hcount &= 0x0FFFFFFF
    bcount &= 0x0FFFFFFF
    f.seek((off + hoff) & 0xFFFFFFFF)
    htab = bytearray(m.decrypt(f.read(hcount * 16), m.hash_string('(hash table)', 3)))
    f.seek((off + boff) & 0xFFFFFFFF)
    btab = bytearray(m.decrypt(f.read(bcount * 16), m.hash_string('(block table)', 3)))
    if len(htab) < hcount * 16:
        raise SystemExit('hash table declared beyond the end of the file (%d entries, %d in the file): virtual table; '
                         'repair the map first' % (hcount, len(htab) // 16))
    bcount = min(bcount, len(btab) // 16)
    del btab[bcount * 16:]
    f.seek(0, 2)
    end = f.tell()
    tables_end = off + max(hoff + hcount * 16, boff + bcount * 16)
    if fake_count:
        n_fake = 0
        for i in range(hcount):
            n1, n2, loc, plat, bi = struct.unpack_from('<IIHHI', htab, i * 16)
            if bi not in (0xFFFFFFFF, 0xFFFFFFFE) and (bi & 0x0FFFFFFF) >= bcount:
                struct.pack_into('<IIHHI', htab, i * 16, n1, n2, loc, plat, 0xFFFFFFFE)
                n_fake += 1
        log('fake: %d hash table entry(ies) with a nonexistent block -> removed' % n_fake)
    new_hash = False
    if grow is not None and hcount and not hcount & (hcount - 1):
        pairs = set()
        available = 0
        for i in range(hcount):
            n1, n2, _l, _p, bi = struct.unpack_from('<IIHHI', htab, i * 16)
            if bi in (0xFFFFFFFF, 0xFFFFFFFE):
                available += 1
            elif (bi & 0x0FFFFFFF) < bcount:
                pairs.add((n1, n2))
        new_ones = sum(1 for fname, _c in list(repl) + [(x[0], None) for x in weight]
                       if (m.hash_string(fname, 1), m.hash_string(fname, 2)) not in pairs)
        tgt = new_ones + max(1, slack)
        if (new_ones or slack) and available < tgt:
            known = _known_pairs(grow)
            known_live = sum(1 for i in range(hcount)
                             if (struct.unpack_from('<I', htab, i * 16 + 12)[0] & 0x0FFFFFFF) < bcount and
                             struct.unpack_from('<II', htab, i * 16) in known)
            factor = 2
            while hcount * factor <= HASH_MAX and \
                    factor * available + (factor - 1) * known_live < tgt:
                factor *= 2
            if hcount * factor <= HASH_MAX and factor * available + (factor - 1) * known_live >= tgt:
                new_htab, new_hcount, relocated = grow_table(bytes(htab), hcount, known, factor)
                log('hash table FULL (%d entries, %d available, %d new names): grows %dx -> %d entries, %d '
                    'known-name entries relocated' % (hcount, available, new_ones, factor, new_hcount, relocated))
                htab = bytearray(new_htab)
                hcount = new_hcount
                new_hash = True
            else:
                log('hash table FULL (%d entries, %d available, %d new names) and no known name to '
                    'free: not growing' % (hcount, available, new_ones))
    if reset and end > tables_end:
        log('reset: truncating from %d to %d' % (end, tables_end))
        f.truncate(tables_end)
        end = tables_end
    new_end = end
    bcount0 = bcount
    sector = _ML.header_sector(bshift)
    uses = None
    for name in to_delete:
        ha = m.hash_string(name, 1)
        hb = m.hash_string(name, 2)
        i = m.hash_string(name, 0) & (hcount - 1)
        achou = 0
        for _ in range(hcount):
            n1, n2, loc, plat, bi = struct.unpack_from('<IIHHI', htab, i * 16)
            if bi == 0xFFFFFFFF:
                break
            if n1 == ha and n2 == hb and bi != 0xFFFFFFFE:
                struct.pack_into('<IIHHI', htab, i * 16, n1, n2, loc, plat, 0xFFFFFFFE)
                log('deleted %s: hash#%d (block %d is left orphaned)' % (name, i, bi))
                achou += 1
            i = (i + 1) & (hcount - 1)
        if not achou:
            log('delete: %s is not in the map' % name)
    if repl or weight:
        replaced_pairs = set((m.hash_string(n, 1), m.hash_string(n, 2)) for n, _c in repl)
        hash_entries = list(struct.iter_unpack('<IIHHI', htab))
        new_block_cap = (
            bcount + len(repl) + len(weight) + sum(1 for e in hash_entries if (e[0], e[1]) in replaced_pairs)
        )
        wakeable = [i for i, e in enumerate(hash_entries)
                    if e[4] not in (FREE, DELETED) and bcount <= (e[4] & 0x0FFFFFFF) < new_block_cap]
        for i in wakeable:
            struct.pack_into('<I', htab, i * 16 + 12, DELETED)
        if wakeable:
            log('%d hash table entr(ies) with a block just past the table (where the new blocks go) -> removed'
                % len(wakeable))
        del hash_entries
    no_free = _NoFreeIndex.if_needed(htab, hcount) if (repl or weight) else None
    for name, content in repl:
        ia = m.hash_string(name, 0) & (hcount - 1)
        ha = m.hash_string(name, 1)
        hb = m.hash_string(name, 2)
        hits = []
        free = None
        if no_free is not None:
            slots, free = no_free.lookup(ia, (ha, hb))
            for i in slots:
                n1, n2, loc, plat, bi = struct.unpack_from('<IIHHI', htab, i * 16)
                if (bi & 0x0FFFFFFF) < len(btab) // 16:
                    hits.append((i, bi & 0x0FFFFFFF, loc, plat))
        i = ia
        for _ in (range(hcount) if no_free is None else ()):
            n1, n2, loc, plat, bi = struct.unpack_from('<IIHHI', htab, i * 16)
            if bi == 0xFFFFFFFF:
                if free is None:
                    free = i
                break
            if bi == 0xFFFFFFFE and free is None:
                free = i
            if n1 == ha and n2 == hb and (bi & 0x0FFFFFFF) < len(btab) // 16:
                hits.append((i, bi & 0x0FFFFFFF, loc, plat))
            i = (i + 1) & (hcount - 1)
        if not hits and free is None:
            if no_slot is None:
                raise SystemExit('hash table full for ' + name)
            log('NO SLOT: %s does not fit (the hash table is full: %d entries)' % (name, hcount))
            no_slot.append(name)
            continue
        packed = m.pack_compressed(content, sector)
        f.seek(new_end)
        f.write(packed)
        details = new_end - off
        nflags = MPQ_FILE_EXISTS | MPQ_FILE_COMPRESS
        if hits:
            neutrals = [x for x in hits if x[2] == 0 and (x[3] & 0xFF) == 0]
            targets = hits if all_entries else [neutrals[-1] if neutrals else hits[0]]
            if uses is None:
                uses = _block_uses(htab, hcount)
            for hi, bi, loc, plat in targets:
                if uses.get(bi, set()) - {(ha, hb)}:
                    nbi = len(btab) // 16
                    btab += struct.pack('<IIII', details, len(packed), len(content), nflags)
                    struct.pack_into('<I', htab, hi * 16 + 12, nbi)
                    uses[bi].discard((ha, hb))
                    uses.setdefault(nbi, set()).add((ha, hb))
                    log('replaced %s: hash#%d -> block#%d NEW (block#%d also belongs to another name) size=%d packed=%d'
                        % (name, hi, nbi, bi, len(content), len(packed)))
                    continue
                struct.pack_into('<IIII', btab, bi * 16, details, len(packed), len(content), nflags)
                log('replaced %s: hash#%d block#%d locale 0x%x platform 0x%x flags 0x%x size=%d packed=%d'
                      % (name, hi, bi, loc, plat & 0xFF, plat >> 8, len(content), len(packed)))
            if not all_entries and neutrals:
                target_block_index = struct.unpack_from('<I', htab, targets[0][0] * 16 + 12)[0] & 0x0FFFFFFF
                for x in [x for x in hits if x not in targets and x[2] != 0 and x[1] != target_block_index]:
                    struct.pack_into('<I', htab, x[0] * 16 + 12, DELETED)
                    hits.remove(x)
                    if not any(y[1] == x[1] for y in hits):
                        uses.get(x[1], set()).discard((ha, hb))
                    if no_free is not None:
                        no_free.dropped(x[0], (ha, hb))
                    log('   locale entry 0x%x of %s (hash#%d, block#%d) -> removed: the game opens the replaced one'
                        % (x[2], name, x[0], x[1]))
            if len(hits) > len(targets):
                log('   (%d entries with this name; the other(s) remain: %s)' % (
                    len(hits), [(x[0], hex(x[2])) for x in hits if x not in targets]))
        else:
            bi = len(btab) // 16
            btab += struct.pack('<IIII', details, len(packed), len(content), nflags)
            struct.pack_into('<IIHHI', htab, free * 16, ha, hb, 0, 0, bi)
            if no_free is not None:
                no_free.occupy(free, (ha, hb))
            log('added %s: hash#%d block#%d size=%d packed=%d' % (name, free, bi, len(content), len(packed)))
        new_end += len(packed)
    for name, tgt in weight:
        ia = m.hash_string(name, 0) & (hcount - 1)
        ha = m.hash_string(name, 1)
        hb = m.hash_string(name, 2)
        i = ia
        free = None
        if no_free is not None:
            slots, free = no_free.lookup(ia, (ha, hb))
            if slots:
                raise SystemExit(
                    'add: the forged name %s is already in the map (the weight does not collide with the live one)'
                    % name
                )
        for _ in (range(hcount) if no_free is None else ()):
            n1, n2, loc, plat, bi = struct.unpack_from('<IIHHI', htab, i * 16)
            if n1 == ha and n2 == hb and bi not in (0xFFFFFFFF, 0xFFFFFFFE):
                raise SystemExit(
                    'add: the forged name %s is already in the map (the weight does not collide with the live one)'
                    % name
                )
            if bi == 0xFFFFFFFF:
                if free is None:
                    free = i
                break
            if bi == 0xFFFFFFFE and free is None:
                free = i
            i = (i + 1) & (hcount - 1)
        if free is None:
            raise SystemExit('add: hash table full for %s (the weight)' % name)
        if no_free is not None:
            no_free.occupy(free, (ha, hb))
        bi = len(btab) // 16
        if tgt[0] == 'band':
            _, rel_off, byte_size = tgt
            btab += struct.pack('<IIII', rel_off, byte_size, byte_size, MPQ_FILE_EXISTS)
            struct.pack_into('<IIHHI', htab, free * 16, ha, hb, 0, 0, bi)
            log(
                'added %s: hash#%d block#%d RANGE at +%d x %d B (nothing written)'
                % (name, free, bi, rel_off, byte_size)
            )
        else:
            _, block_entry, fsize, nflags = tgt
            f.seek(new_end)
            f.write(block_entry)
            rel_off = new_end - off
            btab += struct.pack('<IIII', rel_off, len(block_entry), fsize, nflags)
            struct.pack_into('<IIHHI', htab, free * 16, ha, hb, 0, 0, bi)
            log('added %s: hash#%d block#%d BOMB size=%d packed=%d (the sector table by its size)'
                % (name, free, bi, fsize, len(block_entry)))
            new_end += len(block_entry)
    data_bytes = []
    for i in range(bcount):
        b_off, b_cs, _b_fs, b_fl = struct.unpack_from('<IIII', btab, i * 16)
        if b_fl & MPQ_FILE_EXISTS and b_cs:
            begin = (off + b_off) & 0xFFFFFFFF
            if begin + b_cs <= end:
                data_bytes.append((begin, begin + b_cs))
    habs0 = (off + hoff) & 0xFFFFFFFF
    babs0 = (off + boff) & 0xFFFFFFFF
    head_line = (off, off + 32)
    if not new_hash and _touches(habs0, habs0 + len(htab), data_bytes + [(babs0, babs0 + bcount * 16), head_line]):
        new_hash = True
        log('hash table overlaps something else: moving it to the end of the file')
    block_at_end = _touches(babs0, babs0 + bcount * 16, data_bytes + [(habs0, habs0 + len(htab)), head_line])
    if together:
        new_hash = block_at_end = True
    if new_hash:
        hoff = new_end - off
        f.seek(new_end)
        f.write(m.encrypt(bytes(htab), m.hash_string('(hash table)', 3)))
        new_end += len(htab)
    else:
        f.seek((off + hoff) & 0xFFFFFFFF)
        f.write(m.encrypt(bytes(htab), m.hash_string('(hash table)', 3)))
    new_bcount = len(btab) // 16
    if new_bcount != bcount or block_at_end:
        boff = new_end - off
        f.seek(new_end)
        f.write(m.encrypt(bytes(btab), m.hash_string('(block table)', 3)))
        new_end += len(btab)
        bcount = new_bcount
    else:
        f.seek((off + boff) & 0xFFFFFFFF)
        f.write(m.encrypt(bytes(btab), m.hash_string('(block table)', 3)))
    f.seek(off + 8)
    f.write(struct.pack('<I', new_end - off))
    f.seek(off + 24)
    f.write(struct.pack('<II', hcount, bcount))
    f.seek(off + 16)
    f.write(struct.pack('<II', hoff, boff))
    log('ok: size %d (%.1f MiB), blocks=%d, boff=%d' % (new_end, new_end / 1048576.0, bcount, boff))
    return new_end
