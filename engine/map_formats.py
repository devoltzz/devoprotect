# Names the files a map is made of, and reads and writes the placement files byte for byte.
import struct



LOCALES = ('deDE', 'enUS', 'esES', 'esMX', 'frFR', 'itIT', 'jaJP', 'koKR', 'plPL', 'ptBR', 'ruRU', 'zhCN', 'zhTW')
LOCALE_DIR = '_Locales\\'
LOCALE_FILES = ('war3map.wts', 'war3map.w3i', 'war3mapSkin.txt', 'war3mapMisc.txt', 'war3mapMap.blp',
                'war3mapPreview.tga', 'conversation.json')
_CASED = dict((n.lower(), n) for n in (
    'war3map.j', 'war3map.lua', 'Scripts\\war3map.j', 'war3map.w3i', 'war3map.wts', 'war3map.wtg', 'war3map.wct',
    'war3map.w3e', 'war3map.wpm', 'war3map.shd', 'war3map.mmp', 'war3map.doo', 'war3mapUnits.doo', 'war3map.w3r',
    'war3map.w3c', 'war3map.w3s', 'war3map.imp', 'war3map.w3u', 'war3map.w3t', 'war3map.w3a', 'war3map.w3b',
    'war3map.w3d', 'war3map.w3h', 'war3map.w3q', 'war3mapMisc.txt', 'war3mapSkin.txt', 'war3mapExtra.txt',
    'war3mapMap.blp', 'war3mapPreview.tga', 'war3mapPath.tga', 'war3mapSkin.w3u', 'war3mapSkin.w3t',
    'war3mapSkin.w3a', 'war3mapSkin.w3b', 'war3mapSkin.w3d', 'war3mapSkin.w3h', 'war3mapSkin.w3q',
    'conversation.json', 'war3map.w3l', 'war3mapPostProcessing.txt', 'war3map.w3grp', 'war3map.soundasset',
    '(listfile)', '(attributes)', '(signature)'))


def standard_names(locales=True):
    out = list(_CASED.values())
    if locales:
        out += ['%s%s.w3mod\\%s' % (LOCALE_DIR, loc, n) for loc in LOCALES for n in LOCALE_FILES]
    return out


class Unreadable(ValueError):
    pass


class Table(object):
    def __init__(self, kind, head, records, tail, count_at, fields, **info):
        self.kind = kind
        self.head = bytes(head)
        self.records = [bytearray(r) for r in records]
        self.tail = bytes(tail)
        self.count_at = count_at
        self.fields = fields
        self.info = info

    def __len__(self):
        return len(self.records)

    def get(self, i, field):
        off, fmt = self.fields[field]
        v = struct.unpack_from(fmt, self.records[i], off)
        return v[0] if len(v) == 1 else v

    def set(self, i, field, value):
        off, fmt = self.fields[field]
        struct.pack_into(fmt, self.records[i], off, *(value if isinstance(value, (tuple, list)) else (value,)))

    def remove(self, keep):
        old = self.records
        kept = [r for i, r in enumerate(old) if keep(self, i)]
        self.records = kept
        return len(old) - len(kept)

    def write(self):
        head = bytearray(self.head)
        if self.count_at is not None:
            struct.pack_into('<I', head, self.count_at, len(self.records))
        return bytes(head) + b''.join(bytes(r) for r in self.records) + self.tail


PLACED = {'id': (0, '4s'), 'variation': (4, '<i'), 'x': (8, '<f'), 'y': (12, '<f'), 'z': (16, '<f'),
          'angle': (20, '<f'), 'scale': (24, '<3f')}


def read_doo(data):
    import doodads
    try:
        d = doodads.read_data(data)
    except (doodads.FormatError, struct.error) as e:
        raise Unreadable(str(e))
    if not d.get('on_close'):
        raise Unreadable('war3map.doo does not close')
    end = d['regs'][-1]['begin'] + d['regs'][-1]['sz'] if d['regs'] else 16
    if data[end:] != d['tail']:
        raise Unreadable('war3map.doo: the tail does not follow the last record')
    return Table('doo', data[:16], [data[r['begin']:r['begin'] + r['sz']] for r in d['regs']], d['tail'], 12, PLACED,
                 version=d['version_num'], subversion=d['subversion'], skin=d['skin'])


def read_units_doo(data):
    import inflated_counts
    try:
        d = inflated_counts.load_units_doo(data)
    except Exception as e:
        raise Unreadable(str(e))
    if not d.get('on_close') or d['declared'] != len(d['regs']):
        raise Unreadable('war3mapUnits.doo does not close')
    recs, p = [], 16
    for r in d['regs']:
        recs.append(data[p:p + r['sz']])
        p += r['sz']
    return Table('units_doo', data[:16], recs, data[p:], 12, PLACED, layout=d.get('layout'))


def roundtrip_with(reader, data):
    if reader is None:
        return None
    try:
        t = reader(data)
    except Unreadable:
        return 'unreadable'
    if t is None:
        return None
    return 'same' if t.write() == data else 'differs'
