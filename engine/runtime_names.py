# The file names a JASS script builds while it runs (the interpreter runs its start).
import re
import sys
import time

import jass_ast


FILE_ARGUMENTS = {
    'AddSpecialEffect': [(0, 'model')], 'AddSpecialEffectLoc': [(0, 'model')], 'AddSpecialEffectTarget': [(0, 'model')],
    'AddSpellEffectTarget': [(0, 'model')], 'AddSpecialEffectLocBJ': [(1, 'model')],
    'AddSpecialEffectTargetUnitBJ': [(2, 'model')], 'SetSkyModel': [(0, 'model')],
    'SetIntroShotModel': [(0, 'model')], 'PlayModelCinematic': [(0, 'model')],
    'BlzPreloadModelCinematicGame': [(0, 'model')], 'BlzPlayModelCinematicGameAtPosition': [(0, 'model')],
    'CreateTrackable': [(0, 'model')], 'SetCinematicCamera': [(0, 'model')],
    'SetCinematicCameraForPlayer': [(1, 'model')], 'BlzFrameSetModel': [(1, 'model')],
    'DzFrameSetModel': [(1, 'model')], 'SetDayNightModels': [(0, 'model'), (1, 'model')],
    'SetPortraitLight': [(0, 'model')], 'CreateMinimapIcon': [(5, 'model')], 'CreateMinimapIconAtLoc': [(4, 'model')],
    'CreateMinimapIconOnUnit': [(4, 'model')], 'CreateMinimapIconBJ': [(5, 'model')],
    'CreateMinimapIconAtLocBJ': [(4, 'model')], 'CreateMinimapIconOnUnitBJ': [(4, 'model')],
    'CreateSound': [(0, 'sound')], 'CreateSoundFilenameWithLabel': [(0, 'sound')],
    'PlayThematicMusic': [(0, 'sound')], 'PlayThematicMusicEx': [(0, 'sound')], 'PlayMusic': [(0, 'sound')],
    'PlayMusicEx': [(0, 'sound')], 'SetMapMusic': [(0, 'sound')], 'PlayMusicBJ': [(0, 'sound')],
    'PlayMusicExBJ': [(0, 'sound')], 'PlayThematicMusicBJ': [(0, 'sound')], 'PlayThematicMusicExBJ': [(0, 'sound')],
    'SetMapMusicIndexedBJ': [(0, 'sound')], 'SetMapMusicRandomBJ': [(0, 'sound')],
    'GetSoundFileDuration': [(0, 'sound')], 'GetSoundFileDurationBJ': [(0, 'sound')],
    'CreateImage': [(0, 'texture')], 'CreateImageBJ': [(0, 'texture')], 'BlzFrameSetTexture': [(1, 'texture')],
    'DzFrameSetTexture': [(1, 'texture')], 'BlzChangeMinimapTerrainTex': [(0, 'texture')],
    'SetAltMinimapIcon': [(0, 'texture')], 'BlzSetAbilityIcon': [(1, 'texture')],
    'BlzSetAbilityActivatedIcon': [(1, 'texture')], 'BlzSetItemIconPath': [(1, 'texture')],
    'ContinueCinematicFadeAfterBJ': [(5, 'texture')], 'CreateQuestBJ': [(3, 'texture')],
    'BlzFrameSetFont': [(1, 'font')], 'Preload': [(0, 'preload')], 'BlzLoadTOCFile': [(0, 'toc')],
    'PlayCinematic': [(0, 'movie')],
    'BlzCreateFrame': [(0, 'frame')], 'BlzCreateSimpleFrame': [(0, 'frame')], 'BlzGetFrameByName': [(0, 'frame')],
    'BlzCreateFrameByType': [(1, 'frame'), (3, 'frame')],
}
LIST_MAX = 400
MAX_EVAL = 4000
MAX_DEPTH = 6


def _text(v):
    if v is None:
        return None
    try:
        return v.encode('latin-1').decode('utf-8', 'surrogateescape')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return v.encode('latin-1', 'replace').decode('utf-8', 'surrogateescape')


def _latin1(text):
    if isinstance(text, bytes):
        return text.decode('latin-1')
    try:
        text.encode('latin-1')
        return text
    except UnicodeEncodeError:
        return text.encode('utf-8', 'surrogateescape').decode('latin-1')


def plausible(name, kind):
    if not name or len(name) > 259 or any(ord(c) < 32 for c in name):
        return False
    if re.fullmatch(r'[.\\/ ]*(?:\.\w*)?', name):
        return False
    if kind == 'frame':
        return len(name) < 80 and all(c.isalnum() or c in '_- ' for c in name)
    if any(c in '<>"|?*' for c in name) or ':' in name[2:] or name[:2].count(':') and not name[0].isalpha():
        return False
    if kind in ('preload', 'toc', 'movie', 'font') and not re.search(r'\.\w{1,5}$', name):
        return False
    return True


def _walk_names(e):
    return [n.name for n in jass_ast.walk(e) if type(n) is jass_ast.Name and n.name not in ('true', 'false', 'null')]


def _subst(e, mapping):
    t = type(e)
    if t is jass_ast.Name:
        return mapping.get(e.name, e)
    if t is jass_ast.Call:
        return jass_ast.Call(e.name, [_subst(a, mapping) for a in e.args], e.line)
    if t is jass_ast.Binary:
        return jass_ast.Binary(e.op, _subst(e.left, mapping), _subst(e.right, mapping), e.line)
    if t is jass_ast.Unary:
        return jass_ast.Unary(e.op, _subst(e.operand, mapping), e.line)
    if t is jass_ast.Paren:
        return jass_ast.Paren(_subst(e.inner, mapping), e.line)
    if t is jass_ast.Index:
        return jass_ast.Index(_subst(e.base, mapping), _subst(e.index, mapping), e.line)
    return e


def _run(script, libs, budget, seconds, early, record):
    import jass_eval
    if sys.getrecursionlimit() < 20000:
        sys.setrecursionlimit(20000)
    it = jass_eval.Interpreter(script, jass_eval.libraries() if libs is None else libs, budget, seconds)
    jass_eval._handle_natives(it.native_types)
    it.stopped = None
    saved = {}

    def recorder(name):
        kinds = FILE_ARGUMENTS[name]

        def rec(interp, *args):
            who = interp._frames[-1][2] if interp._frames else None
            for idx, kind in kinds:
                if idx < len(args) and isinstance(args[idx], str) and args[idx]:
                    record.append((name, kind, args[idx], who))
            return jass_eval.DEFAULTS.get(interp.native_types.get(name))
        return rec
    for name in FILE_ARGUMENTS:
        saved[name] = jass_eval.NATIVES.get(name)
        jass_eval.NATIVES[name] = recorder(name)
    try:
        it.early = early
        try:
            it.start()
            it.run_early()
        except jass_eval.Budget as e:
            it.stopped = str(e)
    finally:
        for name, old in saved.items():
            if old is None:
                jass_eval.NATIVES.pop(name, None)
            else:
                jass_eval.NATIVES[name] = old
    return it


def file_names(text, budget=600000, seconds=15.0, early=5.0, libs=None, deadline=None):
    text = _latin1(text)
    try:
        tree = jass_ast.parse(text)
    except jass_ast.JassSyntaxError as e:
        return {'error': 'The script does not parse (%s).' % e, 'lines': ['The script does not parse.']}
    t0 = time.time()
    deadline = deadline or t0 + seconds * 2
    funcs = dict((f.name, f) for f in tree.functions)
    globals_ = set(g.name for g in tree.globals)
    items, seen = [], set()

    def add(name, native, kind, how, function, line):
        if not plausible(name, kind):
            return
        key = (name, native, how)
        if key in seen:
            return
        seen.add(key)
        items.append({'name': name, 'native': native, 'kind': kind, 'how': how, 'function': function, 'line': line})

    record = []
    it = None
    try:
        it = _run(text.encode('latin-1'), libs, budget, seconds, early, record)
    except Exception as e:
        run = {'error': str(e)}
    else:
        run = {'steps': it.steps, 'stopped': it.stopped, 'crashes': len(it.crashes),
               'unknown_natives': len(it.unknown)}
    for native, kind, val, who in record:
        add(_text(val), native, kind, 'ran', who, 0)
    ran = len(items)

    templates = {}
    unresolved = [0]
    ground = []

    def classify(expr, fname, native, kind, line, how, depth):
        if type(expr) is jass_ast.Literal:
            if expr.kind == 'string':
                add(_text(jass_ast._unescape(expr.text[1:-1])), native, kind, 'literal', fname, line)
            return
        f = funcs.get(fname)
        params = set(n for _t, n in f.params) if f else set()
        locals_ = set(d.name for d in f.locals) if f else set()
        names = _walk_names(expr)
        if any(n in locals_ for n in names):
            unresolved[0] += 1
            return
        if any(n in params for n in names):
            if depth < MAX_DEPTH and len(templates.setdefault(fname, [])) < 200:
                templates[fname].append((expr, native, kind, line))
            else:
                unresolved[0] += 1
            return
        if any(n not in globals_ for n in names):
            unresolved[0] += 1
            return
        ground.append((expr, native, kind, fname, line, how))

    for f in tree.functions:
        for c in (n for n in jass_ast.walk(f) if type(n) is jass_ast.Call):
            for idx, kind in FILE_ARGUMENTS.get(c.name, ()):
                if idx < len(c.args) and c.name not in funcs:
                    classify(c.args[idx], f.name, c.name, kind, c.line or f.line, 'computed', 0)
    sites = {}
    if templates:
        for f in tree.functions:
            for c in (n for n in jass_ast.walk(f) if type(n) is jass_ast.Call):
                if c.name in funcs and c.name != f.name:
                    sites.setdefault(c.name, []).append((f.name, c))
    done = set()
    for _round in range(MAX_DEPTH):
        grew = False
        for callee in list(templates):
            g = funcs[callee]
            for expr, native, kind, line in list(templates[callee]):
                for caller, c in sites.get(callee, ()):
                    key = (callee, id(expr), id(c))
                    if key in done or len(c.args) != len(g.params):
                        continue
                    done.add(key)
                    grew = True
                    mapping = dict((nm, a) for (_t, nm), a in zip(g.params, c.args))
                    classify(_subst(expr, mapping), caller, native, kind, c.line or line, 'param', _round + 1)
        if not grew:
            break
    evaluated = 0
    if it is not None:
        import jass_eval
        cache = {}
        for expr, native, kind, fname, line, how in ground:
            if evaluated >= MAX_EVAL or time.time() > deadline:
                unresolved[0] += 1
                continue
            src = jass_ast._ue(expr)
            if src not in cache:
                evaluated += 1
                try:
                    cache[src] = it.text(src)
                except (jass_eval.JassError, RecursionError, KeyError, TypeError, ValueError):
                    cache[src] = None
            if cache[src]:
                add(cache[src], native, kind, how, fname, line)
            else:
                unresolved[0] += 1
    else:
        unresolved[0] += len(ground)
    lits = set(_text(jass_ast._unescape(n.text[1:-1])) for n in jass_ast.walk(tree)
               if type(n) is jass_ast.Literal and n.kind == 'string')
    for x in items:
        x['known'] = x['how'] == 'literal' or x['name'] in lits
    built = [x for x in items if not x['known']]
    names = sorted(set(x['name'] for x in built if x['kind'] != 'frame'))
    frame_names = sorted(set(x['name'] for x in built if x['kind'] == 'frame'))
    counts = {'items': len(items), 'literal': sum(1 for x in items if x['how'] == 'literal'),
              'ran': sum(1 for x in items if x['how'] == 'ran'),
              'computed': sum(1 for x in items if x['how'] == 'computed'),
              'param': sum(1 for x in items if x['how'] == 'param'), 'names': len(names),
              'frame_names': len(frame_names), 'known': sum(1 for x in items if x['known']),
              'unresolved': unresolved[0]}
    items.sort(key=lambda x: (x['known'], x['how'], x['kind'], x['name']))
    out = {'items': items[:LIST_MAX], 'names': names, 'frame_names': frame_names, 'counts': counts, 'run': run,
           'ran_before_static': ran, 'all_items': items}
    out['lines'] = summary(out)
    return out


def summary(r):
    if r.get('error'):
        return [r['error']]
    c = r['counts']
    if not c['names']:
        return ['The script asks for no file name that it builds while it runs%s.' % (
            ' (%d could not be worked out)' % c['unresolved'] if c['unresolved'] else '')]
    out = ['%d file names the script builds while it runs (the text has no literal for them; %d arguments could not be '
           'worked out).' % (c['names'], c['unresolved'])]
    for x in [x for x in r['items'] if not x['known'] and x['kind'] != 'frame'][:6]:
        out.append('  %s (%s): %s' % (x['native'], x['kind'], x['name']))
    return out

