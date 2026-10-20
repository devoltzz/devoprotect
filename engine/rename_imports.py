# Renames the imported files a map cites to meaningless names, and points every reference at them.
import hashlib
import random
import re
import shutil
import time


FOLDER = 'war3mapImported\\'
MODEL_LEVELS = ('.mdx', '.mdl')
IMAGES = ('.blp', '.dds', '.tga')
NOT_CITE = ('(listfile)', '(attributes)', '(signature)', 'war3map.imp')
NOT_READ = ('(attributes)', '(signature)')
ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
ATTEMPTS = 400


def _norm(n):
    return n.replace('/', '\\').lower()


def _split(fname):
    p = fname.replace('/', '\\')
    i = p.rfind('\\')
    folder, file_ = (p[:i + 1], p[i + 1:]) if i >= 0 else ('', p)
    j = file_.rfind('.')
    return folder, file_[:j] if j > 0 else file_, file_[j:] if j > 0 else ''


RX_W3P_PATH = re.compile(rb'war3mapimported(?:\\|/)+[^\x00"\'<>\r\n\x01-\x1f\x7f]{1,220}', re.IGNORECASE)
END_TRIM = b',);]} \t'


def _cited(data_bytes):
    out = set()
    for m in RX_W3P_PATH.finditer(data_bytes):
        p = m.group(0).rstrip(END_TRIM)
        p = re.sub(rb'\\{2,}', rb'\\', p)
        try:
            out.add(p.decode('utf-8', 'surrogateescape').replace('/', '\\').lower())
        except Exception:
            continue
    return out


def _without_mark(stem, folder, ext, existing_ones):
    pre = ''
    s = stem
    if ext.lower() in IMAGES and len(s) > 3 and s[:3].lower() == 'dis' and \
            _norm(folder + s[3:] + ext) in existing_ones:
        pre, s = s[:3], s[3:]
    suf = ''
    if ext.lower() in MODEL_LEVELS:
        changed = True
        while changed:
            changed = False
            m = re.search(r'(?i)(_portrait)$', s)
            if m and _norm(folder + s[:-len(m.group(1))] + ext) in existing_ones:
                suf, s = m.group(1) + suf, s[:-len(m.group(1))]
                changed = True
                continue
            m = re.search(r'(\d+)$', s)
            if m and len(m.group(1)) < len(s) and _norm(folder + s[:-len(m.group(1))] + ext) in existing_ones:
                suf, s = m.group(1) + suf, s[:-len(m.group(1))]
                changed = True
    return pre, s, suf


def _forms(fname, exts=None):
    folder, stem, ext = _split(fname)
    if exts is None:
        exts = [ext] if ext.lower() not in MODEL_LEVELS else [ext, '.mdx', '.MDX', '.mdl', '.MDL']
    out = set()
    for e in exts:
        for sep in ('\\', '/', '\\\\'):
            out.add((folder + stem + e).replace('\\', sep))
    return out


def _rx_forms(name_list, exts=None):
    forms = set()
    for n in name_list:
        forms |= _forms(n, exts)
    height = b'|'.join(re.escape(f.encode('utf-8', 'surrogateescape'))
                       for f in sorted(forms, key=len, reverse=True))
    return re.compile(rb'(?<![0-9A-Za-z._\-\x80-\xff])(?:' + height + rb')(?![0-9A-Za-z])', re.IGNORECASE)


def _swap(rx, map_path, data_bytes):
    n = [0]

    def sub(m):
        s = m.group(0)
        i = max(s.rfind(b'\\'), s.rfind(b'/'))
        folder, file_ = (s[:i + 1], s[i + 1:]) if i >= 0 else (b'', s)
        try:
            hash_key = (folder + file_).decode('utf-8', 'surrogateescape').replace('/', '\\').lower()
        except Exception:
            return s
        tgt = map_path.get(hash_key)
        if tgt is None:
            key2 = re.sub(r'\\{2,}', r'\\', hash_key)
            tgt = map_path.get(key2)
        if tgt is None:
            return s
        new_stem, old_ext = tgt
        base, ext = file_, b''
        for e in (b'.mdx', b'.MDX', b'.mdl', b'.MDL'):
            if base.endswith(e):
                ext, base = base[-len(e):], base[:-len(e)]
                break
        else:
            if old_ext and base.lower().endswith(old_ext.lower().encode('utf-8', 'surrogateescape')):
                ext = base[-len(old_ext):]
                base = base[:-len(old_ext)]
        new = folder + new_stem.encode('utf-8', 'surrogateescape') + ext
        if len(new) != len(s):
            return s
        n[0] += 1
        return new

    return rx.sub(sub, data_bytes), n[0]


def _seed(entry, seed):
    if seed is not None:
        return int(seed)
    with open(entry, 'rb') as f:
        h = hashlib.sha256()
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return int.from_bytes(h.digest()[:8], 'little')


def renomeia(entry, output, seed=None, keep_names=(), log=print):
    import editor_lock
    import mpqadd
    import mpqread
    t0 = time.time()
    a = mpqread.Archive(entry)
    name_list = list(editor_lock.map_names(a))
    keep_names = set(_norm(x) for x in (keep_names or ()) if x)
    contents = {}
    for n in name_list:
        if n.lower() in NOT_READ:
            continue
        d = editor_lock._read(a, n)
        if d is not None:
            contents[n] = d
    cand = [n for n in contents if _norm(n).startswith(_norm(FOLDER))]
    existing_ones = set(_norm(n) for n in cand)
    if not cand:
        details = {'ok': True, 'renamed': 0, 'citations': {}, 'skipped': {}, 'seed': seed,
                   'gate': 'ok (no imported file in war3mapImported\\)', 'seconds': round(time.time() - t0, 1)}
        log('[imports] %s' % details['gate'])
        shutil.copyfile(entry, output)
        return details
    in_use = dict((n, set()) for n in cand)
    for n, d in contents.items():
        if n.lower() in NOT_CITE:
            continue
        for c in _cited(d):
            for tgt in cand:
                folder, stem, ext = _split(tgt)
                if c == _norm(folder + stem + ext) or (ext.lower() in MODEL_LEVELS and c in (
                        _norm(folder + stem + '.mdx'), _norm(folder + stem + '.mdl'))):
                    in_use[tgt].add(n)
    families = {}
    for n in cand:
        folder, stem, ext = _split(n)
        pre, base, suf = _without_mark(stem, folder, ext, existing_ones)
        hash_key = (folder.lower(), base.lower(), ext.lower())
        families.setdefault(hash_key, {'base': folder + base + ext, 'members': {}, 'cited_flag': False})
        families[hash_key]['members'][n] = (pre, suf)
        if in_use.get(n):
            families[hash_key]['cited_flag'] = True
    seed_value = _seed(entry, seed)
    rng = random.Random(seed_value)
    new_ones = {}
    skipped = {}
    for hash_key, fam in sorted(families.items()):
        folder, base, ext = _split(fam['base'])
        if not fam['cited_flag']:
            for m in fam['members']:
                skipped[m] = 'no file of the game cites it'
            continue
        if any(_norm(folder + base + ext) == x or _norm(m) in keep_names for m in fam['members'] for x in keep_names):
            for m in fam['members']:
                skipped[m] = 'retained'
            continue
        sz = len(base.encode('utf-8', 'surrogateescape'))
        if sz < 1:
            for m in fam['members']:
                skipped[m] = 'name without a base'
            continue
        token = None
        for _ in range(ATTEMPTS):
            t = ''.join(rng.choice(ALPHABET) for _ in range(sz))
            ok = True
            for m in fam['members']:
                p, _s, e = _split(m)
                pre, suf = fam['members'][m]
                new = p + pre + t + suf + e
                if _norm(new) in existing_ones or new in new_ones.values():
                    ok = False
                    break
            if ok:
                token = t
                break
        if token is None:
            for m in fam['members']:
                skipped[m] = 'no free name of the same length'
            continue
        for m in fam['members']:
            p, _s, e = _split(m)
            pre, suf = fam['members'][m]
            new_ones[m] = p + pre + token + suf + e
    def _value(n):
        return (_split(new_ones[n])[1], _split(n)[2])
    map_path = {}
    for n in new_ones:
        for f in _forms(n, [_split(n)[2]]):
            map_path.setdefault(f.lower(), _value(n))
    for n in sorted(new_ones, key=lambda x: ('.mdx' not in x.lower(), x)):
        ext = _split(n)[2]
        if ext.lower() in MODEL_LEVELS:
            other_entries = [e for e in ('.mdx', '.MDX', '.mdl', '.MDL') if e.lower() != ext.lower()]
            for f in _forms(n, other_entries):
                map_path.setdefault(f.lower(), _value(n))
    rx = _rx_forms(new_ones) if new_ones else None
    touch = set(new_ones)
    if rx is not None:
        for n, d in contents.items():
            if n.lower() not in NOT_READ and rx.search(d):
                touch.add(n)
    replacements = {}
    citations = {}
    for n in sorted(touch):
        d = contents.get(n)
        if d is None:
            continue
        new_d, k = _swap(rx, map_path, d) if rx is not None else (d, 0)
        if k:
            citations[n] = k
        if n in new_ones:
            replacements[new_ones[n]] = new_d
        elif new_d != d:
            replacements[n] = new_d
    shutil.copyfile(entry, output)
    mpqadd.add_files(output, sorted(replacements.items()), to_delete=list(new_ones), grow=list(contents),
                     log=lambda *x: None)
    b = mpqread.Archive(output)
    bad_ones = []
    total_cit = sum(len(x) for x in in_use.values())
    if total_cit and not sum(citations.values()):
        bad_ones.append('no citation repointed (%d file(s) cited it)' % total_cit)
    for old, new in new_ones.items():
        d = replacements.get(new)
        if b.find(new) is None:
            bad_ones.append('the new %s is not in the map' % new)
        elif d is not None and b.read(new) != d:
            bad_ones.append('the new %s is not the written one' % new)
        if b.find(old) is not None:
            bad_ones.append('the old %s is still in the map' % old)
        if d is not None and len(d) != len(contents.get(old, b'')):
            bad_ones.append('the length of %s changed' % old)
    if new_ones:
        rx_old = _rx_forms(new_ones)
        for n in list(editor_lock.map_names(b)) + list(new_ones.values()):
            d = editor_lock._read(b, n)
            if d and rx_old.search(d):
                bad_ones.append('%s still cites an old name' % n)
                break
    details = {'ok': not bad_ones, 'renamed': len(new_ones), 'citations': citations,
               'skipped': skipped, 'seed': seed_value,
               'gate': ('ok (%d imported file(s) renamed, %d file(s) repointed)'
                        % (len(new_ones), len(citations))) if not bad_ones else 'FAILED: %s' % bad_ones[:6],
               'seconds': round(time.time() - t0, 1)}
    details['replacements'] = dict((v, k) for k, v in new_ones.items())
    log('[imports] %s' % details['gate'])
    return details
