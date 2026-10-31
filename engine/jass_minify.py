# Makes a JASS script smaller: no comments, short names, dead code out, constants inlined.
import os
import re

import jass_ast


REF_30 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref', '3.0'))
ALPHA = 'etaoinshrdlucmfwypvbgkqjxzETAOINSHRDLUCMFWYPVBGKQJXZ'
ALNUM = ALPHA + '0123456789'
INLINE_STRING_MAX = 14
KEPT = ('main', 'config')
SCRIPT_RUNNERS = frozenset(('EXExecuteScript',))
_RX_WORD = re.compile(r'[A-Za-z_]\w*')
_ENGINE = {}
_REF_TYPES = (jass_ast.Name, jass_ast.Call, jass_ast.FuncRef)


def engine_ids(libraries=None):
    paths = tuple(libraries) if libraries else (os.path.join(REF_30, 'common.j'), os.path.join(REF_30, 'blizzard.j'))
    if paths not in _ENGINE:
        import jass_obfuscate
        ids = set(jass_obfuscate.engine_ids([p for p in paths if os.path.isfile(p)]))
        ids.update(jass_obfuscate.KEYWORDS)
        _ENGINE[paths] = frozenset(ids)
    return _ENGINE[paths]


def _names_gen(avoid):
    n = 0
    while True:
        k, s, m = n, [], len(ALPHA)
        s.append(ALPHA[k % m])
        k //= m
        while k:
            k -= 1
            s.append(ALNUM[k % len(ALNUM)])
            k //= len(ALNUM)
        n += 1
        name = ''.join(s)
        if name not in avoid:
            yield name


def _pool_iter(pool, avoid):
    i = 0
    while True:
        if i == len(pool[1]):
            pool[1].append(next(pool[0]))
        name = pool[1][i]
        i += 1
        if name not in avoid:
            yield name


def _string_value(lit):
    return jass_ast._unescape(lit.text[1:-1])


def _is_pure(e):
    return not any(type(n) is jass_ast.Call for n in jass_ast.walk(e))


def minify_text(text, options=None):
    opt = dict({'rename': True, 'dead': True, 'inline': True, 'keep': (), 'libraries': None}, **(options or {}))
    rep = {'state': 'nothing_to_do', 'reason': None, 'before': len(text), 'after': len(text), 'removed_functions': 0,
           'removed_globals': 0, 'removed_names': [], 'inlined': 0, 'renamed': 0, 'names': {}, 'dynamic_execute': False,
           'dynamic_variable_events': False, 'dynamic_script': False}
    try:
        tree = jass_ast.parse(text)
    except jass_ast.JassSyntaxError as e:
        rep.update(state='refused', reason='The script does not parse (%s): kept as it was.' % e)
        return text, rep
    keep = set(opt['keep']) | set(KEPT)
    funcs = dict((f.name, f) for f in tree.functions)
    exec_literals, var_literals = set(), set()
    for n in jass_ast.walk(tree):
        if type(n) is jass_ast.Call:
            if n.name == 'ExecuteFunc':
                a = n.args[0] if n.args else None
                if type(a) is jass_ast.Literal and a.kind == 'string':
                    exec_literals.add(_string_value(a))
                else:
                    rep['dynamic_execute'] = True
            elif n.name == 'TriggerRegisterVariableEvent':
                a = n.args[1] if len(n.args) > 1 else None
                if type(a) is jass_ast.Literal and a.kind == 'string':
                    var_literals.add(_string_value(a))
                else:
                    rep['dynamic_variable_events'] = True
            elif n.name in SCRIPT_RUNNERS:
                a = n.args[0] if n.args else None
                if type(a) is jass_ast.Literal and a.kind == 'string':
                    keep.update(_RX_WORD.findall(_string_value(a)))
                else:
                    rep['dynamic_script'] = True
    if opt['inline']:
        uses = {}
        for n in jass_ast.walk(tree):
            if type(n) is jass_ast.Name:
                uses[n.name] = uses.get(n.name, 0) + 1
        consts = {}
        for g in tree.globals:
            if g.is_constant and not g.is_array and type(g.initializer) is jass_ast.Literal and g.name not in keep \
                    and g.name not in var_literals and g.initializer.kind in ('integer', 'real', 'string', 'rawcode',
                                                                              'boolean') \
                    and g.initializer.kind in _LITERAL_OF_TYPE.get(g.type, ()):
                lit = g.initializer
                if lit.kind != 'string' or len(lit.text) <= INLINE_STRING_MAX or uses.get(g.name, 0) <= 2:
                    consts[g.name] = lit
        if consts:
            rep['inlined'] = _inline(tree, consts)
    if opt['dead'] and not rep['dynamic_execute'] and not rep['dynamic_script']:
        dead = _dead_functions(tree, funcs, keep, exec_literals)
        if dead:
            tree.items = [it for it in tree.items if not (type(it) is jass_ast.Function and not it.is_native and
                                                          it.name in dead)]
            rep['removed_functions'] = len(dead)
            funcs = dict((n, f) for n, f in funcs.items() if n not in dead)
    if opt['dead'] and not rep['dynamic_script']:
        gone = _dead_globals(tree, funcs, var_literals, keep)
        rep['removed_globals'] = len(gone)
        rep['removed_names'] = gone
    if opt['rename']:
        names = _rename(tree, funcs, keep, exec_literals, var_literals, rep, opt['libraries'])
        rep['names'] = names
        rep['renamed'] = len(names)
    new = jass_ast.canonical(tree)
    if not new.endswith('\n'):
        new += '\n'
    try:
        again = jass_ast.parse(new)
    except jass_ast.JassSyntaxError as e:
        rep.update(state='failed', reason='The minified script does not parse (%s): kept as it was.' % e)
        return text, rep
    del again
    rep.update(state='done', after=len(new))
    return new, rep


_LITERAL_OF_TYPE = {
    'integer': ('integer', 'rawcode'),
    'real': ('real',),
    'string': ('string',),
    'boolean': ('boolean',),
}


def _inline(tree, consts):
    count = [0]

    def apply(node, cs):
        def repl(e):
            if type(e) is jass_ast.Name and e.name in cs:
                count[0] += 1
                lit = cs[e.name]
                return jass_ast.Literal(lit.kind, lit.text, e.line)
            return e

        for n in jass_ast.walk(node):
            t = type(n)
            if t is jass_ast.Call:
                n.args = [repl(a) for a in n.args]
            elif t is jass_ast.SetStmt:
                n.value = repl(n.value)
                if type(n.target) is jass_ast.Index:
                    n.target.index = repl(n.target.index)
            elif t is jass_ast.Index:
                n.index = repl(n.index)
            elif t is jass_ast.Binary:
                n.left, n.right = repl(n.left), repl(n.right)
            elif t is jass_ast.Unary:
                n.operand = repl(n.operand)
            elif t is jass_ast.Paren:
                n.inner = repl(n.inner)
            elif t is jass_ast.ReturnStmt and n.value is not None:
                n.value = repl(n.value)
            elif t is jass_ast.ExitWhenStmt:
                n.cond = repl(n.cond)
            elif t is jass_ast.LocalDecl and n.initializer is not None:
                n.initializer = repl(n.initializer)
            elif t is jass_ast.GlobalDecl and n.initializer is not None and not (n.is_constant and n.name in cs):
                n.initializer = repl(n.initializer)
            elif t is jass_ast.IfStmt:
                n.branches = [(None if c is None else repl(c), b) for c, b in n.branches]

    for g in tree.globals:
        apply(g, consts)
    for f in tree.functions:
        shadow = set(n for _t, n in f.params) | set(d.name for d in f.locals)
        apply(f, dict((k, v) for k, v in consts.items() if k not in shadow) if shadow & set(consts) else consts)
    return count[0]


def _dead_functions(tree, funcs, keep, exec_literals):
    edges = dict((n, set()) for n in funcs)
    for f in tree.functions:
        for n in jass_ast.walk(f):
            t = type(n)
            if t is jass_ast.Call and n.name in funcs:
                edges[f.name].add(n.name)
            elif t is jass_ast.FuncRef:
                edges[f.name].add(n.name)
    roots = [n for n in funcs if n in keep or n in exec_literals]
    for g in tree.globals:
        if g.initializer is not None:
            roots.extend(n.name for n in jass_ast.walk(g.initializer) if type(n) is jass_ast.FuncRef)
    seen, stack = set(), list(roots)
    while stack:
        n = stack.pop()
        if n in seen or n not in funcs:
            continue
        seen.add(n)
        stack.extend(edges.get(n, ()))
    return set(n for n in funcs if n not in seen)


def _dead_globals(tree, funcs, var_literals, keep):
    mentioned = set(var_literals)
    for f in tree.functions:
        if f.name in funcs:
            mentioned.update(n.name for n in jass_ast.walk(f) if type(n) is jass_ast.Name)
    for g in tree.globals:
        if g.initializer is not None:
            mentioned.update(n.name for n in jass_ast.walk(g.initializer) if type(n) is jass_ast.Name)
    removed = []
    for block in (it for it in tree.items if type(it) is jass_ast.Globals):
        kept = []
        for d in block.decls:
            if d.name not in mentioned and d.name not in keep and (d.initializer is None or _is_pure(d.initializer)):
                removed.append(d.name)
            else:
                kept.append(d)
        block.decls = kept
    return removed


def _rename(tree, funcs, keep, exec_literals, var_literals, rep, libraries):
    engine = engine_ids(libraries)
    natives = set(f.name for f in tree.natives)
    types_ = set(t.name for t in tree.types) | set(t.base for t in tree.types)
    protected = set(engine) | natives | types_ | set(keep)
    glob = dict((g.name, g) for it in tree.items if type(it) is jass_ast.Globals for g in it.decls)
    top_names = set(glob) | set(funcs)
    rename_funcs = not rep['dynamic_execute'] and not rep['dynamic_script']
    rename_globals = not rep['dynamic_variable_events'] and not rep['dynamic_script']
    refs, external, freq = {}, set(), {}
    for f in tree.functions:
        if f.name not in funcs:
            continue
        own_set = set(nm for _t, nm in f.params) | set(d.name for d in f.locals)
        lst = [n for n in jass_ast.walk(f) if type(n) in _REF_TYPES]
        refs[f.name] = (own_set, lst)
        for n in lst:
            if n.name in top_names:
                freq[n.name] = freq.get(n.name, 0) + 1
            elif n.name not in own_set:
                external.add(n.name)
    for g in glob.values():
        if g.initializer is not None:
            for n in jass_ast.walk(g.initializer):
                if type(n) in _REF_TYPES:
                    if n.name in top_names:
                        freq[n.name] = freq.get(n.name, 0) + 1
                    else:
                        external.add(n.name)
    movable = [name for name in top_names if name not in protected and not (name in funcs and not rename_funcs) and
               not (name in glob and not rename_globals)]
    movable.sort(key=lambda n: (-freq.get(n, 0), n))
    fixed = (top_names - set(movable)) | protected | external
    gen = _names_gen(fixed)
    top_map = dict((name, next(gen)) for name in movable)
    final_top = dict((n, top_map.get(n, n)) for n in top_names)
    local_maps = {}
    pool = [_names_gen(protected | external | set(final_top.values())), []]
    for fname, (own_set, lst) in refs.items():
        if not own_set:
            continue
        outside = set(final_top.get(n.name, n.name) for n in lst if n.name not in own_set)
        lgen = _pool_iter(pool, outside)
        f = funcs[fname]
        order = [nm for _t, nm in f.params] + [d.name for d in f.locals]
        local_maps[fname] = dict((nm, next(lgen)) for nm in dict.fromkeys(order))
    for g in glob.values():
        if g.initializer is not None:
            _rename_expr(g.initializer, {}, final_top, funcs)
        g.name = final_top.get(g.name, g.name)
    for f in tree.functions:
        if f.name not in funcs:
            continue
        lm = local_maps.get(f.name, {})
        f.params = [(t, lm.get(nm, nm)) for t, nm in f.params]
        for d in f.locals:
            d.name = lm.get(d.name, d.name)
        for n in refs[f.name][1]:
            t = type(n)
            if t is jass_ast.Name:
                n.name = lm.get(n.name) or final_top.get(n.name, n.name)
            elif t is jass_ast.Call:
                if n.name in funcs:
                    n.name = final_top[n.name]
                _rename_literals(n, final_top, exec_literals, var_literals)
            else:
                n.name = final_top.get(n.name, n.name)
    for f in tree.functions:
        if f.name in funcs:
            f.name = final_top.get(f.name, f.name)
    return dict((o, nw) for o, nw in final_top.items() if o != nw)


def _rename_expr(e, lm, top, funcs):
    for n in jass_ast.walk(e):
        t = type(n)
        if t is jass_ast.Name:
            n.name = lm.get(n.name) or top.get(n.name, n.name)
        elif t is jass_ast.FuncRef:
            n.name = top.get(n.name, n.name)
        elif t is jass_ast.Call and n.name in funcs:
            n.name = top.get(n.name, n.name)


def _rename_literals(call, top, exec_literals, var_literals):
    if call.name == 'ExecuteFunc' and call.args and type(call.args[0]) is jass_ast.Literal:
        a = call.args[0]
        v = _string_value(a)
        if v in top and v != top[v]:
            a.text = '"' + top[v] + '"'
    elif call.name == 'TriggerRegisterVariableEvent' and len(call.args) > 1 and type(call.args[1]) is jass_ast.Literal:
        a = call.args[1]
        v = _string_value(a)
        if v in top and v != top[v]:
            a.text = '"' + top[v] + '"'

