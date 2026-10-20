# Makes the textures that only models use smaller: half size, from their own mipmaps when they have them.

from PIL import Image

import blpread
import blpwrite



ICON_PREFIXES = ('btn', 'disbtn', 'pas', 'dispas', 'atc', 'disatc')
INTERFACE_FOLDERS = ('ui\\', 'replaceabletextures\\commandbuttons', 'replaceabletextures\\passivebuttons',
                     'replaceabletextures\\worldeditui', 'replaceabletextures\\cursor')
MIN_SIDE = 128
MIN_SIDES = (64, 128, 256)
FACTORS = (2,)


def is_interface(fname):
    low = fname.lower().replace('/', '\\')
    base = low.rsplit('\\', 1)[-1]
    return base.startswith(ICON_PREFIXES) or low.startswith(INTERFACE_FOLDERS) or \
        ('\\' not in low and low.startswith(('war3map', 'war3campaign')))


def reducible(a, name_list):
    import re
    import editor_lock
    import dds_to_blp
    rx = re.compile(rb'\.blp', re.IGNORECASE)
    blps = set(n.lower().replace('/', '\\') for n in name_list if n.lower().endswith('.blp'))
    by_model, by_other, ui_models = set(), set(), set()
    model_cites = {}
    rx_mdl = re.compile(rb'\.md[xl]', re.IGNORECASE)
    for n in name_list:
        low = n.lower()
        if (
            low.endswith(('.blp', '.mp3', '.wav', '.flac', '.ogg', '.tga', '.dds', '.png'))
            or low in dds_to_blp.LIST_FILES
        ):
            continue
        d = editor_lock._read(a, n)
        if not d:
            continue
        if rx.search(d):
            cited = dds_to_blp._cited_names(d, rx) & blps
            if low.endswith(('.mdx', '.mdl')):
                by_model |= cited
                model_cites[low.replace('/', '\\')] = cited
            else:
                by_other |= cited
        if low.endswith(('.w3i', '.fdf', '.toc')) and rx_mdl.search(d):
            for m in dds_to_blp._cited_names(d, rx_mdl):
                ui_models.add(m[:-4] + '.mdx')
    ui_textures = set()
    for m in ui_models:
        ui_textures |= model_cites.get(m, set())
    ok, keep = set(), {}
    for b in sorted(blps):
        if is_interface(b):
            keep[b] = 'the interface reads it (icon, interface folder or fixed name)'
        elif b in by_other:
            keep[b] = 'a file that is not a model cites it (object data, frame, script or loading screen)'
        elif b in ui_textures:
            keep[b] = 'a model of the interface uses it (loading screen or frame)'
        elif b not in by_model:
            keep[b] = 'no model of the map cites it'
        else:
            ok.add(b)
    return ok, keep


def _shifted_chain(data_bytes, info):
    import struct
    w, h = info['map_width'], info['map_height']
    sizes, offs = list(info['sizes']), list(info['offsets'])
    if not info['mips'] or not sizes[1] or offs[1] + sizes[1] > len(data_bytes) or max(w, h) < 2:
        return None
    nw, nh = max(1, w // 2), max(1, h // 2)
    level_list, sources = [], []
    for i in range(1, 16):
        if not sizes[i]:
            break
        if offs[i] + sizes[i] > len(data_bytes):
            return None
        level_list.append(data_bytes[offs[i]:offs[i] + sizes[i]])
        sources.append((offs[i], sizes[i]))
    if info['compression'] == 0:
        import io
        try:
            with Image.open(
                io.BytesIO(blpread._raw_components(data_bytes[160 : 160 + info['jpeg_header']] + level_list[0]))
            ) as im1:
                im1.load()
                if im1.size != (nw, nh):
                    return None
        except Exception:
            return None
    elif sizes[1] < nw * nh + (nw * nh * info['alpha_bits'] + 7) // 8:
        return None
    if info['compression'] == 0:
        head_line = data_bytes[160:160 + info['jpeg_header']]
        base = 160 + len(head_line)
        middle = struct.pack('<I', len(head_line)) + head_line
    else:
        base = 156 + 1024
        middle = data_bytes[156:156 + 1024]
    new_offs, new_sizes, pos, existing, block_body = [], [], base, {}, []
    for lv, source in zip(level_list, sources):
        if source not in existing:
            existing[source] = pos
            block_body.append(lv)
            pos += len(lv)
        new_offs.append(existing[source])
        new_sizes.append(len(lv))
    new_offs += [0] * (16 - len(new_offs))
    new_sizes += [0] * (16 - len(new_sizes))
    hdr = b'BLP1' + struct.pack('<IIIIII', info['compression'], info['alpha_bits'], nw, nh, info['type_name'], 1)
    hdr += struct.pack('<16I', *new_offs) + struct.pack('<16I', *new_sizes)
    return hdr + middle + b''.join(block_body)


def half_bytes(data_bytes, factor=2, min_side=MIN_SIDE):
    import zlib
    if factor not in FACTORS:
        raise ValueError('factor %r: valid %s' % (factor, FACTORS))
    try:
        info = blpread.header_bytes(data_bytes)
    except Exception as e:
        return None, {'why': 'the header does not read (%s)' % str(e)[:60]}
    w, h = info['map_width'], info['map_height']
    out = {'dim_before': (w, h)}
    if info['version_num'] != 1 or info['compression'] not in (0, 1):
        out['why'] = 'not a BLP1 JPEG or paletted texture (%s)' % info['format']
        return None, out
    if max(w, h) // factor < min_side:
        out['why'] = 'below %d px' % (min_side * factor)
        return None, out
    new_ones = _shifted_chain(data_bytes, info)
    out['how'] = 'mipmaps'
    if new_ones is None:
        out['how'] = 'rewritten'
        try:
            im, _i = blpread.read_bytes(data_bytes, 0, info)
            im = im.resize((max(1, w // factor), max(1, h // factor)), Image.LANCZOS)
            ab = 8 if info['alpha_bits'] else 0
            if info['compression'] == 0:
                _n, new_ones = blpwrite.blp_jpeg_bytes(
                    im,
                    100,
                    alpha_bits=ab,
                    mipmaps=bool(info['mips']),
                    extra=info['type_name'],
                    qtable=blpwrite.qtable_of_bytes(data_bytes),
                )
            else:
                new_ones = blpwrite.blp_palette_bytes(
                    im,
                    alpha_bits=ab,
                    mipmaps=bool(info['mips']),
                    extra=info['type_name'],
                    given_palette=data_bytes[156 : 156 + 1024],
                )
        except Exception as e:
            out['why'] = 'it does not decode (%s)' % str(e)[:60]
            return None, out
    if len(zlib.compress(new_ones, 9)) >= len(zlib.compress(data_bytes, 9)):
        out['why'] = 'not smaller'
        return None, out
    out['dim_after'] = (max(1, w // factor), max(1, h // factor))
    return new_ones, out
