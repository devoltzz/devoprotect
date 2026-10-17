# Rebuilds an MPQ archive from its file data when the file tables are unreadable.
import collections
import os
import re
import struct



def _text(b, n=4096):
    return b[:n].decode('utf-8', 'replace')


TEXT_CONTROL_CHARS = frozenset((27, 30, 31))


def _is_text(b):
    head_line = b[:4096]
    return bool(head_line) and not any(c < 9 or 13 < c < 32 for c in head_line if c not in TEXT_CONTROL_CHARS)


RX_FIELD = re.compile(rb'([a-z][a-zA-Z0-9]{3})[\x00-\xff]\x00\x00\x00')


def _field_prefixes(b):
    return collections.Counter(chr(m.group(1)[0]) for m in RX_FIELD.finditer(b[:65536]))


RX_LEVEL_FIELD = re.compile(
    rb'([A-Za-z][A-Za-z0-9]{3})[\x00-\xff]\x00\x00\x00[\x00-\x0f]\x00\x00\x00[\x00-\x03]\x00\x00\x00'
)


def object_type(b):
    letters = _field_prefixes(b)
    for letter, _c in letters.most_common(3):
        if letter in OBJECT_BY_LETTER:
            return OBJECT_BY_LETTER[letter]
    level = collections.Counter(chr(m.group(1)[0]) for m in RX_LEVEL_FIELD.finditer(b[:65536]))
    tn = sum(level.values())
    if not tn:
        return None
    if level.get('d', 0) * 2 >= tn:
        return 'war3map.w3d'
    if level.get('g', 0) * 2 >= tn:
        return 'war3map.w3q'
    return 'war3map.w3a'


EDITOR_EMPTY_FILES = {b'\0\0\0\0': ('war3map.w3c', 'war3map.wct', 'war3map.mmp'),
                      b'\x05\0\0\0': ('war3map.w3r',),
                      b'\x01\0\0\0': ('war3map.imp', 'war3map.w3s', 'war3map.wct'),
                      b'\x02\0\0\0': ('war3map.w3s',), b'\x03\0\0\0': ('war3map.w3s',)}


OBJECT_BY_LETTER = {'u': 'war3map.w3u', 'i': 'war3map.w3t', 'b': 'war3map.w3b', 'd': 'war3map.w3d',
                    'f': 'war3map.w3h', 'g': 'war3map.w3q', 'a': 'war3map.w3a'}


def identify(b, w3e_dims=None):
    if not b:
        return None, '.bin', 'empty'
    c4 = b[:4]
    if c4 == b'W3E!':
        return 'war3map.w3e', '.w3e', 'w3e'
    if c4 == b'MP3W':
        return 'war3map.wpm', '.wpm', 'wpm'
    if c4 == b'WTG!':
        return 'war3map.wtg', '.wtg', 'wtg'
    if c4 == b'W3do':
        try:
            import inflated_counts
            x = inflated_counts.load_units_doo(b)
            if x.get('on_close'):
                return 'war3mapUnits.doo', '.doo', 'units_doo'
        except Exception:
            pass
        return 'war3map.doo', '.doo', 'doo'
    if c4 == b'MDLX':
        return None, '.mdx', 'mdx'
    if c4 in (b'BLP1', b'BLP2'):
        try:
            w, hh = struct.unpack_from('<II', b, 12)
        except struct.error:
            w = hh = 0
        return None, '.blp', 'blp_%dx%d' % (w, hh)
    if c4 == b'RIFF':
        return None, '.wav', 'wav'
    if c4[:3] == b'ID3' or c4[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'):
        return None, '.mp3', 'mp3'
    if c4 == b'DDS ':
        return None, '.dds', 'dds'
    if c4[:2] == b'MZ':
        return None, '.dll', 'pe'
    if b.endswith(b'TRUEVISION-XFILE.\x00'):
        return None, '.tga', 'tga'
    if len(b) > 18 and b[1] == 0 and b[2] in (2, 10) and b[3:7] == b'\0' * 4 and b[16] in (24, 32):
        w, hh = struct.unpack_from('<HH', b, 12)
        if 0 < w <= 4096 and 0 < hh <= 4096:
            return None, '.tga', 'tga'
    if len(b) >= 8:
        v = struct.unpack_from('<i', b, 0)[0]
        if v in (18, 25, 28, 31, 32, 33) and len(b) < 400000:
            try:
                import w3i
                m = w3i.parse_or_tolerant(b)
                if m.get('players') is not None:
                    return 'war3map.w3i', '.w3i', 'w3i'
            except Exception:
                pass
    t = b.lstrip(b'\xef\xbb\xbf')
    if _is_text(t):
        s = _text(t, 1 << 20).replace('\r\n', '\n').replace('\r', '\n')
        if re.search(r'(?m)^\s*function\s+main\s+takes\s+nothing\s+returns\s+nothing', s) or \
                (re.search(r'(?m)^\s*endglobals\b', s) and re.search(r'(?m)^\s*function\s+\w+\s+takes', s)):
            return 'war3map.j', '.j', 'jass'
        if re.search(r'(?m)^\s*function\s+main\s*\(\s*\)', s) and re.search(r'(?m)^\s*end\b', s):
            return 'war3map.lua', '.lua', 'lua'
        if s.startswith('STRING ') or '\nSTRING ' in s[:200]:
            return 'war3map.wts', '.wts', 'wts'
        if s.startswith('[Misc]'):
            return 'war3mapMisc.txt', '.txt', 'misc'
        if s.startswith('[MapExtraInfo]'):
            return 'war3mapExtra.txt', '.txt', 'extra'
        if s.startswith('[CustomSkin]') or s.startswith('[FrameDef]'):
            return 'war3mapSkin.txt', '.txt', 'skin'
        line_list = [lx.strip() for lx in s.splitlines() if lx.strip() and lx.strip() not in MPQ_NAMES]
        if (
            line_list
            and sum(1 for lx in line_list if re.search(r'\.[A-Za-z0-9]{1,4}$', lx)) >= 0.9 * len(line_list)
            and any(lx.lower().startswith('war3map') for lx in line_list)
        ):
            return '(listfile)', '.txt', 'listfile'
        return None, '.txt', 'body_text'
    if len(b) >= 8 and set(b[:4096]) <= {0, 0xFF} and w3e_dims and len(b) == w3e_dims[0] * w3e_dims[1] * 16:
        return 'war3map.shd', '.shd', 'shd'
    if len(b) == 8 and b[4:] == b'\0\0\0\0' and b[:4] in EDITOR_EMPTY_FILES:
        fname = EDITOR_EMPTY_FILES[b[:4]][0]
        return fname, os.path.splitext(fname)[1], 'empty_editor'
    if len(b) >= 8:
        v, n = struct.unpack_from('<ii', b, 0)
        if v == 0 and n >= 0 and len(b) == 8 + 16 * n:
            return 'war3map.mmp', '.mmp', 'mmp'
        if v == 100 and 0 <= n <= 15:
            return '(attributes)', '.bin', 'attributes'
        try:
            import inflated_counts
            for fname in ('war3map.w3r', 'war3map.w3c', 'war3map.w3s', 'war3map.imp'):
                try:
                    x = inflated_counts._READERS[fname](b)
                except Exception:
                    continue
                if x.get('declared') and len(x['regs']) == x['declared'] and not x.get('remaining'):
                    return fname, os.path.splitext(fname)[1], fname.split('.')[-1]
            if v in (0, 1) or v in (-0x7FFFFFFF, -0x7FFFFFFC):
                try:
                    x = inflated_counts.read_wct(b)
                    if not x.get('remaining') and len(x['regs']) == x['declared'] and (x['declared'] or len(b) > 8):
                        return 'war3map.wct', '.wct', 'wct'
                except Exception:
                    pass
        except Exception:
            pass
        if v in (1, 2, 3) and 0 <= n < 100000:
            fname = object_type(b[8:])
            if fname:
                return fname, os.path.splitext(fname)[1], 'object_data'
    if len(b) > 1000 and set(b[:4096]) <= {0, 0xFF}:
        return 'war3map.shd', '.shd', 'shd'
    return None, '.bin', 'bin'


DEFAULT_UPPER = frozenset(n.upper() for n in (
    'war3map.j', 'war3map.lua', 'war3map.w3i', 'war3map.wts', 'war3map.wtg', 'war3map.wct', 'war3map.w3e',
    'war3map.w3a', 'war3map.w3b', 'war3map.w3d', 'war3map.w3h', 'war3map.w3q', 'war3map.w3t', 'war3map.w3u',
    'war3map.w3c', 'war3map.w3s', 'war3map.w3r', 'war3map.wpm', 'war3map.doo', 'war3map.shd', 'war3map.mmp',
    'war3map.imp', 'war3mapMisc.txt', 'war3mapSkin.txt', 'war3mapExtra.txt', 'war3mapUnits.doo', 'war3mapMap.blp',
    'war3mapMap.tga', 'war3mapPreview.tga', 'war3mapPath.tga', 'Scripts\\war3map.j', '(listfile)', '(attributes)'))

OBJECTS_UPPER = frozenset(n.upper() for n in OBJECT_BY_LETTER.values())
MPQ_NAMES = ('(listfile)', '(attributes)', '(signature)')

