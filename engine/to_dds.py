# Converts the BLP, TGA and PNG textures of a map to DDS when they get smaller, and points every reference at the new file.
import io
import os
import re
import struct



TYPES = ('blp', 'tga', 'png')
PSNR_MIN = 33.0
W3I_MIN = 31
QUALITIES = {'high': (36.0, 0.0), 'normal': (33.0, 1.0), 'small': (30.0, 2.0)}
DEFAULT_QUALITY = 'normal'


def _rx(t):
    return re.compile(rb'\.' + t.encode() + rb'(?![0-9A-Za-z])', re.IGNORECASE)


def _is_pow2(n):
    return n >= 4 and n & (n - 1) == 0


def _image(data, kind):
    from PIL import Image
    if kind == 'blp':
        import blpread
        return blpread.read_bytes(data)[0].convert('RGBA')
    im = Image.open(io.BytesIO(data))
    im.load()
    return im.convert('RGBA')


def candidate(data, kind, sector=None, psnr_min=PSNR_MIN, blp_best=False, rdo=0.0):
    import bcn_encode
    import dds_to_blp
    im = _image(data, kind)
    info = {'dim': im.size}
    if not (_is_pow2(im.size[0]) and _is_pow2(im.size[1])):
        info['why'] = 'the side (%dx%d) is not a power of 2 of at least 4' % im.size
        return None, info
    before = data
    if blp_best and kind == 'blp':
        import blp_huffman
        try:
            best, _why = blp_huffman.otimiza_blp(data, proof=False)
        except Exception:
            best = None
        before = best or data
    info['stored_before'] = dds_to_blp._stored_size(before, sector)
    for force in ((rdo, 0.0) if rdo > 0 else (0.0,)):
        dds, fmt = bcn_encode.encode(im, rdo=force)
        info.update(fmt=fmt, rdo=force, stored_after=dds_to_blp._stored_size(dds, sector))
        if info['stored_after'] >= info['stored_before']:
            info['why'] = 'the DDS (%d B stored) is not smaller than the %s (%d B)' % (
                info['stored_after'], kind.upper(), info['stored_before'])
            return None, info
        back = bcn_encode.decode(dds)
        info['psnr'] = round(bcn_encode.psnr(im, back), 2)
        if back.size == im.size and info['psnr'] >= psnr_min:
            info.pop('why', None)
            return dds, info
        info['why'] = 'the DDS is %.1f dB from the original, under %.1f' % (info['psnr'], psnr_min)
    return None, info


def _refs(data, rx_ext, swapped):
    import dds_to_blp as D
    out = []
    for m in rx_ext.finditer(data):
        end = m.end()
        if end < len(data) and (48 <= data[end] <= 57 or 65 <= data[end] <= 90 or 97 <= data[end] <= 122):
            continue
        begin, lim = m.start(), max(0, end - 260)
        while begin > lim and data[begin - 1] >= 0x20 and data[begin - 1] not in D._NAME_END:
            begin -= 1
        parts = data[begin:end].decode('utf-8', 'surrogateescape').replace('\\\\', '\\').replace('/', '\\') \
            .lower().split('\\')
        if any('\\'.join(parts[k:]) in swapped for k in range(len(parts))):
            out.append(m.start())
    return out


def convert(entry, output, types=TYPES, sector_bytes=None, psnr_min=PSNR_MIN, blp_best=False, log=print, rdo=0.0):
    import editor_lock
    import dds_to_blp as D
    import disabled_icons
    import mpqadd
    import mpqread
    import shutil
    types = tuple(t for t in TYPES if t in set(types))
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if entry == output:
        raise SystemExit('the output must be another file (the input never changes)')
    a = mpqread.Archive(entry)
    names, low = [], set()
    for n in editor_lock.map_names(a):
        if n.lower() not in low:
            low.add(n.lower())
            names.append(n)

    def kind_of(n):
        ext = n.lower()[-4:]
        return ext[1:] if ext[:1] == '.' and ext[1:] in types else None
    targets = [n for n in names if kind_of(n)]
    details = {'entry': entry, 'output': output, 'types': list(types), 'matrix': {}, 'replaced': 0, 'stored_value': {},
               'ok': False}
    for t in types:
        details[t] = len([n for n in targets if kind_of(n) == t])
    shutil.copyfile(entry, output)
    w3i = editor_lock._read(a, 'war3map.w3i')
    w3i_v = struct.unpack_from('<i', w3i, 0)[0] if w3i and len(w3i) >= 4 else None
    if not targets or w3i_v is None or w3i_v < W3I_MIN:
        if targets:
            details['why'] = 'the map is for a game before 1.32 (w3i %s), which reads no DDS' % w3i_v
            log('[to_dds] %s' % details['why'])
        details['ok'] = True
        return details
    rx_any = re.compile(rb'\.(?:' + b'|'.join(t.encode() for t in types) + rb')', re.IGNORECASE)
    targets_low = set(n.lower().replace('/', '\\') for n in targets)
    citing = []
    for n in names:
        d = editor_lock._read(a, n)
        if d and rx_any.search(d):
            citing.append((n, d))
    cited = {}
    for t in types:
        c = set()
        for n, d in citing:
            if n.lower().replace('/', '\\') not in targets_low and n.lower() not in D.LIST_FILES and _rx(t).search(d):
                c |= D._cited_names(d, _rx(t))
        cited[t] = c
    lua_bytes = editor_lock._read(a, 'war3map.lua')
    script = lua_bytes if lua_bytes else editor_lock._script(a)[1]
    built = {}
    for t in types:
        r = D.built_prefixes(script, t) if script else None
        if r is not None:
            built[t] = r
    by_ext = {}
    for x in low:
        x = x.replace('/', '\\')
        by_ext.setdefault(x[-4:], []).append(x)
    pairs = {}
    for icon in disabled_icons.icons(a, names):
        i_low = icon.replace('/', '\\').lower()
        if i_low in targets_low:
            pairs[i_low] = disabled_icons.disabled_path(icon).replace('/', '\\').lower()
    disabled_of = dict((v, k) for k, v in pairs.items())
    plan = {}
    for n in targets:
        t = kind_of(n)
        n_low = n.lower().replace('/', '\\')
        new_name = n[:-4] + ('.DDS' if n[-4:].isupper() else '.dds')
        why = None
        if '\\' not in n_low and n_low.startswith(('war3map', 'war3campaign')):
            why = 'the game reads this fixed name'
        elif built.get(t) is False:
            why = 'the script builds .%s names while the game runs' % t
        elif t in built and D._starts_with(n_low, built[t]) is not None:
            why = 'the script builds names that start like this one (%s)' % D._starts_with(n_low, built[t])
        elif n_low not in cited.get(t, ()) and disabled_of.get(n_low) not in cited.get(t, ()):
            why = 'no file of the map cites it (the game may read it by name)'
        elif new_name.lower() in low:
            why = '%s already exists in the map' % new_name
        elif any(x != n_low and x.endswith('\\' + n_low) for x in by_ext.get(n_low[-4:], ())):
            why = 'another file of the map ends with this name'
        elif n_low in pairs and pairs[n_low] not in targets_low:
            why = 'its disabled art (%s) is not in the map: the game would look for it as .dds' % pairs[n_low]
        if why:
            details['matrix'][n] = {'action_code': 'retained', 'why': why}
            continue
        d = editor_lock._read(a, n)
        if not d:
            continue
        try:
            dds, info = candidate(d, t, sector_bytes, psnr_min, blp_best, rdo)
        except Exception as e:
            details['matrix'][n] = {'action_code': 'not touched', 'why': 'the image does not read (%s)' % str(e)[:60]}
            continue
        if dds is None:
            details['matrix'][n] = {'action_code': 'retained', 'why': info['why']}
            continue
        plan[n_low] = (n, t, new_name, d, dds, info)
    for i_low, dis in pairs.items():
        if (i_low in plan) != (dis in plan):
            for x in (i_low, dis):
                if x in plan:
                    details['matrix'][plan[x][0]] = {'action_code': 'retained',
                                                     'why': 'its icon pair (%s) stays, so it stays too' % (
                                                     dis if x == i_low else i_low)}
                    del plan[x]
    write, delete, swapped, dims = [], [], [], {}
    for n, t, new_name, d, dds, info in plan.values():
        write.append((new_name, dds))
        delete.append(n)
        swapped.append(n)
        dims[new_name.lower()] = info['dim']
        details['matrix'][n] = {
            'action_code': 'converted_file',
            'new': new_name,
            'bytes_before': len(d),
            'bytes_after': len(dds),
            'dim': info['dim'],
            'format': info['fmt'],
            'psnr': info['psnr'],
            'rdo': info['rdo'],
            'stored_before': info['stored_before'],
            'stored_after': info['stored_after'],
        }
        g = details['stored_value'].setdefault(t, {'converted': 0, 'before': 0, 'after_diag': 0})
        g['converted'] += 1
        g['before'] += info['stored_before']
        g['after_diag'] += info['stored_after']
    if not write:
        details['ok'] = True
        return details
    sw_low = set(x.lower().replace('/', '\\') for x in swapped)
    gone = set(x.lower() for x in delete)
    rx_sw = re.compile(rb'\.(?:' + b'|'.join(sorted(set(x[-3:].lower().encode() for x in swapped))) + rb')',
                       re.IGNORECASE)
    for n, d in citing:
        if n.lower() in gone:
            continue
        pos = _refs(d, rx_sw, sw_low)
        if pos:
            new = bytearray(d)
            for p in pos:
                new[p:p + 4] = b'.DDS' if d[p + 1:p + 4].isupper() else b'.dds'
            write.append((n, bytes(new)))
            details['matrix'].setdefault(n, {})['action_code'] = 'retargeted'
    mpqadd.add_files(output, write, to_delete=delete, log=lambda *x: None)
    import bcn_encode
    b = mpqread.Archive(output)
    bad = []
    for name, data in write:
        if not name.lower().endswith('.dds'):
            continue
        got = b.read(name) or b''
        if got != data:
            bad.append('%s: not written as encoded' % name)
            continue
        try:
            im = bcn_encode.decode(got)
            if im.size != tuple(dims[name.lower()]):
                bad.append('%s: reads back with another size' % name)
        except Exception as e:
            bad.append('%s: does not read back (%s)' % (name, str(e)[:50]))
    left, forms = [], set()
    for x in sw_low:
        if '\\' in x:
            for f in (x, x.replace('\\', '/'), x.replace('\\', '\\\\')):
                forms.add(f.encode('utf-8', 'surrogateescape'))
    for n in names:
        if n.lower() in gone:
            continue
        dd = editor_lock._read(b, n)
        if dd and (_refs(dd, rx_sw, sw_low) or any(f in dd.lower() for f in forms)):
            left.append(n)
    if left:
        bad.append('a swapped name is still cited in %s' % left[:5])
    details['gate'] = 'ok (%d DDS, all read back; no reference left)' % len(delete) if not bad else 'FAILED: %s' % bad
    if bad:
        raise SystemExit('ABORTS (to_dds): %s' % bad)
    details['replaced'] = len(delete)
    details['ok'] = True
    log('DDS OK: %d texture(s) -> .dds in %s' % (details['replaced'], output))
    return details
