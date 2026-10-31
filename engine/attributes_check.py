# Finds and rewrites the checksums in (attributes) that no longer match their files.
import os
import shutil
import struct
import sys
import zlib



ATTRIBUTES = '(attributes)'


def _nothing(*_a, **_k):
    pass


def _unprotector():
    if _FOUND:
        return _FOUND[0]
    u = sys.modules.get('name_recovery')
    if u is None:
        u = next((m for k, m in list(sys.modules.items()) if m is not None and k.rsplit('.', 1)[-1] == 'name_recovery'),
                 None)
    if u is not None and hasattr(u, '_listfile_status'):
        _FOUND.append(u)
        return u
    return None


_FOUND = []


def _open(path):
    import mpqread
    u = _unprotector()
    try:
        return (u._open(path) if u is not None else mpqread.Archive(path)), None
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return None, 'The map does not open (%s).' % (str(e) or type(e).__name__)


def _names(a):
    import map_formats
    import mpqread
    u = _unprotector()
    if u is not None:
        with u.quiet():
            if u._listfile_status(a)['status'] == 'ok':
                return u.listfile_names(a)
            return u.map_names(a)
    names = mpqread.listfile_names(a)
    seen = set(n.lower() for n in names)
    return names + [n for n in map_formats.standard_names() if n.lower() not in seen and a.find(n)]


def _read(a, name):
    import mpqread
    u = _unprotector()
    return u._read(a, name) if u is not None else mpqread.read_as_game(a, name)


def _part(path):
    base, ext = os.path.splitext(path)
    return base + '.part' + (ext or '.w3x')


def _vectors(data, n_blocks):
    import mpqadd
    if not data or len(data) < 8:
        return None
    version, flags = struct.unpack_from('<II', data)
    if version != 100 or flags & ~0xF:
        return None
    per = 4 * bool(flags & 1) + 8 * bool(flags & 2) + 16 * bool(flags & 4)

    def size(n):
        return 8 + n * per + ((n + 7) // 8 if flags & 8 else 0)
    old = next((n for n in range(n_blocks + 1) if size(n) == len(data)), None)
    if old is None:
        return None
    pos, vec = 8, {}
    for bit, width in ((mpqadd.ATTR_CRC32, 4), (mpqadd.ATTR_FILETIME, 8), (mpqadd.ATTR_MD5, 16)):
        if flags & bit:
            vec[bit] = [data[pos + width * i:pos + width * (i + 1)] for i in range(old)]
            pos += width * old
    return vec, flags


def _stale(a, progress):
    if a.find(ATTRIBUTES) is None:
        return False, True, 0, []
    try:
        data = a.read(ATTRIBUTES)
    except Exception:
        return True, False, 0, []
    got = _vectors(data, len(a.blocks))
    if got is None or 1 not in got[0]:
        return True, got is not None, 0, []
    crcs = got[0][1]
    out, checked, seen = [], 0, set()
    names = [n for n in _names(a) if n.lower() != ATTRIBUTES]
    for k, n in enumerate(names):
        if k % 200 == 0:
            progress('Checking CRC %d/%d' % (k, len(names)))
        r = a.find(n)
        if r is None:
            continue
        try:
            r = a.find_locale(n) or r
        except Exception:
            pass
        bi = r[1]
        if bi in seen or bi >= len(crcs):
            continue
        seen.add(bi)
        stored = struct.unpack('<I', crcs[bi])[0]
        if stored == 0:
            continue
        body = _read(a, n)
        if body is None:
            continue
        checked += 1
        actual = zlib.crc32(body) & 0xFFFFFFFF
        if actual != stored:
            out.append((n, bi, stored, actual))
    return True, True, checked, out


def fix(path_in, path_out, progress=None):
    import contextlib
    import io
    import mpqadd
    p = progress or _nothing
    res = {'state': 'failed', 'fixed': 0, 'files': []}
    if os.path.abspath(path_in) == os.path.abspath(path_out):
        res['error'] = 'The output must be a new file.'
        return res
    a, err = _open(path_in)
    if a is None:
        res['error'] = err
        return res
    present, ok, _checked, rows = _stale(a, p)
    if present and not ok:
        res['error'] = 'The (attributes) file is in a layout this program does not read, so it is left alone.'
        return res
    if not present or not rows:
        res['state'] = 'nothing_to_do'
        return res
    data = a.read(ATTRIBUTES)
    swaps = [(bi, _read(a, n)) for n, bi, _s, _c in rows]
    new = mpqadd.attributes_with(data, len(a.blocks), swaps)
    if new is None:
        res['error'] = 'The (attributes) file could not be rewritten.'
        return res
    names = _names(a)
    part = _part(path_out)
    try:
        p('Writing the new map')
        shutil.copyfile(path_in, part)
        no_room = []
        quiet = io.StringIO()
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            mpqadd.add_files(part, [(ATTRIBUTES, new)], log=_nothing, no_slot=no_room, hero_attributes=False)
        if no_room:
            raise RuntimeError('no room in the hash table for (attributes)')
        b, err = _open(part)
        if b is None:
            raise RuntimeError(err)
        _p, _ok, _c, still = _stale(b, _nothing)
        if still:
            raise RuntimeError('%d files still disagree with their CRC' % len(still))
        for n in names:
            if n.lower() == ATTRIBUTES:
                continue
            x = _read(a, n)
            if x is not None and _read(b, n) != x:
                raise RuntimeError('%s changed' % n)
        del a, b
        os.replace(part, path_out)
    except Exception as e:
        try:
            os.remove(part)
        except OSError:
            pass
        res['error'] = 'The check of the new map failed (%s).' % (str(e) or type(e).__name__)
        return res
    res.update(state='done', fixed=len(rows), files=[n for n, _b, _s, _c in rows])
    res['lines'] = ['The CRC of %d files in (attributes) was redone, so the game does not refuse the map as corrupted.'
                    % len(rows)]
    return res
