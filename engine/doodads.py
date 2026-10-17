# Reads war3map.doo and checks every doodad id against the game data.
import struct



class FormatError(Exception):
    pass


def _tail_ok(tail):
    if not tail:
        return True
    if len(tail) < 8:
        return False
    _v, c = struct.unpack_from('<ii', tail, 0)
    if c < 0 or c > 1 << 20:
        return False
    return 8 + 16 * c == len(tail)


def read_data(b, skin=None):
    if b[:4] != b'W3do':
        raise FormatError('missing W3do')
    try:
        ver, sub = struct.unpack_from('<ii', b, 4)
        n = struct.unpack_from('<I', b, 12)[0]
    except struct.error:
        raise FormatError('short header (%d bytes)' % len(b))
    first = None
    for attempt in ((False, True) if skin is None else (bool(skin),)):
        try:
            regs, p = [], 16
            for _i in range(n):
                begin = p
                ident = b[p:p + 4]
                id_positions = [begin]
                p += 4 + 4 + 12 + 4 + 12
                if attempt:
                    id_positions.append(p)
                    p += 4
                if ver >= 12:
                    p += 4
                if ver >= 6:
                    p += 1
                p += 1
                if ver >= 8:
                    n_sets = struct.unpack_from('<I', b, p + 4)[0]
                    p += 8
                    if n_sets > 64:
                        raise FormatError('record %d: %d item sets' % (_i, n_sets))
                    for _k in range(n_sets):
                        k = struct.unpack_from('<I', b, p)[0]
                        if k > 64:
                            raise FormatError('record %d: %d items' % (_i, k))
                        id_positions.extend(p + 4 + 8 * j for j in range(k))
                        p += 4 + 8 * k
                if ver >= 13:
                    p += 4
                editor_id = None
                if ver >= 4:
                    editor_id = struct.unpack_from('<I', b, p)[0]
                    p += 4
                if ver >= 12:
                    p += 4 + 4
                    lights = struct.unpack_from('<I', b, p)[0]
                    p += 4
                    if lights > 64:
                        raise FormatError('record %d: %d lights' % (_i, lights))
                    p += 36 * lights
                if p > len(b):
                    raise FormatError('record %d runs past the end of the file' % _i)
                regs.append(
                    {'id': ident, 'begin': begin, 'sz': p - begin, 'editor_id': editor_id, 'id_positions': id_positions}
                )
            tail = b[p:]
            d = {'version_num': ver, 'subversion': sub, 'skin': attempt, 'regs': regs, 'tail': tail,
                 'on_close': _tail_ok(tail)}
            if d['on_close']:
                return d
            if first is None:
                first = d
        except (FormatError, struct.error):
            continue
    if first is not None:
        return first
    raise FormatError('does not fit any layout (version %d/%d)' % (ver, sub))

