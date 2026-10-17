# Reads and writes war3campaign.w3f, the info of a campaign: its name and its maps.
import struct



FILE = 'war3campaign.w3f'
class _Reader(object):
    def __init__(self, data):
        self.d, self.p = data, 0

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.p)[0]
        self.p += 4
        return v

    def raw(self, n):
        if self.p + n > len(self.d):
            raise ValueError('the file ends inside a field')
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def s(self):
        e = self.d.index(b'\0', self.p)
        v = self.d[self.p:e]
        self.p = e + 1
        return v


def parse(data):
    r = _Reader(bytes(data))
    try:
        m = {'version': r.i32()}
        if m['version'] not in (1, 2, 3):
            raise ValueError('war3campaign.w3f version %d' % m['version'])
        m['campaign_version'], m['editor_version'] = r.i32(), r.i32()
        m['name'], m['difficulty'], m['author'], m['description'] = r.s(), r.s(), r.s(), r.s()
        m['flags'], m['background_number'] = r.i32(), r.i32()
        m['background_path'], m['minimap_path'] = r.s(), r.s()
        m['ambient_sound_number'], m['ambient_sound_path'] = r.i32(), r.s()
        m['fog'] = [r.i32(), r.f32(), r.f32(), r.f32(), r.raw(4)]
        m['race'] = r.i32()
        if m['version'] >= 3:
            m['fog_v3'] = [r.f32(), r.f32(), r.f32(), r.f32(), r.f32(), r.i32()]
        if m['version'] >= 2:
            m['background_version'] = r.i32()
        m['buttons'] = []
        for _ in range(_count(r)):
            m['buttons'].append({'visible': r.i32(), 'chapter': r.s(), 'title': r.s(), 'map': r.s()})
        m['maps'] = []
        for _ in range(_count(r)):
            m['maps'].append({'unk': r.s(), 'map': r.s()})
    except (struct.error, IndexError) as e:
        raise ValueError('war3campaign.w3f does not read: %s' % e)
    if r.p != len(r.d):
        raise ValueError('war3campaign.w3f: %d bytes after the last map' % (len(r.d) - r.p))
    return m


def _count(r):
    n = r.i32()
    if not 0 <= n <= 1000:
        raise ValueError('implausible count %d' % n)
    return n

