# The builds of Warcraft III and the World Editor number each one writes.
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))

NAME = 'game_builds.json'
_TABLE = {}


def _roots():
    try:
        import wc3_versions
        return wc3_versions._ref_roots()
    except Exception:
        return [os.path.normpath(os.path.join(HERE, '..', 'ref'))]


def patch_label(patch):
    parts = str(patch or '').lstrip('vV').split('_')
    return '.'.join(parts)


def builds():
    if 'b' not in _TABLE:
        rows = []
        for root in _roots():
            p = os.path.join(root, NAME)
            if os.path.isfile(p):
                with open(p, encoding='utf-8') as f:
                    data = json.load(f)
                cols = data.get('columns') or ['expansion', 'date', 'patch', 'version', 'editor']
                for r in data.get('builds') or []:
                    d = dict(zip(cols, r))
                    d['label'] = patch_label(d.get('patch'))
                    rows.append(d)
                break
        _TABLE['b'] = rows
    return list(_TABLE['b'])


def by_editor(editor):
    try:
        n = int(editor)
    except (TypeError, ValueError):
        return []
    return [b for b in builds() if b['editor'] == n]

