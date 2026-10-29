# Diagnoses a map, removes its protection and prepares it for the World Editor.
import contextlib
import io
import re
import sys

import mpqread


class _Record(io.TextIOBase):
    def __init__(self):
        super().__init__()
        self.pieces = []

    def write(self, s):
        self.pieces.append(s)
        return len(s)

    def reconfigure(self, **_k):
        pass

    def body_text(self):
        return ''.join(self.pieces)


@contextlib.contextmanager
def quiet(reg=None):
    reg = _Record() if reg is None else reg
    old_streams = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = reg
    try:
        yield reg
    finally:
        sys.stdout, sys.stderr = old_streams


def _read(a, fname):
    try:
        r = a.find_locale(fname) if a.find(fname) else None
        return a.read(fname, bi=r[1]) if r else None
    except Exception:
        return None


def _open(file_path):
    with quiet():
        return mpqread.Archive(file_path)


def language_from_w3i(b):
    if not b:
        return None
    try:
        import w3i
        m = w3i.parse(b)
    except Exception:
        return None
    return m.get('script_language')


J2B_FILE = 'war3map.bin'
RX_J2B = re.compile(rb'"war3map\.bin"')


def script_j2b(a, j):
    if not RX_J2B.search(j):
        return False
    r = a.find(J2B_FILE)
    if not r:
        return False
    try:
        v, begin_pos = a.validate_light(r[1], J2B_FILE)
    except Exception:
        return False
    return v == 'ok' and begin_pos[:4] in (b'2SAJ', b'SSAJ')

