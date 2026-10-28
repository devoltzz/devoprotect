# Diagnoses a map, removes its protection and prepares it for the World Editor.


def _read(a, fname):
    try:
        r = a.find_locale(fname) if a.find(fname) else None
        return a.read(fname, bi=r[1]) if r else None
    except Exception:
        return None

