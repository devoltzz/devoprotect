# The game files of each Warcraft III version from 1.24 to 1.29 (scripts and data), and which version a map was made for.
import json
import os
import re
import struct
import sys


HERE = os.path.dirname(os.path.abspath(__file__))

COMMON = os.path.normpath(os.path.join(HERE, '..'))
REF_ROOT = os.path.join(COMMON, 'ref')
INDEX_NAME = 'versions.json'
NATIVES_NAME = 'natives_patch.json'
SCRIPTS = ('common.j', 'blizzard.j', 'common.ai')
REFORGED = '3.0'
REFORGED_OLD = ('2.0.4',)
SOURCES = (('1.24a', 'patch'), ('1.24b', 'patch'), ('1.24c', 'patch'), ('1.24d', 'patch'), ('1.24e', 'patch'),
           ('1.25b', 'patch'), ('1.26a', 'patch'), ('1.27a', 'patch'), ('1.27b', 'patch'),
           ('1.28.5', 'folder'), ('1.29.2', 'folder'))
CLASSIC = tuple(v for v, _k in SOURCES)
RANGES = (('pre-1.24', None), ('1.24-1.28', '1.27b'), ('1.29', '1.29.2'), ('1.30+', REFORGED))
RANGE_ORDER = tuple(r for r, _v in RANGES)
OBJECTS = 'objects'

class VersionError(Exception):
    pass


def normalize(text):
    t = str(text or '').strip().lower().lstrip('v')
    if t in CLASSIC:
        return t
    if t in ('2', '2.0') or t.startswith('2.'):
        return REFORGED_OLD[-1]
    if t in ('reforged', 'r', '3', '3.0', '3.0.0', '3.0.1') or t.startswith('3.'):
        return REFORGED
    m = re.match(r'^1\.?(\d{2})([a-z]?)(?:\.\d+)*$', t)
    if not m:
        return None
    minor = int(m.group(1))
    if minor >= 30:
        return REFORGED
    same = [v for v in CLASSIC if _key(v)[:2] == (1, minor)]
    if not same:
        return None
    if m.group(2):
        exact = '1.%02d%s' % (minor, m.group(2))
        return exact if exact in CLASSIC else same[-1]
    return same[-1]


def _key(version):
    t = str(version).strip().lower()
    m = re.match(r'^(\d+)\.(\d+)([a-z]?)(?:\.(\d+))?', t)
    if not m:
        return (0, 0, 0)
    third = (ord(m.group(3)) - 96) if m.group(3) else int(m.group(4) or 0)
    return (int(m.group(1)), int(m.group(2)), third)


PACK_ZIP = 'wc3_versions.zip'
_DATA = {}
def user_data_dir():
    if sys.platform.startswith('linux'):
        base = os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')
    else:
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'DevosMapDoctor', 'wc3_versions')


def data_dir():
    env = os.environ.get('WC3_VERSOES_DADOS')
    if env:
        return env
    if 'dir' in _DATA:
        return _DATA['dir']
    if getattr(sys, 'frozen', False):
        d = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'wc3_versions')
        if not os.path.isdir(os.path.join(d, OBJECTS)) and os.path.isdir(os.path.join(user_data_dir(), OBJECTS)):
            d = user_data_dir()
    else:
        d = os.path.join(COMMON, 'cache', 'wc3_versions')
    _DATA['dir'] = d
    zipped = os.path.join(os.path.dirname(d), PACK_ZIP)
    if not os.path.isdir(os.path.join(d, OBJECTS)) and os.path.isfile(zipped):
        import tempfile
        cache = os.path.join(os.environ.get('DEVOPROTECT_CACHE') or os.path.join(tempfile.gettempdir(),
                                                                             'devos_map_doctor_ui'), 'wc3_versions')
        for target in (d, cache):
            try:
                if not os.path.isdir(os.path.join(target, OBJECTS)):
                    unpack(zipped, target)
                _DATA['dir'] = target
                break
            except Exception:
                continue
    return _DATA['dir']


def _ref_roots():
    roots = [REF_ROOT]
    if os.path.join(HERE, 'ref') != REF_ROOT:
        roots.append(os.path.join(HERE, 'ref'))
    if getattr(sys, 'frozen', False):
        roots.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'ref'))
    roots.append(os.path.join(data_dir(), 'ref'))
    return roots


_INDEX = {}


def index():
    if 'i' not in _INDEX:
        _INDEX['i'] = {}
        for root in _ref_roots():
            p = os.path.join(root, INDEX_NAME)
            if os.path.isfile(p):
                with open(p, encoding='utf-8') as f:
                    _INDEX['i'] = json.load(f)
                break
    return _INDEX['i']


def scripts_name(version):
    v = normalize(version)
    if v == REFORGED:
        return REFORGED
    return ((index().get('versions') or {}).get(v) or {}).get('scripts')


def scripts_dir(version):
    name = scripts_name(version)
    if not name:
        return None
    for root in _ref_roots():
        d = os.path.join(root, name)
        if all(os.path.isfile(os.path.join(d, f)) for f in SCRIPTS[:2]):
            return d
    return None


_GAMES = {}


RX_NATIVE = re.compile(r'(?m)^\s*(?:constant\s+)?native\s+(\w+)')
RX_FUNCTION = re.compile(r'(?m)^\s*function\s+(\w+)')
_NATIVES = {}


def natives_patches():
    if 't' not in _NATIVES:
        _NATIVES['t'] = {}
        for root in _ref_roots():
            p = os.path.join(root, NATIVES_NAME)
            if os.path.isfile(p):
                with open(p, encoding='utf-8') as f:
                    t = json.load(f)
                _NATIVES['t'] = dict((n, v) for v, ns in (t.get('patches') or {}).items() for n in ns)
                break
    return _NATIVES['t']


RX_JASS_NOISE = re.compile(r'//[^\n]*|"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'')
RX_IDENT = re.compile(r'\b[A-Za-z_]\w*\b')
RX_RETURN_BUG = re.compile(r'(?m)^\s*function\s+\w+\s+takes\s+\w+\s+\w+\s+returns\s+\w+\s*\n\s*return\s+\w+\s*\n\s*'
                           r'return\s+(?:0|null|0\.0|false|"")\s*\n\s*endfunction')
EDITOR_129 = 6060


RX_GLOBALS = re.compile(r'(?ms)^\s*globals\b(.*?)^\s*endglobals')
RX_GLOBAL = re.compile(r'(?m)^\s*(?:constant\s+)?\w+\s+(?:array\s+)?(\w+)')


def script_names(text):
    clean = RX_JASS_NOISE.sub(' ', text.replace('\r\n', '\n').replace('\r', '\n'))
    defined = set(RX_FUNCTION.findall(clean))
    for block in RX_GLOBALS.findall(clean):
        defined.update(RX_GLOBAL.findall(block))
    return set(RX_IDENT.findall(clean)), defined, set(RX_NATIVE.findall(clean))


def _bump(state, rng, reason):
    state['reasons'].append(reason)
    if RANGE_ORDER.index(rng) > RANGE_ORDER.index(state['range']):
        state['range'] = rng


def _range_of_patch(patch):
    k = _key(patch)
    if k >= (1, 30, 0):
        return '1.30+'
    if k >= (1, 29, 0):
        return '1.29'
    return '1.24-1.28'


def detect_parts(w3i_bytes=None, script=None, language=None, objects=None, wtg=None, size=None, platform=None):
    st = {'range': '1.24-1.28', 'reasons': [], 'minimum': None, 'w3i': None, 'players': None, 'return_bug': False}
    if w3i_bytes:
        try:
            import w3i
            m = w3i.parse_or_tolerant(w3i_bytes)
        except Exception:
            m = None
        if m:
            fmt, editor = m.get('version'), m.get('editor_version')
            gv = m.get('game_version')
            st['w3i'] = {'format': fmt, 'editor': editor, 'game': '.'.join(str(x) for x in gv) if gv else None}
            st['players'] = len(m.get('players') or [])
            if gv and fmt >= 28:
                game_text = '.'.join(str(x) for x in gv)
                _bump(st, '1.30+' if tuple(gv[:2]) >= (1, 30) else _range_of_patch(game_text),
                      'the map info (w3i format %d) was saved by the %s World Editor' % (fmt, game_text))
            elif fmt == 18:
                st['reasons'].append('the map info is in the Reign of Chaos format (w3i 18)')
            elif fmt is not None and fmt >= 28:
                _bump(st, '1.30+', 'the map info is in format %d, which 1.31 and later write' % fmt)
            if fmt is not None and fmt < 28 and editor and editor >= EDITOR_129:
                _bump(st, '1.29', 'saved by World Editor %d (1.29 or newer)' % editor)
            if st['players'] and st['players'] > 12:
                _bump(st, '1.29', '%d player slots: more than 12 came with 1.29' % st['players'])
    if platform:
        st['reasons'].append(platform)
    platform = 1 if platform else 0
    if language == 'lua':
        _bump(st, '1.30+', 'the script is Lua, which came with 1.31')
    elif script:
        script = script.replace('\r\n', '\n').replace('\r', '\n')
        used, defined, declared = script_names(script)
        table = natives_patches()
        newest, newest_name = None, None
        later = {}
        own = len([n for n in declared if n not in table])
        platform += own
        if own:
            st['reasons'].append('the script declares %d natives no Blizzard game has (a platform client: KK, JAPI, '
                                 'JN, YDWE)' % own)
        for n in sorted(used - defined):
            p = table.get(n)
            if p is None:
                continue
            if newest is None or _key(p) > _key(newest):
                newest, newest_name = p, n
            if _key(p) >= (1, 29, 0):
                later.setdefault(_range_of_patch(p), []).append(n)
        if newest:
            st['minimum'] = newest
        for rng in ('1.29', '1.30+'):
            if later.get(rng):
                names = sorted(later[rng])
                _bump(st, rng, 'the script uses %d natives or constants that came in %s or later (%s)' % (
                    len(names), '1.29' if rng == '1.29' else '1.30', ', '.join(names[:5]) +
                    (', ...' if len(names) > 5 else '')))
        if RX_RETURN_BUG.search(script):
            st['return_bug'] = True
            if st['range'] == '1.24-1.28' and (newest is None or _key(newest) < (1, 24, 1)):
                st['range'] = 'pre-1.24'
                st['reasons'].append('the script uses the return bug (a handle returned as an integer), which only '
                                     '1.23 and older run')
            else:
                st['reasons'].append('the script has a return bug function, which 1.24 and later refuse')
        if newest and not later and newest_name:
            st['reasons'].append('the newest native it uses is %s (%s)' % (newest_name, newest))
    for name, data in sorted((objects or {}).items()):
        if data and len(data) >= 4 and struct.unpack_from('<i', data, 0)[0] >= 3:
            _bump(st, '1.30+', '%s is in the object data format 3 (1.33 and later)' % name)
            break
    if wtg and len(wtg) >= 8 and wtg[:4] == b'WTG!' and struct.unpack_from('<I', wtg, 4)[0] & 0x80000000:
        _bump(st, '1.30+', 'the triggers (war3map.wtg) are in the format of 1.31 and later')
    import map_size
    if size and size > map_size.NEW:
        st['reasons'].append('the map is %.1f MB, above the 128 MB the classic game sends to other players: %s' % (
            size / 1048576.0, 'the platform client lifts that limit' if platform else
            'made for single player, or for a client or loader that lifts the limit'))
    elif size and size > map_size.OLD:
        st['reasons'].append('the map is %.1f MB, above the 8 MB that 1.24 to 1.27a send to other players: %s' % (
            size / 1048576.0, 'the platform client lifts that limit' if platform else
            'made for 1.27b or later, for single player, or for a client or loader that lifts the limit'))
    if not st['reasons']:
        st['reasons'].append('nothing newer than the 1.24 to 1.28 game was found')
    st['version'] = dict(RANGES).get(st['range'])
    st['label'] = {'pre-1.24': '1.23 or older', '1.24-1.28': '1.24 to 1.28', '1.29': '1.29',
                   '1.30+': '1.30 or newer (Reforged)'}[st['range']]
    return st


def unpack(zip_path, data=None):
    import shutil
    import zipfile
    data = data or data_dir()
    n = 0
    fresh = not os.path.exists(data)
    out_dir = data + '.part' if fresh else data
    if fresh and os.path.isdir(out_dir):
        shutil.rmtree(out_dir, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename
            if name.startswith(('/', '\\')) or '..' in name.replace('\\', '/').split('/') or ':' in name:
                raise VersionError('a name outside the data folder in the zip: %s' % name)
            if name.endswith('/'):
                continue
            dst = os.path.join(out_dir, *name.split('/'))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with z.open(info) as src, open(dst + '.part', 'wb') as out:
                out.write(src.read())
            os.replace(dst + '.part', dst)
            n += 1
    if fresh:
        os.rename(out_dir, data)
    _GAMES.clear()
    _INDEX.clear()
    _NATIVES.clear()
    return {'files': n}

