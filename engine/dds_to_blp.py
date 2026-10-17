# Converts the DDS textures of a map to BLP and points every reference at the new file.
import io
import os
import re
import tempfile




def _rx_repoint(name_list):
    forms = set()
    for n in name_list:
        b = n.replace('/', '\\')
        forms.add(b)
        forms.add(b.replace('\\', '/'))
        forms.add(b.replace('\\', '\\\\'))
    height = b'|'.join(re.escape(f.encode('utf-8', 'surrogateescape')) for f in sorted(forms, key=len, reverse=True))
    return re.compile(rb'(?<![0-9A-Za-z._\-\x80-\xff])(?:' + height + rb')(?![0-9A-Za-z])', re.IGNORECASE)


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


def converte(entry, output, only_smaller=False, log=print):
    import editor_lock
    import blpread
    import mpqadd
    import mpqread
    import shutil
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if entry == output:
        raise SystemExit('the output must be another file (the input never changes)')
    a = mpqread.Archive(entry)
    name_list, names_low = [], set()
    for n in editor_lock.map_names(a):
        if n.lower() not in names_low:
            names_low.add(n.lower())
            name_list.append(n)
    dds = [n for n in name_list if n.lower().endswith('.dds')]
    details = {'entry': entry, 'output': output, 'dds': len(dds), 'matrix': {}, 'replaced': 0, 'ok': False}
    shutil.copyfile(entry, output)
    if not dds:
        details['ok'] = True
        log('[dds] no .dds in the map')
        return details
    name_swaps = []
    write_out, to_delete = [], []
    for n in dds:
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
        new_name = n[:-4] + ('.BLP' if n[-4:].isupper() else '.blp')
        if new_name.lower() in names_low and new_name.lower() != n.lower():
            details['matrix'][n] = {'action_code': 'retained', 'why': '%s already exists in the map' % new_name}
            log('[dds] %s kept: %s already exists' % (n, new_name))
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
        log('[dds] %s -> %s (%d -> %d B)' % (n, new_name, len(d), len(new_ones)))
    if not write_out:
        details['ok'] = True
        return details
    rx = _rx_repoint(name_swaps)
    to_delete_low = set(x.lower() for x in to_delete)
    for n in name_list:
        if n.lower() in to_delete_low:
            continue
        d = editor_lock._read(a, n)
        if d is None:
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
    pend = []
    for del_name in to_delete:
        rxv = _rx_repoint([del_name])
        for n in name_list:
            if n.lower() in to_delete_low:
                continue
            dd = b.read(n)
            if dd and rxv.search(dd):
                pend.append('%s em %s' % (del_name, n))
                break
    if pend:
        bad_ones.append('pending .dds reference: %s' % pend[:5])
    details['gate'] = (
        'ok (%d BLP, all re-read; no pending reference)' % len([1 for n, _ in write_out if n.lower().endswith('.blp')])
        if not bad_ones
        else 'FAILED: %s' % bad_ones
    )
    if bad_ones:
        raise SystemExit('ABORT (dds): %s' % bad_ones)
    details['replaced'] = len(to_delete)
    details['ok'] = True
    log('DDS %s: %d .dds -> .blp in %s' % ('OK' if details['ok'] else 'FAILED', details['replaced'], output))
    return details
