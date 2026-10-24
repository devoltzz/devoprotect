# Finds the imported files the game never reads, and removes them keeping every file it does read.
import os
import re
import shutil
import struct
import time



GAME_FOLDERS = frozenset((
    'abilities', 'achievement', 'ai scripts', 'battlenet', 'buildings', 'campaign', 'cinematics', 'collection',
    'cutscenes', 'doodads', 'editor', 'environment', 'facialanimation', 'fonts', 'maps', 'meshes', 'movies', 'objects',
    'pathtextures', 'replaceabletextures', 'scripts', 'shaders', 'sharedfx', 'sharedmodels', 'sound', 'splats',
    'strings', 'terrainart', 'textures', 'ui', 'units', 'webui', 'x86_64'))
EDITOR = frozenset(('war3map.imp', 'war3map.wtg', 'war3map.wct', 'war3map.w3s', 'war3map.w3c', 'war3map.w3r'))
CONTROL_BYTE = frozenset(('(listfile)', '(attributes)', '(signature)'))
RX_TOKEN = re.compile(rb'[^\x00-\x1f"\'\\/:*?<>|\x7f]{2,200}')
BUILT_EXTENSIONS = (
    'mdx',
    'mdl',
    'blp',
    'tga',
    'dds',
    'png',
    'jpg',
    'wav',
    'mp3',
    'ogg',
    'flac',
    'ttf',
    'fdf',
    'toc',
    'txt',
    'slk',
    'ai',
    'pld',
)
MEDIA = ('.blp', '.dds', '.tga', '.png', '.jpg', '.jpeg', '.bmp', '.mp3', '.wav', '.ogg', '.flac', '.ttf', '.otf',
         '.mp4', '.webm', '.avi', '.bik')
BS = '\\'


def _nothing(*_a, **_k):
    pass


def cites(fname):
    return not fname.lower().endswith(MEDIA)


def alias_names(fname):
    base = fname.replace('/', BS).split(BS)[-1].lower()
    root = os.path.splitext(base)[0]
    out = {base, root}
    no_digits = root.rstrip('0123456789')
    if no_digits and no_digits != root:
        out.add(no_digits)
    if root.endswith('_portrait'):
        out.add(root[:-9])
    for pre in ('disbtn', 'dispas', 'disatc'):
        if root.startswith(pre):
            out.add(root[3:])
    return set(a for a in out if len(a) >= 2)


RX_LIST = re.compile(r'[,;=]+')
RX_LIST_SPACE = re.compile(r'[,;=\s()\[\]{}]+')


def _without_ext(s):
    i = s.rfind('.')
    return s[:i] if i > 0 and s[:i].strip('.') else s


def tokens(data_bytes):
    piece_list = set()
    for t in set(RX_TOKEN.findall(data_bytes.lower())):
        s = t.decode('latin-1')
        piece_list.add(s)
        piece_list.update(RX_LIST.split(s))
        piece_list.update(RX_LIST_SPACE.split(s))
    out = set()
    for s in piece_list:
        s = s.strip(' .,;)(][}{')
        if len(s) < 2:
            continue
        r = _without_ext(s)
        out.add(s)
        out.add(r)
        out.add(r.rstrip('0123456789'))
    return out


def in_game_folder(fname):
    pieces = fname.replace('/', BS).split(BS)
    if len(pieces) == 1:
        return fname.lower().startswith(('war3map', 'war3campaign'))
    topo = pieces[0].lower()
    return topo in GAME_FOLDERS or topo.startswith('_')


def _running_names(script):
    try:
        import runtime_names
        r = runtime_names.file_names(script)
    except Exception:
        return set()
    return set(n.replace('/', BS).lower() for n in (r.get('names') or ()))


def analyze(file_path, extra_script=None, log=None):
    import editor_lock
    import dds_to_blp
    import map_formats
    import mpqnames
    import mpqread
    log = log or _nothing
    t0 = time.time()
    a = mpqread.Archive(file_path)
    name_list, seen = [], set()
    for n in editor_lock.map_names(a):
        k = n.replace('/', BS).lower()
        if k not in seen:
            seen.add(k)
            name_list.append(n)
    data_bytes, sz = {}, {}
    for n in name_list:
        if n.lower() in CONTROL_BYTE:
            continue
        d = editor_lock._read(a, n)
        if d is not None:
            sz[n] = len(d)
            data_bytes[n] = d if cites(n) else None
    default_value = set(n.lower() for n in map_formats.standard_names())
    scripts = [data_bytes[n] for n in data_bytes if n.replace('/', BS).lower() in ('war3map.j', 'scripts\\war3map.j',
                                                                          'war3map.lua')]
    if extra_script:
        scripts.append(extra_script)
    built_names = {}
    for e in BUILT_EXTENSIONS:
        prefixes = None
        for s in scripts:
            p = dds_to_blp.built_prefixes(s, e)
            if p is False:
                prefixes = False
                break
            if p:
                prefixes = (prefixes or set()) | set(x.decode('latin-1') if isinstance(x, bytes) else x for x in p)
        if prefixes is not None:
            built_names[e] = prefixes
    running_scope = set()
    for s in scripts:
        if b'function main' in s and b'endfunction' in s:
            running_scope |= _running_names(s)
    running_base = set(x.split(BS)[-1] for x in running_scope)
    keep, kept_why = set(), {}

    def keep_names(n, rule):
        keep.add(n)
        kept_why[rule] = kept_why.get(rule, 0) + 1
    candidates = [n for n in data_bytes if n.replace('/', BS).lower() not in EDITOR]
    for n in candidates:
        if n.replace('/', BS).lower() in default_value or in_game_folder(n):
            keep_names(n, 'game')
    toks = set(tokens(extra_script)) if extra_script else set()
    read_count = set()
    seeds = [x for x in mpqnames.BASE_NAMES if x.lower() not in EDITOR]
    seeds += ['scripts\\war3map.j', 'war3mapSkin.txt', 'war3mapMisc.txt', 'war3mapPath.tga']
    seeds += [x for x in map_formats.standard_names() if x.startswith(map_formats.LOCALE_DIR)]
    reached, seeded = set(), set()
    for _goes_back in range(16):
        changed = False
        for n in sorted(keep | set(x for x in candidates if x.replace('/', BS).upper() in reached)):
            if n not in read_count:
                read_count.add(n)
                if data_bytes[n] is not None:
                    toks |= tokens(data_bytes[n])
        for n in candidates:
            if n in keep:
                continue
            low = n.replace('/', BS).lower()
            if alias_names(n) & toks:
                keep_names(n, 'cited_flag')
            elif low in running_scope or low.split(BS)[-1] in running_base:
                keep_names(n, 'running_scope')
            else:
                e = os.path.splitext(low)[1][1:]
                m = built_names.get(e)
                if not (m is False or (m and any(low.startswith(x) for x in m))):
                    continue
                keep_names(n, 'assembled')
            if data_bytes[n] is not None:
                toks |= tokens(data_bytes[n])
            read_count.add(n)
            changed = True
        new_ones = sorted(keep - seeded)
        if new_ones or _goes_back == 0:
            seeded |= set(new_ones)
            closure = mpqnames.referenced_closure(a, seeds=(seeds if _goes_back == 0 else []) +
                                                  [x for x in new_ones if cites(x)], mines=cites)
            before = len(reached)
            reached |= set(x.replace('/', BS).upper() for x in closure)
            changed = changed or len(reached) != before
        if not changed:
            break
    out_path = sorted((n, sz[n]) for n in candidates
                      if n not in keep and n.replace('/', BS).upper() not in reached)
    log('[no_use] %d file(s), %d unused (%d B)' % (len(sz), len(out_path), sum(b for _n, b in out_path)))
    return {'out_path': out_path, 'file_set': len(sz), 'keep': kept_why,
            'built_names': dict((e, sorted(v) if v else v) for e, v in built_names.items()),
            'seconds': round(time.time() - t0, 1)}


def imp_without(data_bytes, name_list):
    wanted = set(n.replace('/', BS).upper() for n in name_list)
    try:
        version_num, n = struct.unpack_from('<ii', data_bytes, 0)
        p, mantidas, removed_count = 8, [], 0
        for _ in range(n):
            f = data_bytes.index(b'\0', p + 1)
            brute = data_bytes[p:f + 1]
            fname = data_bytes[p + 1:f].decode('utf-8', 'surrogateescape').replace('/', BS).upper()
            if fname in wanted or 'WAR3MAPIMPORTED\\' + fname in wanted:
                removed_count += 1
            else:
                mantidas.append(brute)
            p = f + 1
    except (struct.error, ValueError):
        return data_bytes, 0
    if not removed_count:
        return data_bytes, 0
    return struct.pack('<ii', version_num, len(mantidas)) + b''.join(mantidas) + data_bytes[p:], removed_count


def _listfile_without(data_bytes, name_list):
    wanted = set(n.replace('/', BS).lower() for n in name_list)
    line_list = data_bytes.splitlines(True)
    keep = [
        lx for lx in line_list if lx.strip().decode('utf-8', 'surrogateescape').replace('/', BS).lower() not in wanted
    ]
    return b''.join(keep), len(line_list) - len(keep)


def remove(entry, output, extra_script=None, log=print):
    import editor_lock
    import mpqadd
    import mpqread
    r = analyze(entry, extra_script=extra_script, log=log)
    name_list = [n for n, _b in r['out_path']]
    res = dict(r, removed=r['out_path'], bytes=sum(b for _n, b in r['out_path']), imp=0, listfile=0)
    shutil.copyfile(entry, output)
    if not name_list:
        return res
    a = mpqread.Archive(entry)
    repl = []
    imp = editor_lock._read(a, 'war3map.imp')
    if imp:
        new, removed_count = imp_without(imp, name_list)
        if removed_count:
            repl.append(('war3map.imp', new))
            res['imp'] = removed_count
    listing = editor_lock._read(a, '(listfile)')
    if listing:
        new, removed_count = _listfile_without(listing, name_list)
        if removed_count:
            repl.append(('(listfile)', new))
            res['listfile'] = removed_count
    mpqadd.add_files(output, repl, to_delete=name_list, log=_nothing)
    b = mpqread.Archive(output)
    sobrou = [n for n in name_list if b.find(n) is not None]
    if sobrou:
        raise SystemExit('no_use: the entry of %s is still in the map' % sobrou[:3])
    return res
