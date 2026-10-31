# Recovers file names from their hashes and from what the map itself mentions.
import os
import re


WARCRAFT_EXTS = frozenset(e.encode() for e in (
    'mdx mdl blp tga dds jpg jpeg png gif bmp psd ico tif tiff webp '
    'wav mp3 flac ogg mid midi dls aif aiff avi ttf otf fnt woff '
    'j ai lua txt slk fdf toc pld wts wai ini html htm xml json csv js css md cfg log lst '
    'ts '
    'w3a w3b w3c w3d w3e w3f w3g w3h w3i w3l w3m w3n w3o w3q w3r w3s w3t w3u w3x w3z w3grp '
    'wct wtg wpm doo mmp shd imp mpq frag vert material mrf ifl flt m3d '
    'exe dll asi mix bin dat db jc key sign gid ccd ax b00 bak cmd clh exp jx lnk pkg was xlsx 3ds xxx iniconfig '
    'manifest zip rar 7z').split())
EXT_EQUIV = [
    ('.w3m', '.w3x', '.mpq', '.pud'),
    ('.txt', '.ini'),
    ('.j', '.lua'),
    ('.wav', '.mp3', '.ogg', '.flac', '.aif', '.aiff'),
    ('.mdl', '.mdx'),
    ('.blp', '.tga', '.jpg', '.dds', '.gif', '.png'),
    ('.ttf', '.otf', '.woff'),
]
PROTECTOR_PREFIXES = ('DIS', 'PAS', 'DISDIS', 'DISPAS')
_EXT_EQUIV_OF = {}
for _g in EXT_EQUIV:
    for _e in _g:
        _EXT_EQUIV_OF.setdefault(_e, tuple(x for _g2 in EXT_EQUIV if _e in _g2 for x in _g2 if x != _e))


_VARIANTS_MEMO = {}
_VARIANTS_MEMO_CAP = 200000


def variants(fname, ceiling=48, rounds=3):
    hash_key = (fname, ceiling, rounds)
    seq = _VARIANTS_MEMO.get(hash_key)
    if seq is None:
        if len(_VARIANTS_MEMO) >= _VARIANTS_MEMO_CAP:
            _VARIANTS_MEMO.clear()
        seq = _VARIANTS_MEMO[hash_key] = _variants_seq(fname, ceiling, rounds)
    return set(seq)


def _variants_seq(fname, ceiling=48, rounds=3):
    fname = fname.strip()
    if not fname:
        return ()
    fast_path = ':' not in fname and '/' not in fname and fname[:2] != '\\\\'
    join_lines = None if fast_path else os.path.join
    split, splitext = os.path.split, os.path.splitext
    equivalents = _EXT_EQUIV_OF
    current = {fname}
    direct = set()
    for r in range(rounds):
        new = set(current)
        add = new.add
        for n in sorted(current):
            if r and len(new) >= ceiling:
                break
            root, ext = splitext(n)
            e = ext.lower()
            for height in equivalents.get(e, ()):
                add(root + height)
            folder, base = split(root)
            if join_lines is None:
                pre = folder if not folder or folder[-1] == '\\' else folder + '\\'
            base_upper = base.upper()
            for p in PROTECTOR_PREFIXES:
                if base_upper.startswith(p):
                    x = base[len(p):].lstrip('_- ')
                    add((pre + x if join_lines is None else join_lines(folder, x)) + ext)
                elif join_lines is None:
                    add(pre + p + base + ext)
                    add(pre + p + '_' + base + ext)
                else:
                    add(join_lines(folder, p + base) + ext)
                    add(join_lines(folder, p + '_' + base) + ext)
            if not root.upper().endswith('_PORTRAIT'):
                add(root + '_PORTRAIT' + ext)
        if r == 0:
            direct = set(new)
        if new == current or len(new) >= ceiling:
            current = new
            break
        current = new
    if len(direct) >= ceiling:
        output = [n for n in sorted(direct)[:ceiling] if n]
    else:
        rest = sorted(current - direct)
        output = [n for n in list(direct) + rest[:ceiling - len(direct)] if n]
    root, ext = os.path.splitext(fname)
    if ext.lower() == '.mdl' and not root.upper().endswith('_PORTRAIT'):
        output.append(root + '_PORTRAIT.mdx')
    return tuple(output)


_EXTENSIONS_B = (
    rb'(?:mdx|mdl|blp|tga|jpg|dds|gif|png|wav|mp3|ogg|flac|aiff|aif|ttf|otf|woff|fdf|toc|slk|ini|txt|'
    rb'j|lua|w3a|w3t|w3u|w3d|w3b|w3h|w3q|w3i|w3e|w3r|w3c|w3s|wts|doo|shd|wpm|mmp|imp|pld)')
RE_PATH_B = re.compile(
    rb'[A-Za-z0-9_\-\\/\.\[\(!#$%&@^~{=][A-Za-z0-9_\-\\/\. \[\]\(\)\+!#$%&@^~{}=]{0,180}?\.' + _EXTENSIONS_B,
    re.I)
RE_EXTENSION_B = re.compile(rb'\.' + _EXTENSIONS_B, re.I)
RE_EXTENSION_NUL_B = re.compile(rb'\.' + _EXTENSIONS_B + rb'(?=\x00)', re.I)
PATH_REACH = 181
PATH_EXT_MAX = 4
RE_REQUIRE_B = re.compile(rb'''require\s*\(?\s*['"]([\w.\-/\\ ]{1,120})['"]''')


def _paths(data_bytes):
    segments = []
    for m in RE_EXTENSION_B.finditer(data_bytes):
        s, e = max(0, m.start() - PATH_REACH), m.start() + 1 + PATH_EXT_MAX
        if segments and s <= segments[-1][1]:
            segments[-1][1] = e
        else:
            segments.append([s, e])
    for s, e in segments:
        yield from RE_PATH_B.finditer(data_bytes, s, min(e, len(data_bytes)))


def nul_values(data_bytes):
    out = set()
    for m in RE_EXTENSION_NUL_B.finditer(data_bytes):
        i = m.start()
        j = i
        lim = max(0, i - 200)
        while j > lim and 0x20 <= data_bytes[j - 1] <= 0x7e:
            j -= 1
        if j < i and j > 0 and data_bytes[j - 1] == 0:
            out.add(data_bytes[j:m.end()])
    return out


def mdx_textures(data_bytes):
    out = set()
    i = data_bytes.find(b'TEXS')
    if i < 0 or i + 8 > len(data_bytes):
        return out
    sz = int.from_bytes(data_bytes[i + 4:i + 8], 'little')
    if sz % 268 or i + 8 + sz > len(data_bytes):
        return out
    for k in range(i + 8, i + 8 + sz, 268):
        c = data_bytes[k + 4:k + 264].split(b'\0')[0].decode('latin-1', 'replace').replace('/', '\\').strip()
        if c:
            out.add(c)
    return out


EXT_MODEL_TEXTURE = ('.mdx', '.mdl', '.blp', '.tga', '.dds', '.jpg')


def slk_dir_file(data_bytes):
    out = set()
    if not data_bytes.startswith(b'ID;'):
        return out
    try:
        import slk
        slk_columns, rows = slk.parse_slk_bytes(data_bytes)
    except Exception:
        return out
    cols = {str(c).lower(): c for c in slk_columns}
    cd, cf = cols.get('dir'), cols.get('file')
    if cd is None or cf is None:
        return out
    for row in rows.values():
        d = (row.get(cd) or '').strip().strip('"').replace('/', '\\').strip('\\')
        f = (row.get(cf) or '').strip().strip('"').replace('/', '\\').strip('\\')
        if not d or not f or d == '-' or f == '-' or f == '_':
            continue
        file_path = d + '\\' + f
        out.add(file_path)
        root = os.path.splitext(file_path)[0] if os.path.splitext(f)[1].lower() in EXT_MODEL_TEXTURE else file_path
        out.update(root + e for e in EXT_MODEL_TEXTURE)
        out.update(file_path + e for e in EXT_MODEL_TEXTURE)
    return out


def mine_bytes(data_bytes):
    out = set()
    if data_bytes[:4] == b'MDLX':
        out |= mdx_textures(data_bytes)
    elif data_bytes[:3] == b'ID;':
        out |= slk_dir_file(data_bytes)
    if b'\x00' in data_bytes:
        out.update(v.decode('latin-1').replace('/', '\\') for v in nul_values(data_bytes))
    out = set(n for n in out if not re.search(r'\.\.[\\/]', n))
    for m in _paths(data_bytes):
        s = m.group(0).decode('latin-1', 'replace').replace('/', '\\').strip()
        s = s.strip('"\' \t\r\n\x00')
        if not s or re.search(r'\.\.[\\/]', s):
            continue
        readings = [s]
        if '=' in s:
            readings.append(s.rsplit('=', 1)[-1].strip())
        if ' ' in s:
            words = s.split(' ')
            i = next((k for k, p in enumerate(words) if '\\' in p), None)
            if i:
                readings.append(' '.join(words[i:]))
            readings.append(words[-1])
        for s in readings:
            if not s:
                continue
            out.add(s)
            u = re.sub(r'\\{2,}', lambda _m: '\\', s)
            if u != s:
                out.add(u)
    if b'require' in data_bytes:
        for m in RE_REQUIRE_B.finditer(data_bytes):
            module = m.group(1).decode('latin-1').replace('/', '\\')
            file_path = module.replace('.', '\\')
            out.update((file_path + '.lua', file_path + '\\init.lua', module + '.lua'))
    return out


def _pairs_of_hash(a, ht, n_ht):
    cache = getattr(a, '_hash_pairs', None)
    if cache is None or cache[0] != n_ht or cache[1] is not ht:
        cache = (n_ht, ht, set(zip(ht[0:4 * n_ht:4], ht[1:4 * n_ht:4])))
        try:
            a._hash_pairs = cache
        except AttributeError:
            pass
    return cache[2]


def _with_hash_entry(a, name_list):
    ht = getattr(a, 'ht', None)
    n_ht = getattr(a, 'hash_n_read', None)
    if not name_list or ht is None or n_ht is None:
        return name_list
    import mpqlib as M
    pairs = _pairs_of_hash(a, ht, n_ht)
    enc = [n.encode('utf-8', 'surrogateescape') for n in name_list]
    h1, h2 = M.hashstr_batch(enc, 1), M.hashstr_batch(enc, 2)
    return [n for n, x, y in zip(name_list, h1, h2) if (int(x), int(y)) in pairs]


def referenced_closure(a, seeds=None, log=None, mines=None):
    if seeds is None:
        seeds = list(BASE_NAMES) + ['scripts\\war3map.j', 'war3map.imp', 'war3mapSkin.txt', 'war3mapMisc.txt',
                                    'war3mapPath.tga', 'war3map.w3s', 'war3mapUnits.doo']
        import map_formats
        seeds += [n for n in map_formats.standard_names() if n.startswith(map_formats.LOCALE_DIR)]
    seen = {}
    work_queue = []
    keys = set()

    def accept(n, from_game=False):
        k = n.upper()
        if k in keys:
            return
        r = a.find(n)
        ok = bool(r) and is_valid_name(a, r[1], n)
        if r and not ok and hasattr(a, 'find_locale'):
            r2 = a.find_locale(n)
            if r2 and r2[1] != r[1] and is_valid_name(a, r2[1], n):
                r, ok = r2, True
        if ok:
            if from_game:
                try:
                    d = a.read(n, bi=r[1])
                except Exception:
                    return
                if not d or not content_matches(n, d):
                    return
            keys.add(k)
            seen[n] = r[1]
            work_queue.append(n)

    for n in seeds:
        accept(n.replace('/', '\\'))
    for n in GAME_NAMES:
        accept(n, from_game=True)
    round_num = 0
    while work_queue:
        round_num += 1
        current, work_queue[:] = list(work_queue), []
        candidates = set()
        for n in current:
            if mines is not None and not mines(n):
                continue
            try:
                d = a.read(n, bi=seen[n])
            except Exception:
                continue
            if d:
                candidates |= mine_bytes(d[:16 * 1048576])
                if n.lower().endswith('war3map.lua') and d[:5] == b'--W3P':
                    try:
                        import packed_lua
                        candidates |= set(packed_lua.paths(d))
                    except Exception:
                        pass
        expanded = set()
        for c in candidates:
            expanded |= variants(c)
        for c in _with_hash_entry(a, [c for c in sorted(expanded) if c not in seen]):
            accept(c)
        if log:
            log(
                'closure, round %d: %d candidates, +%d referenced (total %d)'
                % (round_num, len(expanded), len(work_queue), len(seen))
            )
    return seen


SIGNATURES = {'.blp': (b'BLP1', b'BLP2', b'BLX1'), '.mdx': (b'MDLX',), '.w3x': (b'HM3W',), '.w3m': (b'HM3W',),
              '.w3n': (b'HM3W', b'MPQ\x1a'),
              '.wav': (b'RIFF',), '.mp3': (b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'), '.jpg': (b'\xff\xd8\xff',),
              '.dds': (b'DDS ',), '.exe': (b'MZ',), '.dll': (b'MZ',), '.asi': (b'MZ',), '.mix': (b'MZ',),
              '.m3d': (b'MZ',), '.flt': (b'MZ',), '.ogg': (b'OggS',), '.png': (b'\x89PNG',),
              '.flac': (b'fLaC', b'ID3'), '.aif': (b'FORM',), '.aiff': (b'FORM',), '.woff': (b'wOFF',),
              '.gif': (b'GIF87a', b'GIF89a'), '.zip': (b'PK\x03\x04',), '.rar': (b'Rar!',), '.7z': (b'7z\xbc\xaf',)}
EXT_TEXT = frozenset(('.ai', '.j', '.txt', '.fdf', '.toc', '.slk', '.html', '.pld', '.lua', '.ini', '.js', '.css',
                      '.wai', '.htm', '.xml', '.json', '.md', '.csv'))


def looks_random(data_bytes, n=4096):
    head_line = data_bytes[:n]
    if len(head_line) < 1024:
        return False
    expected_len = len(head_line) / 256.0
    tally = [0] * 256
    for c in head_line:
        tally[c] += 1
    return sum((x - expected_len) ** 2 for x in tally) / expected_len < 400


def content_matches(fname, data_bytes, raw_data=False):
    ext = os.path.splitext(fname)[1].lower()
    if ext in SIGNATURES:
        return data_bytes.startswith(SIGNATURES[ext])
    if ext in EXT_TEXT:
        head_line = data_bytes[:4096]
        if any(head_line.startswith(s) for ss in SIGNATURES.values() for s in ss):
            return False
        return not any(c < 9 or 13 < c < 32 for c in head_line if c not in (27, 30, 31))
    return not (raw_data and looks_random(data_bytes))


def read_by_name(a, bi, fname):
    try:
        data_bytes = a.read(fname, bi=bi)
    except Exception:
        return False
    return data_bytes is not None and len(data_bytes) == a.blocks[bi][2] and content_matches(fname, data_bytes)


def is_valid_name(a, bi, fname):
    import mpqread
    v, detail = a.validate(bi, fname)
    if v != 'ok':
        return v == 'invalid' and read_by_name(a, bi, fname)
    if detail in mpqread.VALID_FOR_GAME:
        try:
            return content_matches(fname, a.read(fname, bi=bi) or b'')
        except Exception:
            return False
    return True


BASE_NAMES = (
    'war3map.j', 'war3map.lua', 'war3map.w3i', 'war3map.wts', 'war3map.wtg',
    'war3map.wct', 'war3map.w3e', 'war3map.w3a', 'war3map.w3b', 'war3map.w3d',
    'war3map.w3h', 'war3map.w3q', 'war3map.w3t', 'war3map.w3u', 'war3map.w3c',
    'war3map.w3s', 'war3map.w3r', 'war3map.wpm', 'war3map.doo', 'war3map.shd',
    'war3map.mmp', 'war3map.imp', 'war3mapMisc.txt', 'war3mapSkin.txt',
    'war3mapExtra.txt', 'war3MapUnits.doo', 'war3mapMap.blp', 'war3mapPreview.tga',
    'war3mapSkin.w3u', 'war3mapSkin.w3t', 'war3mapSkin.w3a', 'war3mapSkin.w3b', 'war3mapSkin.w3d', 'war3mapSkin.w3h',
    'war3mapSkin.w3q',
    'conversation.json', 'war3map.w3l', 'war3mapPostProcessing.txt', 'war3map.w3grp', 'war3map.soundasset',
)

GAME_NAMES = tuple(
    [
        'Scripts\\Blizzard.j',
        'Scripts\\common.j',
        'Units\\MiscData.txt',
        'Units\\MiscGame.txt',
        'UI\\MiscData.txt',
        'Doodads\\Doodads.slk',
    ]
    + [
        'Units\\%s.slk' % n
        for n in (
            'UnitData',
            'UnitUI',
            'UnitBalance',
            'UnitAbilities',
            'UnitWeapons',
            'ItemData',
            'AbilityData',
            'AbilityBuffData',
            'UpgradeData',
            'DestructableData',
        )
    ]
    + [
        'Units\\%s%s%s.txt' % (r, t, s)
        for r in ('Campaign', 'Human', 'Orc', 'Undead', 'NightElf', 'Neutral')
        for t in ('Unit', 'Ability', 'Upgrade')
        for s in ('Func', 'Strings')
    ]
    + [
        'Units\\%s.txt' % n
        for n in (
            'ItemFunc',
            'ItemStrings',
            'ItemAbilityFunc',
            'ItemAbilityStrings',
            'CommonAbilityFunc',
            'CommonAbilityStrings',
            'CommandFunc',
            'CommandStrings',
        )
    ]
    + ['Units\\%sSkin.txt' % n for n in ('Unit', 'Item', 'Ability', 'Upgrade', 'Destructable')]
    + ['Doodads\\DoodadSkins.txt']
)

