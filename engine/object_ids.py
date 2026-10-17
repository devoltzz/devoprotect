# Restores object ids scrambled by the PG2 protector.
import collections
import re
import struct

import objects


TYPES = (('w3u', False, 'unit'), ('w3t', False, 'item'), ('w3a', True, 'ability'), ('w3b', False, 'destructible'),
         ('w3d', True, 'doodad'), ('w3h', False, 'buff'), ('w3q', True, 'upgrade'))
NAME_FIELDS = (b'unam', b'anam', b'bnam', b'dnam', b'fnam', b'gnam')
M32 = 0xFFFFFFFF
RX_SCRIPT = re.compile(rb'(?P<str>"(?:[^"\\]|\\.)*")|(?P<comment>//[^\r\n]*)'
                       rb"|(?P<sum_expr>\(\s*'(?P<a>(?:[^'\\]|\\.){4})'\s*\+\s*'(?P<b>(?:[^'\\]|\\.){4})'\s*\))"
                       rb"|(?P<raw>'(?P<r>(?:[^'\\]|\\.){4})')"
                       rb'|(?P<num>(?<![\w.$])(?:0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|\d+)(?![\w.]))', re.S)


def unescape(b):
    return re.sub(rb'\\(.)', lambda m: m.group(1), b)


def rawcode_value(b):
    v = 0
    for c in b:
        v = (v * 256 + (c - 256 if c >= 128 else c)) & M32
    return v


def id_value(idb):
    return struct.unpack('>I', idb)[0]


def jass_literal(idb):
    if all(32 <= c < 127 for c in idb) and b"'" not in idb and b'\\' not in idb:
        return b"'" + idb + b"'"
    return b'0x%08X' % id_value(idb)


def id_text(idb):
    return ''.join(chr(c) if 32 <= c < 127 and c != 92 else '\\x%02x' % c for c in idb)


def id_from_text(t):
    if len(t) == 4:
        return t.encode('latin-1')
    return re.sub(r'\\x([0-9A-Fa-f]{2})', lambda m: chr(int(m.group(1), 16)), t).encode('latin-1')


def number_value(t):
    if t[:2] in (b'0x', b'0X'):
        return int(t[2:], 16)
    if t[:1] == b'$':
        return int(t[1:], 16)
    if re.fullmatch(rb'0[0-7]+', t):
        return int(t, 8)
    t = t.lstrip(b'0') or b'0'
    return int(t) if len(t) <= 10 else M32 + 1


def object_name(mods):
    for m in mods:
        if m[0].encode('latin-1') in NAME_FIELDS and m[1] == 3:
            return m[4].decode('utf-8', 'replace')
    return ''


def load_data(a, prefix='war3map.'):
    files_ = {}
    for ext, level, _t in TYPES:
        try:
            d = a.read(prefix + ext)
        except Exception:
            d = None
        if not d:
            continue
        ver, objs, pos = objects.read_objects_bytes(d, level, prefix + ext, with_end=True)
        if objects.write_objects_bytes(ver, objs, level) != d[:pos]:
            raise ValueError('%s%s: the unchanged round trip does not match -- not rewritten' % (prefix, ext))
        files_[ext] = (ver, objs, level, d, pos)
    return files_


def script_rawcodes(j):
    in_use = set()
    for m in RX_SCRIPT.finditer(j):
        if m.group('raw'):
            in_use.add(unescape(m.group('r')))
    return in_use


def rewrite_objects(files_, new_ones):
    output = {}
    tally = collections.Counter()
    ids = {k: v[0] for k, v in new_ones.items()}
    for ext, (ver, objs, level, d, pos) in files_.items():
        new_objs = []
        changed = False
        for tab, orig, new, mods in objs:
            ob, nb = orig.encode('latin-1'), new.encode('latin-1')
            if nb in ids:
                nb = ids[nb]
                tally['object id'] += 1
                changed = True
            if ob in ids:
                ob = ids[ob]
                tally['base id'] += 1
                changed = True
            mods2 = []
            for m in mods:
                field_id, type_name, level_, pointer, val, end_pos = m
                if type_name == 3:
                    pieces = val.split(b',')
                    swapped = [ids.get(p, p) for p in pieces]
                    n = sum(1 for p, q in zip(pieces, swapped) if p != q)
                    if n:
                        val = b','.join(swapped)
                        tally['text value (%s)' % field_id] += n
                        changed = True
                elif type_name == 0:
                    b = struct.pack('>i', val)
                    if b in ids:
                        val = struct.unpack('>i', ids[b])[0]
                        tally['integer value (%s)' % field_id] += 1
                        changed = True
                if end_pos in ids:
                    end_pos = ids[end_pos]
                    tally['end of record'] += 1
                    changed = True
                mods2.append((field_id, type_name, level_, pointer, val, end_pos))
            new_objs.append((tab, ob.decode('latin-1'), nb.decode('latin-1'), objects.with_item_sets(mods2, mods)))
        if changed:
            output[ext] = objects.write_objects_bytes(ver, new_objs, level) + d[pos:]
    return output, tally


def rewrite_script(j, new_ones):
    ids = {id_value(k): v[0] for k, v in new_ones.items()}
    tally = collections.Counter()

    def swap(m):
        if m.group('str') or m.group('comment'):
            return m.group(0)
        if m.group('sum_expr'):
            v = (rawcode_value(unescape(m.group('a'))) + rawcode_value(unescape(m.group('b')))) & M32
            if v in ids:
                tally['sum of two rawcodes'] += 1
                return jass_literal(ids[v])
            return m.group(0)
        if m.group('raw'):
            v = rawcode_value(unescape(m.group('r')))
            if v in ids:
                tally['direct rawcode'] += 1
                return jass_literal(ids[v])
            return m.group(0)
        t = m.group('num')
        v = number_value(t)
        if v & M32 in ids and v <= M32:
            tally['numeric'] += 1
            return jass_literal(ids[v & M32])
        return t

    return RX_SCRIPT.sub(swap, j), tally

