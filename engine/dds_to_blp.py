# Converts the DDS, TGA and PNG textures of a map to BLP and points every reference at the new file.
import io
import os
import re
import tempfile
import zlib




def _rx_repoint(name_list):
    forms = set()
    for n in name_list:
        b = n.replace('/', '\\')
        forms.add(b)
        forms.add(b.replace('\\', '/'))
        forms.add(b.replace('\\', '\\\\'))
    height = b'|'.join(re.escape(f.encode('utf-8', 'surrogateescape')) for f in sorted(forms, key=len, reverse=True))
    return re.compile(rb'(?<![0-9A-Za-z._\-\x80-\xff])(?:' + height + rb')(?![0-9A-Za-z])', re.IGNORECASE)


_RX_DDS = re.compile(rb'\.dds', re.IGNORECASE)


def _blp_bytes(dds_data, cap_kb=256):
    import blpwrite
    from PIL import Image
    im = Image.open(io.BytesIO(dds_data))
    im.load()
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA')
    with tempfile.NamedTemporaryFile(suffix='.blp', delete=False) as f:
        tmp = f.name
    try:
        blpwrite.save_blp_fit(im, tmp, cap_kb * 1024)
        with open(tmp, 'rb') as f:
            return f.read(), im.size
    finally:
        os.unlink(tmp)


TYPES = ('dds', 'tga', 'png')
_RX_KIND = {'dds': _RX_DDS, 'tga': re.compile(rb'\.tga', re.IGNORECASE), 'png': re.compile(rb'\.png', re.IGNORECASE)}
_RX_BUILT = dict((t, re.compile(rb'(?:(?:\+|\.\.)\s*["\'][^"\'\r\n]*|["\'])\.' + t.encode() + rb'["\']',
                                re.IGNORECASE)) for t in ('tga', 'png'))
_RX_TOKEN = re.compile(rb'"(?:\\.|[^"\\\r\n])*"|\'(?:\\.|[^\'\\\r\n])*\'|\.\.|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|\S')
TEXTURE_NATIVES = (b'DzFrameSetTexture', b'BlzFrameSetTexture')


def _operand_start(toks, i):
    t = toks[i]
    if t in (b')', b']'):
        opens, on_close = (b'(', b')') if t == b')' else (b'[', b']')
        max_depth, k = 0, i
        while k >= 0:
            if toks[k] == on_close:
                max_depth += 1
            elif toks[k] == opens:
                max_depth -= 1
                if not max_depth:
                    break
            k -= 1
        if k < 0:
            return None
        if k > 0 and re.match(rb'[A-Za-z_]', toks[k - 1]):
            k -= 1
        return None if k > 0 and toks[k - 1] in (b'.', b':') else k
    if t[:1] in (b'"', b"'") or re.match(rb'[A-Za-z_\d]', t):
        return None if i > 0 and toks[i - 1] in (b'.', b':') else i
    return None


def _call_of(toks, i):
    max_depth, k = 0, i - 1
    while k >= 0:
        if toks[k] in (b')', b']'):
            max_depth += 1
        elif toks[k] in (b'(', b'['):
            if not max_depth:
                return toks[k - 1] if toks[k] == b'(' and k > 0 else None
            max_depth -= 1
        k -= 1
    return None


def built_prefixes(script, type_name):
    matches = list(_RX_BUILT[type_name].finditer(script))
    if not matches:
        return None
    prefixes = set()
    for m in matches:
        begin = max(script.rfind(b'\n', 0, m.start()), script.rfind(b'\r', 0, m.start())) + 1
        toks = _RX_TOKEN.findall(script[begin:m.end()])
        if not toks or toks[-1][:1] not in (b'"', b"'"):
            return False
        i, operands = len(toks) - 1, []
        while True:
            j = _operand_start(toks, i)
            if j is None:
                return False
            operands.append(toks[j:i + 1])
            if j >= 2 and toks[j - 1] in (b'+', b'..'):
                i = j - 2
                continue
            break
        if len(operands) == 1:
            if _call_of(toks, len(toks) - 1) not in TEXTURE_NATIVES:
                return False
            continue
        first = operands[-1]
        if len(first) != 1 or first[0][:1] not in (b'"', b"'"):
            return False
        prefixes.add(first[0][1:-1].decode('utf-8', 'surrogateescape').replace('\\\\', '\\').replace('/', '\\')
                     .lower())
    return prefixes


def _starts_with(name_low, prefixes):
    file_path = '\\' + name_low
    return next((p for p in sorted(prefixes) if file_path.find('\\' + p) >= 0), None)
_NAME_END = frozenset(b'"\'=,;|<>*?:')
LIST_FILES = ('(listfile)', '(attributes)', '(signature)', 'war3map.imp', 'war3campaign.imp')


def _stored_size(d, sector_bytes=None):
    if not sector_bytes:
        return len(zlib.compress(d, 9))
    return 4 + sum(
        min(len(zlib.compress(d[i : i + sector_bytes], 9)), len(d[i : i + sector_bytes])) + 4
        for i in range(0, len(d), sector_bytes)
    )


def blp_from_image(data_bytes, sector_bytes=None):
    import blpwrite
    from PIL import Image
    im = Image.open(io.BytesIO(data_bytes))
    im.load()
    rgba = im.convert('RGBA')
    info = {
        'dim': rgba.size,
        'format': None,
        'stored_before': _stored_size(data_bytes, sector_bytes),
        'given_palette': None,
    }
    words = blpwrite.blp_palette_bytes(rgba)
    if words is not None:
        info['given_palette'] = _stored_size(words, sector_bytes)
        if info['given_palette'] < info['stored_before']:
            info.update(format='paletted', stored_after=info['given_palette'])
            return words, info
    _n, jpg = blpwrite.blp_jpeg_bytes(rgba, 100, qtable=blpwrite.QTABLE_HIGH)
    info['jpeg'] = _stored_size(jpg, sector_bytes)
    if info['jpeg'] < info['stored_before']:
        info.update(format='jpeg', stored_after=info['jpeg'])
        return jpg, info
    return None, info


def _is_pow2(n):
    return n > 0 and n & (n - 1) == 0


def _cited_names(data_bytes, rx_ext):
    out = set()
    for m in rx_ext.finditer(data_bytes):
        end_pos = m.end()
        if end_pos < len(data_bytes) and (
            48 <= data_bytes[end_pos] <= 57 or 65 <= data_bytes[end_pos] <= 90 or 97 <= data_bytes[end_pos] <= 122
        ):
            continue
        begin, lim = m.start(), max(0, end_pos - 260)
        while begin > lim and data_bytes[begin - 1] >= 0x20 and data_bytes[begin - 1] not in _NAME_END:
            begin -= 1
        s = (
            data_bytes[begin:end_pos]
            .decode('utf-8', 'surrogateescape')
            .replace('\\\\', '\\')
            .replace('/', '\\')
            .lower()
        )
        pieces = s.split('\\')
        for k in range(len(pieces)):
            out.add('\\'.join(pieces[k:]))
    return out


def converte(entry, output, only_smaller=False, log=print, types=('dds',), sector_bytes=None):
    import editor_lock
    import blpread
    import mpqadd
    import mpqread
    import shutil
    import struct
    types = tuple(t for t in TYPES if t in set(types))
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if entry == output:
        raise SystemExit('the output must be another file (the input never changes)')
    a = mpqread.Archive(entry)
    name_list, names_low = [], set()
    for n in editor_lock.map_names(a):
        if n.lower() not in names_low:
            names_low.add(n.lower())
            name_list.append(n)

    def type_of(n):
        ext = n.lower()[-4:]
        return ext[1:] if ext[:1] == '.' and ext[1:] in types else None
    dds = [n for n in name_list if n.lower().endswith('.dds')] if 'dds' in types else []
    images = [n for n in name_list if type_of(n) in ('tga', 'png')]
    details = {'entry': entry, 'output': output, 'dds': len(dds), 'types': list(types), 'matrix': {}, 'replaced': 0,
               'ok': False}
    for t in types:
        if t != 'dds':
            details[t] = len([n for n in images if type_of(n) == t])
    shutil.copyfile(entry, output)
    targets = dds + images
    if not targets:
        details['ok'] = True
        log('[dds] no %s in the map' % '/'.join('.' + t for t in types))
        return details
    rx_tipos = re.compile(rb'\.(?:' + b'|'.join(t.encode() for t in types) + rb')', re.IGNORECASE)
    targets_low = set(n.lower() for n in targets)
    cited_before = []
    for n in name_list:
        d = editor_lock._read(a, n)
        if d and rx_tipos.search(d):
            cited_before.append((n, d))
    cited, built_names, w3i_version, by_ext = {}, {}, None, {}
    if images:
        for t in ('tga', 'png'):
            if t in types:
                kind_cited = set()
                for n, d in cited_before:
                    if n.lower() not in targets_low and n.lower() not in LIST_FILES and _RX_KIND[t].search(d):
                        kind_cited |= _cited_names(d, _RX_KIND[t])
                cited[t] = kind_cited
        lua_bytes = editor_lock._read(a, 'war3map.lua')
        _script_name, script = ('war3map.lua', lua_bytes) if lua_bytes else editor_lock._script(a)
        for t in ('tga', 'png'):
            r = built_prefixes(script, t) if t in types and script else None
            if r is not None:
                built_names[t] = r
        w3i = editor_lock._read(a, 'war3map.w3i')
        if w3i and len(w3i) >= 4:
            w3i_version = struct.unpack_from('<i', w3i, 0)[0]
        for x in names_low:
            x = x.replace('/', '\\')
            by_ext.setdefault(x[-4:], []).append(x)
    name_swaps = []
    write_out, to_delete = [], []
    stored_value = {}
    for n in targets:
        t = type_of(n) or 'dds'
        new_name = n[:-4] + ('.BLP' if n[-4:].isupper() else '.blp')
        info = None
        if t == 'dds':
            d = editor_lock._read(a, n)
            if d is None:
                continue
            try:
                new_ones, dim = _blp_bytes(d)
            except Exception as e:
                details['matrix'][n] = {
                    'action_code': 'not touched',
                    'why': 'Pillow cannot read the .dds (%s)' % str(e)[:60],
                }
                log('[dds] %s: Pillow cannot read it (%s)' % (n, str(e)[:60]))
                continue
            if only_smaller and len(new_ones) >= len(d):
                details['matrix'][n] = {
                    'action_code': 'retained',
                    'why': 'the BLP (%d B) did not get smaller than the DDS (%d B)' % (len(new_ones), len(d)),
                }
                continue
            if new_name.lower() in names_low and new_name.lower() != n.lower():
                details['matrix'][n] = {'action_code': 'retained', 'why': '%s already exists in the map' % new_name}
                log('[dds] %s kept: %s already exists' % (n, new_name))
                continue
        else:
            n_low = n.lower().replace('/', '\\')
            why, d = None, None
            if '\\' not in n_low and n_low.startswith(('war3map', 'war3campaign')):
                why = 'the game reads this fixed name'
            elif built_names.get(t) is False:
                why = 'the script builds .%s names while the game runs' % t
            elif t in built_names and _starts_with(n_low, built_names[t]) is not None:
                why = 'the script builds names that start like this one (%s)' % _starts_with(n_low, built_names[t])
            elif n_low not in cited.get(t, ()):
                why = 'no file of the map cites it (the game may read it by name)'
            elif new_name.lower() in names_low:
                why = '%s already exists in the map' % new_name
            elif any(x != n_low and x.endswith('\\' + n_low) for x in by_ext.get(n_low[-4:], ())):
                why = 'another file of the map ends with this name'
            else:
                d = editor_lock._read(a, n)
                if d is None:
                    continue
                try:
                    from PIL import Image
                    with Image.open(io.BytesIO(d)) as _img:
                        dim = _img.size
                    if not (_is_pow2(dim[0]) and _is_pow2(dim[1])):
                        why = 'the side (%dx%d) is not a power of 2' % dim
                    elif max(dim) > 512 and (w3i_version is None or w3i_version < 28):
                        why = 'the side (%dx%d) is above 512 in a map older than 1.31 (w3i %s)' % (dim[0], dim[1],
                                                                                                 w3i_version)
                    else:
                        new_ones, info = blp_from_image(d, sector_bytes)
                        if new_ones is None:
                            why = 'the BLP is not smaller once stored (the original %d B; paletted %s, JPEG %s)' % (
                                info['stored_before'], info['given_palette'], info.get('jpeg'))
                except Exception as e:
                    details['matrix'][n] = {
                        'action_code': 'not touched',
                        'why': 'Pillow does not read the .%s (%s)' % (t, str(e)[:60]),
                    }
                    log('[dds] %s: Pillow cannot read it (%s)' % (n, str(e)[:60]))
                    continue
            if why:
                details['matrix'][n] = {'action_code': 'retained', 'why': why}
                continue
        write_out.append((new_name, new_ones))
        to_delete.append(n)
        name_swaps.append(n)
        details['matrix'][n] = {
            'action_code': 'converted_file',
            'new': new_name,
            'bytes_before': len(d),
            'bytes_after': len(new_ones),
            'dim': dim,
        }
        if info is not None:
            details['matrix'][n].update(format=info['format'], stored_before=info['stored_before'],
                                        stored_after=info['stored_after'])
            g = stored_value.setdefault(t, [0, 0, 0, 0])
            g[0] += 1
            g[1] += info['stored_before']
            g[2] += info['stored_after']
            g[3] += info['format'] == 'paletted'
        log('[dds] %s -> %s (%d -> %d B)' % (n, new_name, len(d), len(new_ones)))
    details['stored_value'] = dict((t, {'converted': g[0], 'paletted_count': g[3], 'before': g[1], 'after_diag': g[2]})
                                   for t, g in stored_value.items())
    if not write_out:
        details['ok'] = True
        return details
    rx = _rx_repoint(name_swaps)
    to_delete_low = set(x.lower() for x in to_delete)
    rx_trocados = re.compile(rb'\.(?:' + b'|'.join(sorted(set(x[-3:].lower().encode() for x in name_swaps))) + rb')',
                             re.IGNORECASE)
    for n, d in cited_before:
        if n.lower() in to_delete_low or not rx_trocados.search(d):
            continue
        new = rx.sub(lambda m: m.group(0)[:-4] + (b'.BLP' if m.group(0)[-4:].isupper() else b'.blp'), d)
        if new != d:
            write_out.append((n, new))
            details['matrix'].setdefault(n, {})['action_code'] = 'retargeted'
    mpqadd.add_files(output, write_out, to_delete=to_delete, log=lambda *x: None)
    b = mpqread.Archive(output)
    bad_ones = []
    for name_new, data_bytes in write_out:
        if name_new.lower().endswith('.blp') and (b.read(name_new) or b'')[:4] not in (b'BLP1', b'BLP2'):
            bad_ones.append('%s: what was written is not a BLP' % name_new)
        elif name_new.lower().endswith('.blp'):
            try:
                blpread.read_bytes(b.read(name_new))
            except Exception as e:
                bad_ones.append('%s: the blpread cannot re-read it (%s)' % (name_new, str(e)[:50]))
    mentions = []
    for n in name_list:
        if n.lower() in to_delete_low:
            continue
        dd = b.read(n)
        if dd and rx_trocados.search(dd):
            mentions.append((n, dd))
    pend = []
    for del_name in to_delete:
        rxv = _rx_repoint([del_name])
        for n, dd in mentions:
            if rxv.search(dd):
                pend.append('%s em %s' % (del_name, n))
                break
    if pend:
        bad_ones.append('pending %s reference: %s' % ('.dds' if types == ('dds',) else 'swapped', pend[:5]))
    details['gate'] = (
        'ok (%d BLP, all re-read; no pending reference)' % len([1 for n, _ in write_out if n.lower().endswith('.blp')])
        if not bad_ones
        else 'FAILED: %s' % bad_ones
    )
    if bad_ones:
        raise SystemExit('ABORT (dds): %s' % bad_ones)
    details['replaced'] = len(to_delete)
    details['ok'] = True
    if types == ('dds',):
        log('DDS %s: %d .dds -> .blp in %s' % ('OK' if details['ok'] else 'FAILED', details['replaced'], output))
    else:
        log('BLP %s: %d image(s) -> .blp in %s' % ('OK' if details['ok'] else 'FAILED', details['replaced'], output))
    return details
