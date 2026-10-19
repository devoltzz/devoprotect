# Makes MDX models smaller: repeated animation keys out, lossy only when asked; each one proved.
import math
import struct

import mdx_struct
import mdxcheck


TRANSLATION = ('KGTR', 'KCTR', 'KTTR', 'KTAT')
ROTATION = ('KGRT', 'KTAR')
SCALE = ('KGSC', 'KTAS')
OTHER = ('KGAO', 'KGAC', 'KMTA', 'KMTE', 'KFC3', 'KFCA', 'KFTC', 'KLAS', 'KLAE', 'KLAC', 'KLAI', 'KLBI', 'KLBC', 'KRAL',
         'KRCO', 'KRHA', 'KRHB', 'KCRL', 'KTAS')
DEFAULT_TOLERANCE = {'translation': 0.05, 'rotation': 0.002, 'scale': 0.002, 'other': 0.002}
MIN_GAIN = 64


def _class(tag):
    if tag in TRANSLATION:
        return 'translation'
    if tag in ROTATION:
        return 'rotation'
    if tag in SCALE:
        return 'scale'
    return 'other' if tag in OTHER else None


class _View(object):
    def __init__(self, data, t):
        self.t = t
        self.frames = t.frames
        stride, w = t.stride, t.words
        self.raw = []
        self.values = []
        self.tan = []
        for i in range(t.count):
            p = t.body + i * stride
            self.raw.append(data[p + 4:p + 4 + 4 * w])
            self.tan.append(data[p + 4 + 4 * w:p + stride])
            self.values.append(struct.unpack_from('<%d%s' % (w, 'f' if t.kind == 'f' else 'i'), data, p + 4))

    def record(self, data, i):
        p = self.t.body + i * self.t.stride
        return data[p:p + self.t.stride]


def _segments(frames, seqs, gseq):
    if gseq != -1:
        return [0] * len(frames)
    out = []
    for f in frames:
        seg = None
        for i, (a, b) in enumerate(seqs):
            if a <= f <= b:
                seg = i
                break
        out.append(seg)
    return out


def _zero(b):
    return not any(b)


def lossless_keep(v, seqs):
    t = v.t
    n = t.count
    stride = t.stride
    hermite = t.interp > 1
    seg = _segments(v.frames, seqs, t.gseq)
    keep = [True] * n
    last = 0
    for i in range(1, n):
        if v.frames[i] == v.frames[last] and v.raw[i] == v.raw[last] and v.tan[i] == v.tan[last]:
            keep[i] = False
        else:
            last = i
    idx = [i for i in range(n) if keep[i]]
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and seg[idx[j + 1]] is not None and seg[idx[j + 1]] == seg[idx[i]] and \
                v.raw[idx[j + 1]] == v.raw[idx[i]] and seg[idx[i]] is not None:
            j += 1
        if j - i >= 2:
            interior = idx[i + 1:j]
            ok = True
            if hermite:
                w = 4 * t.words
                ok = _zero(v.tan[idx[i]][w:]) and _zero(v.tan[idx[j]][:w]) and all(_zero(v.tan[k]) for k in interior)
            if ok:
                for k in interior:
                    keep[k] = False
        i = j + 1
    return keep


def _lerp(a, b, u):
    return tuple(x + (y - x) * u for x, y in zip(a, b))


def _slerp(a, b, u):
    dot = sum(x * y for x, y in zip(a, b))
    if dot < 0:
        b = tuple(-y for y in b)
        dot = -dot
    if dot > 0.9995:
        r = _lerp(a, b, u)
    else:
        th = math.acos(min(dot, 1.0))
        s = math.sin(th)
        wa, wb = math.sin((1 - u) * th) / s, math.sin(u * th) / s
        r = tuple(wa * x + wb * y for x, y in zip(a, b))
    n = math.sqrt(sum(x * x for x in r)) or 1.0
    return tuple(x / n for x in r)


def _error(cls, a, b):
    if a == b:
        return 0.0
    if cls == 'rotation':
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        dot = abs(sum(x * y for x, y in zip(a, b))) / (na * nb)
        return 2.0 * math.acos(min(dot, 1.0))
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def sample(frames, values, frame, interp, rotation=False):
    if frame <= frames[0]:
        return values[0]
    if frame >= frames[-1]:
        return values[-1]
    lo, hi = 0, len(frames) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if frames[mid] <= frame:
            lo = mid
        else:
            hi = mid
    if frames[lo] == frame:
        while lo + 1 < len(frames) and frames[lo + 1] == frame:
            lo += 1
        return values[lo]
    if interp == 0:
        return values[lo]
    u = (frame - frames[lo]) / float(frames[hi] - frames[lo])
    return (_slerp if rotation else _lerp)(values[lo], values[hi], u)


def rdp_keep(v, seqs, tol):
    t = v.t
    cls = _class(t.tag)
    keep = lossless_keep(v, seqs)
    idx = [i for i in range(t.count) if keep[i]]
    seg = _segments(v.frames, seqs, t.gseq)
    rot = cls == 'rotation'
    i = 0
    while i < len(idx):
        j = i
        while j + 1 < len(idx) and seg[idx[i]] is not None and seg[idx[j + 1]] == seg[idx[i]]:
            j += 1
        if j - i >= 2 and seg[idx[i]] is not None:
            stack = [(i, j)]
            while stack:
                a, b = stack.pop()
                if b - a < 2:
                    continue
                fa, fb = v.frames[idx[a]], v.frames[idx[b]]
                worst, at = -1.0, None
                for k in range(a + 1, b):
                    u = (v.frames[idx[k]] - fa) / float(fb - fa) if fb != fa else 0.0
                    est = (_slerp if rot else _lerp)(v.values[idx[a]], v.values[idx[b]], u)
                    e = _error(cls, v.values[idx[k]], est)
                    if e != e:
                        e = float('inf')
                    if e > worst:
                        worst, at = e, k
                if worst > tol:
                    stack.append((a, at))
                    stack.append((at, b))
                else:
                    for k in range(a + 1, b):
                        keep[idx[k]] = False
        i = j + 1
    return keep


def _new_track(data, v, keep):
    t = v.t
    head = data[t.start:t.start + (12 if t.event else 16)]
    head = head[:4] + struct.pack('<I', sum(keep)) + head[8:]
    body = b''.join(v.record(data, i) for i in range(t.count) if keep[i])
    return head + body


def _prove(old, new, kept, lossy, tol):
    a, b = mdx_struct.read(old), mdx_struct.read(new)
    if b.version != a.version or b.notes != a.notes:
        return False, 'the output reads differently', {}
    if len(a.tracks) != len(b.tracks) or len(a.nodes) != len(b.nodes) or len(a.geos) != len(b.geos) or \
            len(a.mats) != len(b.mats) or len(a.seqs) != len(b.seqs) or len(a.texs) != len(b.texs):
        return False, 'the structure changed', {}
    if [(n['kind'], n['name'], n['id'], n['parent']) for n in a.nodes] != \
            [(n['kind'], n['name'], n['id'], n['parent']) for n in b.nodes]:
        return False, 'the nodes changed', {}
    for ga, gb in zip(a.geos, b.geos):
        if old[ga['off'] + 4:ga['mats_end']] != new[gb['off'] + 4:gb['mats_end']]:
            return False, 'a geoset changed', {}
    seqs = [(s['start'], s['end']) for s in a.seqs]
    worst = {}
    for k, (ta, tb) in enumerate(zip(a.tracks, b.tracks)):
        if (ta.tag, ta.owner, ta.interp, ta.gseq, ta.event) != (tb.tag, tb.owner, tb.interp, tb.gseq, tb.event):
            return False, 'a track changed identity', {}
        if k not in kept:
            if old[ta.start:ta.end] != new[tb.start:tb.end]:
                return False, 'a track that should not change did', {}
            continue
        keep = kept[k]
        va, vb = _View(old, ta), _View(new, tb)
        idx = [i for i in range(ta.count) if keep[i]]
        if len(idx) != tb.count or any(va.record(old, i) != vb.record(new, j) for j, i in enumerate(idx)):
            return False, 'the kept keys are not a subset of the original', {}
        if ta.gseq == -1:
            seg = _segments(va.frames, seqs, -1)
            for s in set(x for x in seg if x is not None):
                ks = [i for i in range(ta.count) if seg[i] == s]
                kept_frames = set(va.frames[i] for i in ks if keep[i])
                if va.frames[ks[0]] not in kept_frames or va.frames[ks[-1]] not in kept_frames:
                    return False, 'the first or last key of a sequence was dropped', {}
        if tb.count == ta.count:
            continue
        cls = _class(ta.tag)
        rot = cls == 'rotation'
        probes = set(va.frames)
        fr = sorted(probes)
        probes |= set((x + y) // 2 for x, y in zip(fr, fr[1:]))
        err = 0.0
        for f in probes:
            x = sample(va.frames, va.values, f, ta.interp, rot)
            y = sample(vb.frames, vb.values, f, tb.interp, rot)
            err = max(err, _error(cls or 'other', x, y) if ta.kind == 'f' else (0.0 if x == y else 1.0))
        worst[cls or 'other'] = max(worst.get(cls or 'other', 0.0), err)
        limit = tol[cls] if lossy and cls in tol else 1e-6 if cls == 'rotation' else 0.0
        if err > limit + (1e-6 if lossy else 0):
            return False, '%s %s moved by %.6g, above %.6g' % (ta.owner, ta.tag, err, limit), worst
    return True, '', worst


def optimize(data, lossy=False, tolerance=1.0):
    data = bytes(data)
    m = mdx_struct.read(data)
    seqs = [(s['start'], s['end']) for s in m.seqs]
    tol = dict((k, v * float(tolerance)) for k, v in DEFAULT_TOLERANCE.items())
    report = {
        'keys_before': 0,
        'keys_after': 0,
        'tracks_changed': 0,
        'bytes_before': len(data),
        'bytes_after': len(data),
    }
    if m.notes:
        report['error'] = 'the model does not read cleanly (%s)' % m.notes[0]
        return None, report
    edits, kept = [], {}
    for k, t in enumerate(m.tracks):
        report['keys_before'] += t.count
        report['keys_after'] += t.count
        if t.event or t.count < 3 or t.kind != 'f' and t.interp > 1:
            continue
        if any(t.frames[i] < t.frames[i - 1] for i in range(1, t.count)):
            continue
        v = _View(data, t)
        cls = _class(t.tag)
        if lossy and cls and t.interp == 1 and t.kind == 'f':
            keep = rdp_keep(v, seqs, tol[cls])
        else:
            keep = lossless_keep(v, seqs)
        dropped = t.count - sum(keep)
        if not dropped:
            continue
        edits.append((t.start, t.end, _new_track(data, v, keep)))
        kept[k] = keep
        report['keys_after'] -= dropped
        report['tracks_changed'] += 1
    if not edits:
        return None, report
    new = mdx_struct.edit(data, m, edits)
    report['bytes_after'] = len(new)
    if len(data) - len(new) < max(MIN_GAIN, len(data) // 100):
        return None, report
    try:
        ok, why, worst = _prove(data, new, kept, lossy, tol)
    except (ValueError, struct.error, IndexError) as e:
        ok, why, worst = False, 'the output does not read back (%s)' % e, {}
    chunks, err = mdxcheck.walk(new)
    if ok and err:
        ok, why = False, 'the output chunk walk does not close (%s)' % err
    if lossy:
        report['max_error'] = worst
    if not ok:
        report['error'] = why
        report['bytes_after'] = len(data)
        return None, report
    return new, report

