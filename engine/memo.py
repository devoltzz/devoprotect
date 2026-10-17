# A disk cache: the file names of a map and the parsed tables, kept while the files do not change.
import os


def folder():
    p = os.environ.get('DEVOPROTECT_CACHE')
    if not p:
        return None
    try:
        os.makedirs(p, exist_ok=True)
    except OSError:
        return None
    return p

