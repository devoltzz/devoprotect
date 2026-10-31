# The "not allowed to edit" marks of a map: a file inside the archive and a comment in the script (an old MPQ header signature is still read), read by the tools that respect them.
import contextlib
import io
import json
import os
import re



NAME = 'war3map.noedit'
TEXT = ('The author of this map does not allow it to be edited. Tools that respect this mark do not unprotect, '
        'change or extract it.')
SCRIPT_TEXT = 'Protected with DevoProtect. Do not edit.'
SCRIPT_RX = re.compile(rb'--|//|["\']|\[')
SCRIPT_NL_RX = re.compile(rb'[\r\n]')
HEADER_SECTOR = 0xD4
HEADER_HASH = 0xE
HEADER_BLOCK = 0xA


def content():
    return (json.dumps({'no_edit': True, 'text': TEXT}, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8')


def _result(marks, text=TEXT):
    return {'name': NAME, 'text': text, 'marks': marks} if marks else None


def of_header(h):
    try:
        marked = ((h.block_shift >> 8) & 0xFF) == HEADER_SECTOR and \
                 ((h.hash_n >> 28) & 0xF) == HEADER_HASH and ((h.block_n >> 28) & 0xF) == HEADER_BLOCK
    except Exception:
        return None
    return _result(['header']) if marked else None


def _long_open(data, pos):
    if pos + 1 >= len(data) or data[pos] != 91:
        return None
    end = pos + 1
    while end < len(data) and data[end] == 61:
        end += 1
    if end < len(data) and data[end] == 91:
        return end - pos - 1, end + 1
    return None


def _after_long(data, opened):
    level, start = opened
    close = b']' + b'=' * level + b']'
    end = data.find(close, start)
    return len(data) if end < 0 else end + len(close)


def _comment_signature(data, start, end):
    if data[start + 2:end].strip(b' \t') != SCRIPT_TEXT.encode('ascii'):
        return False
    line = max(data.rfind(b'\n', 0, start), data.rfind(b'\r', 0, start)) + 1
    prefix = data[line:start]
    if prefix.startswith(b'\xef\xbb\xbf'):
        prefix = prefix[3:]
    return not prefix.strip(b' \t')


def script_marked(data):
    if not data:
        return False
    i, n = 0, len(data)
    while i < n:
        found = SCRIPT_RX.search(data, i)
        if found is None:
            return False
        i = found.start()
        c = data[i]
        if c in (34, 39):
            quote = re.compile(rb'\\|' + re.escape(bytes((c,))))
            i += 1
            while i < n:
                part = quote.search(data, i)
                if part is None:
                    i = n
                    break
                i = part.start()
                if data[i] == 92:
                    i += 2
                else:
                    i += 1
                    break
            continue
        if c == 91:
            opened = _long_open(data, i)
            if opened is not None:
                i = _after_long(data, opened)
                continue
        else:
            if c == 45:
                opened = _long_open(data, i + 2)
                if opened is not None:
                    i = _after_long(data, opened)
                    continue
            end = SCRIPT_NL_RX.search(data, i + 2)
            end = end.start() if end else n
            if _comment_signature(data, i, end):
                return True
            i = end
            continue
        i += 1
    return False


def _read_uncached(a, name, bi=None):
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if bi is None:
                r = a.find_locale(name) if a.find(name) else None
                return a.read(name, bi=r[1]) if r else None
            return a.read(name, bi=bi)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return None


def _scripts(a):
    out = []
    for name in ('war3map.lua', 'war3map.j', 'scripts\\war3map.j'):
        try:
            entries = a.hash_entries(name)
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                raise
            continue
        seen = set()
        for entry in entries:
            bi = entry[3]
            if bi in seen:
                continue
            seen.add(bi)
            data = _read_uncached(a, name, bi)
            if data:
                out.append((name, data, bi))
    return out


def map_script_entry(a):
    for name in ('war3map.lua', 'war3map.j', 'scripts\\war3map.j'):
        data = _read_uncached(a, name)
        if data:
            return name, data, a.find_locale(name)[1]
    return None, None, None


def _of_file(a):
    try:
        if a.find(NAME) is None:
            return None
    except Exception:
        return None
    text = TEXT
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            data = json.loads(a.read(NAME).decode('utf-8'))
        if isinstance(data, dict) and isinstance(data.get('text'), str) and data['text'].strip():
            text = data['text'].strip()[:400]
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
    return {'name': NAME, 'text': text}


def of_archive(a):
    marks = []
    text = TEXT
    file_mark = _of_file(a)
    if file_mark is not None:
        marks.append('file')
        text = file_mark['text']
    if any(script_marked(data) for _name, data, _bi in _scripts(a)):
        marks.append('script')
    if of_header(getattr(a, 'h', None)) is not None:
        marks.append('header')
    return _result(marks, text)


def _of_broken(path):
    try:
        with open(path, 'rb') as f:
            data = f.read()
        import mpqlib
        h, _skipped = mpqlib.find_header(data, path)
        return of_header(h)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return None


CAMPAIGN_MAP_RX = re.compile(rb'[^\x00-\x1f"*<>?|]{1,260}?\.w3[mx]', re.I)


def of_campaign_maps(a):
    import shutil
    import tempfile
    try:
        if a.find('war3campaign.w3f') is None or a.find('war3map.w3i') is not None:
            return None
        names = []
        for source in ('(listfile)', 'war3campaign.w3f'):
            data = _read_uncached(a, source) or b''
            names += [m.group(0).strip().decode('utf-8', 'surrogateescape') for m in CAMPAIGN_MAP_RX.finditer(data)]
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return None
    seen = set()
    folder = tempfile.mkdtemp(prefix='devos_map_doctor_')
    try:
        for name in names:
            if name.upper() in seen:
                continue
            seen.add(name.upper())
            data = _read_uncached(a, name)
            if not data:
                continue
            path = os.path.join(folder, '%03d%s' % (len(seen), os.path.splitext(name)[1].lower()))
            with open(path, 'wb') as f:
                f.write(data)
            mark = read(path)
            os.remove(path)
            if mark:
                return dict(mark, map=name)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return None


def read(path):
    import mpqread
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            a = mpqread.Archive(path)
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            raise
        return _of_broken(path)
    return of_archive(a) or of_campaign_maps(a)
