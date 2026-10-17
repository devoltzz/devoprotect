# Reads and rewrites the object data files of a map (war3map.w3u, .w3t, .w3a...).
import struct


VERSIONS = (1, 2, 3)


class ObjectError(Exception):
    pass


class Mods(list):
    item_sets = None


def item_sets(mods):
    return getattr(mods, 'item_sets', None)


def with_item_sets(new_ones, old_streams):
    c = item_sets(old_streams)
    if c is None:
        return new_ones
    m = Mods(new_ones)
    m.item_sets = list(c)
    return m


def _split_in_sets(mods, ver, who):
    c = item_sets(mods)
    n = len(mods)
    if not c:
        return [(0, n)] if (c is None or n) else []
    total = sum(k for _f, k in c)
    if total == n:
        return list(c)
    if n > total:
        return list(c[:-1]) + [(c[-1][0], c[-1][1] + n - total)]
    if len(c) == 1:
        return [(c[0][0], n)]
    raise ObjectError('write: object %r (version %d) had %d sets with %d modifications and came with %d: cannot '
                      'tell which set they were taken from' % (who, ver, len(c), total, n))


_ST_I = struct.Struct('<I')
_ST_II = struct.Struct('<II')
_ST_CT = struct.Struct('<4sI')
_ST_i = struct.Struct('<i')
_ST_f = struct.Struct('<f')
_PK = {(0, True): struct.Struct('<4sIIIi4s').pack, (0, False): struct.Struct('<4sIi4s').pack,
       (1, True): struct.Struct('<4sIIIf4s').pack, (1, False): struct.Struct('<4sIf4s').pack}
_PK3 = {True: struct.Struct('<4sIII').pack, False: struct.Struct('<4sI').pack}


class _Slow(Exception):
    pass


def _read_fast(d, ver, with_levels, with_end):
    u32, u32x2, ct, i32, f32 = _ST_I.unpack_from, _ST_II.unpack_from, _ST_CT.unpack_from, _ST_i.unpack_from, \
        _ST_f.unpack_from
    idx = d.index
    pos = 4
    objects = []
    sz = len(d)
    for table in (0, 1):
        n = u32(d, pos)[0]
        pos += 4
        for _ in range(n):
            orig = d[pos:pos + 4].decode('latin-1')
            new = d[pos + 4:pos + 8].decode('latin-1')
            pos += 8
            if ver >= 3:
                mods = Mods()
                mods.item_sets = []
                nsets = u32(d, pos)[0]
                pos += 4
                if nsets > (sz - pos) // 8:
                    raise _Slow()
            else:
                mods = []
                nsets = 1
            ap = mods.append
            for _cset in range(nsets):
                if ver >= 3:
                    flag, cnt = u32x2(d, pos)
                    pos += 8
                    mods.item_sets.append((flag, cnt))
                else:
                    cnt = u32(d, pos)[0]
                    pos += 4
                for _ in range(cnt):
                    field_id, type_name = ct(d, pos)
                    pos += 8
                    if with_levels:
                        level, pointer = u32x2(d, pos)
                        pos += 8
                    else:
                        level = pointer = 0
                    if type_name == 0:
                        val = i32(d, pos)[0]
                        pos += 4
                    elif type_name == 1 or type_name == 2:
                        val = f32(d, pos)[0]
                        pos += 4
                    elif type_name == 3:
                        e = idx(b'\0', pos)
                        val = d[pos:e]
                        pos = e + 1
                    else:
                        raise _Slow()
                    if with_end:
                        end_pos = d[pos:pos + 4]
                        if len(end_pos) != 4:
                            raise _Slow()
                        ap((field_id.decode('latin-1'), type_name, level, pointer, val, end_pos))
                    else:
                        ap((field_id.decode('latin-1'), type_name, level, pointer, val))
                    pos += 4
            objects.append((table, orig, new, mods))
    if pos > sz or (pos != sz and d[pos:].strip(b'\0')):
        raise _Slow()
    return ver, objects, pos


def _write_fast(ver, objects, with_levels):
    u32 = _ST_I.pack
    with_levels = bool(with_levels)
    pk0, pk1, pk3 = _PK[(0, with_levels)], _PK[(1, with_levels)], _PK3[with_levels]
    zero = b'\0\0\0\0'
    out = [u32(ver)]
    ap = out.append
    for table in (0, 1):
        cluster = [o for o in objects if o[0] == table]
        ap(u32(len(cluster)))
        for _t, orig, new, mods in cluster:
            ids = (orig + new).encode('latin-1')
            if len(ids) != 8:
                raise _Slow()
            if ver >= 3:
                sets_split = _split_in_sets(mods, ver, new.strip('\0') or orig)
                ap(ids + u32(len(sets_split)))
                first_pos = {}
                k = 0
                for flag, n in sets_split:
                    first_pos.setdefault(k, []).append(_ST_II.pack(flag, n))
                    k += n
            else:
                ap(ids + u32(len(mods)))
                first_pos = None
            for i, m in enumerate(mods):
                if first_pos and i in first_pos:
                    out.extend(first_pos.pop(i))
                field_id, type_name, level, pointer, val = m[:5]
                end_pos = m[5] if len(m) > 5 else zero
                field_bytes = field_id.encode('latin-1')
                if len(field_bytes) != 4 or len(end_pos) != 4:
                    raise _Slow()
                if type_name == 0:
                    if not isinstance(val, int):
                        raise _Slow()
                    ap(
                        pk0(field_bytes, type_name, level, pointer, val, end_pos)
                        if with_levels
                        else pk0(field_bytes, type_name, val, end_pos)
                    )
                elif type_name in (1, 2):
                    v = float(val)
                    ap(
                        pk1(field_bytes, type_name, level, pointer, v, end_pos)
                        if with_levels
                        else pk1(field_bytes, type_name, v, end_pos)
                    )
                elif type_name == 3:
                    if not isinstance(val, (bytes, bytearray)) or b'\0' in val:
                        raise _Slow()
                    ap(pk3(field_bytes, type_name, level, pointer) if with_levels else pk3(field_bytes, type_name))
                    ap(bytes(val) + b'\0')
                    ap(end_pos)
                else:
                    raise _Slow()
            if first_pos:
                for headers in first_pos.values():
                    out.extend(headers)
    return b''.join(out)


def read_objects_bytes(d, with_levels, fname='(bytes)', with_end=False):
    if len(d) < 12:
        raise ObjectError('%s: short file (%d bytes)' % (fname, len(d)))
    ver = struct.unpack_from('<I', d, 0)[0]
    if ver not in VERSIONS:
        raise ObjectError('%s: version %d not supported (measured in the collection: %s)' % (fname, ver, VERSIONS))
    try:
        return _read_fast(d, ver, with_levels, with_end)
    except Exception:
        pass
    pos = 4
    objects = []
    try:
        for table in (0, 1):
            n = struct.unpack_from('<I', d, pos)[0]
            pos += 4
            for _ in range(n):
                orig = d[pos:pos + 4].decode('latin-1')
                new = d[pos + 4:pos + 8].decode('latin-1')
                pos += 8
                if ver >= 3:
                    mods = Mods()
                    mods.item_sets = []
                    nsets = struct.unpack_from('<I', d, pos)[0]
                    pos += 4
                    if nsets > (len(d) - pos) // 8:
                        raise ValueError('%d sets in object %r do not fit in the file' % (nsets, new or orig))
                else:
                    mods = []
                    nsets = 1
                for _cset in range(nsets):
                    if ver >= 3:
                        flag, cnt = struct.unpack_from('<II', d, pos)
                        pos += 8
                        mods.item_sets.append((flag, cnt))
                    else:
                        cnt = struct.unpack_from('<I', d, pos)[0]
                        pos += 4
                    for _ in range(cnt):
                        field_id = d[pos:pos + 4].decode('latin-1')
                        type_name = struct.unpack_from('<I', d, pos + 4)[0]
                        pos += 8
                        level = pointer = 0
                        if with_levels:
                            level, pointer = struct.unpack_from('<II', d, pos)
                            pos += 8
                        if type_name == 0:
                            val = struct.unpack_from('<i', d, pos)[0]
                            pos += 4
                        elif type_name in (1, 2):
                            val = struct.unpack_from('<f', d, pos)[0]
                            pos += 4
                        elif type_name == 3:
                            e = d.index(b'\0', pos)
                            val = d[pos:e]
                            pos = e + 1
                        else:
                            raise ObjectError('%s: value type %d in field %r of object %r (byte %d): the '
                                              'file is not of this format or the level decision is '
                                              'wrong (with_levels=%s)' % (fname, type_name, field_id, new or orig,
                                                                          pos - 8, with_levels))
                        end_pos = d[pos:pos + 4]
                        pos += 4
                        if with_end:
                            if len(end_pos) != 4:
                                raise ValueError('truncated end of record')
                            mods.append((field_id, type_name, level, pointer, val, end_pos))
                        else:
                            mods.append((field_id, type_name, level, pointer, val))
                objects.append((table, orig, new, mods))
    except (struct.error, ValueError) as e:
        raise ObjectError('%s: the file ended in the middle of an object (byte %d of %d; with_levels=%s): %s'
                          % (fname, pos, len(d), with_levels, e))
    if pos > len(d):
        raise ObjectError('%s: read %d bytes past the end (with_levels=%s)' % (fname, pos - len(d), with_levels))
    if pos != len(d) and d[pos:].strip(b'\0'):
        raise ObjectError('%s: %d bytes left over after the last object (with_levels=%s)'
                          % (fname, len(d) - pos, with_levels))
    return ver, objects, pos


def write_objects_bytes(ver, objects, with_levels):
    if ver not in VERSIONS:
        raise ObjectError('write: version %r not supported (%s)' % (ver, VERSIONS))
    if isinstance(objects, (list, tuple)):
        try:
            return _write_fast(ver, objects, with_levels)
        except Exception:
            pass
    out = [struct.pack('<I', ver)]
    for table in (0, 1):
        cluster = [o for o in objects if o[0] == table]
        out.append(struct.pack('<I', len(cluster)))
        for _t, orig, new, mods in cluster:
            ids = (orig + new).encode('latin-1')
            if len(ids) != 8:
                raise ObjectError('write: ids %r/%r do not have 4 characters each' % (orig, new))
            if ver >= 3:
                sets_split = _split_in_sets(mods, ver, new.strip('\0') or orig)
                out.append(ids + struct.pack('<I', len(sets_split)))
                first_pos = {}
                k = 0
                for flag, n in sets_split:
                    first_pos.setdefault(k, []).append(struct.pack('<II', flag, n))
                    k += n
            else:
                out.append(ids + struct.pack('<I', len(mods)))
                first_pos = {}
            for i, m in enumerate(mods):
                if i in first_pos:
                    out.extend(first_pos.pop(i))
                field_id, type_name, level, pointer, val = m[:5]
                end_pos = m[5] if len(m) > 5 else b'\0\0\0\0'
                field_bytes = field_id.encode('latin-1')
                if len(field_bytes) != 4 or len(end_pos) != 4:
                    raise ObjectError(
                        'write: field %r or end %r of object %r malformed' % (field_id, end_pos, new or orig)
                    )
                out.append(field_bytes + struct.pack('<I', type_name))
                if with_levels:
                    out.append(struct.pack('<II', level, pointer))
                if type_name == 0:
                    if not isinstance(val, int):
                        raise ObjectError('write: %r of %r is type 0 (int) and got %r' % (field_id, new or orig, val))
                    out.append(struct.pack('<i', val))
                elif type_name in (1, 2):
                    out.append(struct.pack('<f', float(val)))
                elif type_name == 3:
                    if not isinstance(val, (bytes, bytearray)) or b'\0' in val:
                        raise ObjectError('write: %r of %r is type 3 (text as bytes, without \\0) and got %r'
                                          % (field_id, new or orig, val))
                    out.append(bytes(val) + b'\0')
                else:
                    raise ObjectError(
                        'write: value type %r in field %r of object %r' % (type_name, field_id, new or orig)
                    )
                out.append(end_pos)
            for headers in first_pos.values():
                out.extend(headers)
    return b''.join(out)

