# Reads the cells of an SLK table and removes columns from it.


def slk_fields(ln):
    out = []
    buf = None
    for p in ln.split(';')[1:]:
        if buf is not None:
            buf += ';' + p
            if buf.count('"') % 2 == 0:
                out.append(buf)
                buf = None
        elif p.startswith('K"') and p.count('"') % 2 == 1:
            buf = p
        else:
            out.append(p)
    if buf is not None:
        out.append(buf)
    return out

