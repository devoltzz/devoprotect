# Makes the disabled art (DISBTN) of the imported icons, which the game draws green without it.
import os
import struct

import name_recovery


DISABLED_FOLDER = 'ReplaceableTextures\\CommandButtonsDisabled\\'
OBJECT_FIELDS = {'w3u': (b'uico',), 'w3t': (b'iico',), 'w3a': (b'aart', b'arar', b'auar'), 'w3q': (b'gar1',)}
LEVELLED = ('w3a', 'w3d', 'w3q')
OBJECT_FILES = tuple('%s.%s' % (base, ext) for base in ('war3map', 'war3mapSkin') for ext in OBJECT_FIELDS)
TXT_KEYS = ('art', 'researchart', 'unart')
def object_strings(data, levelled):
    ver = struct.unpack_from('<I', data, 0)[0]
    if ver not in (1, 2, 3):
        raise ValueError('object file version %d' % ver)
    p = 4
    for _table in range(2):
        n = struct.unpack_from('<I', data, p)[0]
        p += 4
        for _ in range(n):
            old, new = data[p:p + 4].decode('latin-1'), data[p + 4:p + 8].decode('latin-1')
            ident = new if new.strip('\0') else old
            p += 8
            sets = 1
            if ver >= 3:
                sets = struct.unpack_from('<I', data, p)[0]
                p += 4
            for _s in range(sets):
                if ver >= 3:
                    p += 4
                nm = struct.unpack_from('<I', data, p)[0]
                p += 4
                for _m in range(nm):
                    field = data[p:p + 4]
                    vt = struct.unpack_from('<I', data, p + 4)[0]
                    p += 16 if levelled else 8
                    if vt == 3:
                        end = data.index(b'\0', p)
                        yield ident, field, data[p:end]
                        p = end + 1
                    elif vt in (0, 1, 2):
                        p += 4
                    else:
                        raise ValueError('value type %d in field %r of %r' % (vt, field, ident))
                    p += 4
    if p > len(data) or data[p:].strip(b'\0'):
        raise ValueError('the file does not close (%d of %d bytes)' % (p, len(data)))


def txt_strings(data):
    section = ''
    for line in data.decode('utf-8', 'surrogateescape').splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        elif '=' in line and not line.startswith('//'):
            key, value = line.split('=', 1)
            if key.strip().lower() in TXT_KEYS:
                yield section, key.strip(), value.strip()


def _paths(value):
    if isinstance(value, bytes):
        value = value.decode('utf-8', 'surrogateescape')
    out = []
    for part in value.split(','):
        part = part.strip().strip('"').strip().replace('/', '\\')
        if not part or part.upper().startswith('TRIGSTR_'):
            continue
        if not os.path.splitext(part)[1]:
            part += '.blp'
        out.append(part)
    return out


def disabled_path(icon):
    return DISABLED_FOLDER + 'DIS' + icon.replace('/', '\\').rsplit('\\', 1)[-1]


def icons(a, names):
    out = {}

    def add(value, where):
        for icon in _paths(value):
            out.setdefault(icon, []).append(where)

    for name in OBJECT_FILES:
        data = name_recovery._read(a, name)
        if not data:
            continue
        ext = name.rsplit('.', 1)[1]
        try:
            for ident, field, value in object_strings(data, ext in LEVELLED):
                if field in OBJECT_FIELDS[ext]:
                    add(value, '%s %s %s' % (name, ident, field.decode('latin-1')))
        except (ValueError, struct.error):
            continue
    tables = sorted(n for n in names if n.lower().endswith('.txt') and
                    (n.lower().startswith('units\\') or n.lower() == 'war3mapskin.txt'))
    for name in tables:
        data = name_recovery._read(a, name)
        if data:
            for section, key, value in txt_strings(data):
                add(value, '%s [%s] %s' % (name, section, key))
    return out

