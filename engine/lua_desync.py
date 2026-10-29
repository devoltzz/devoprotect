# Finds handles a Lua script creates while it loads, outside any function: a source of desyncs.
import os
import re

import lua_ast


REF_30 = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref', '3.0'))
_PRIMITIVES = frozenset(('integer', 'real', 'boolean', 'string', 'code', 'nothing', 'handle'))
_RX_BUILDS = re.compile(r'(?:Blz)?(?:Create|Add|Init(?:Hashtable|GameCache)|TriggerRegister|TriggerAdd|DialogAdd|'
                        r'QuestCreate|Place|RestoreUnit|Rect\Z|RectFromLoc\Z|Location\Z|And\Z|Or\Z|Not\Z|'
                        r'Condition\Z|Filter\Z)')
_NOT_BUILT = frozenset(('LoadLocationHandle',))
_RUNS_NOW = frozenset(('pcall', 'xpcall'))
_CREATORS = None


def _signatures(text, kind):
    rx = r'(?m)^\s*(?:constant\s+)?native\s+(\w+)\s+takes\s+.*?\s+returns\s+(\w+)' if kind == 'native' else \
        r'(?m)^\s*(?:constant\s+)?function\s+(\w+)\s+takes\s+.*?\s+returns\s+(\w+)'
    return [(m.group(1), m.group(2)) for m in re.finditer(rx, text)]


def creators(ref=REF_30):
    global _CREATORS
    if _CREATORS is not None and ref == REF_30:
        return _CREATORS
    with open(os.path.join(ref, 'common.j'), encoding='latin-1') as f:
        common = f.read()
    out = {}
    for name, ret in _signatures(common, 'native'):
        if ret in _PRIMITIVES or name in _NOT_BUILT:
            continue
        if ret == 'location' or _RX_BUILDS.match(name):
            out[name] = 'native'
    try:
        with open(os.path.join(ref, 'blizzard.j'), encoding='latin-1') as f:
            bj = f.read()
    except OSError:
        bj = ''
    bodies = {}
    for m in re.finditer(r'(?ms)^function\s+(\w+)\s+takes\s+.*?\s+returns\s+(\w+)\s*$(.*?)^endfunction', bj):
        if m.group(2) not in _PRIMITIVES:
            bodies[m.group(1)] = set(re.findall(r'\b(\w+)\s*\(', m.group(3)))
    changed = True
    while changed:
        changed = False
        for name, calls in bodies.items():
            if name not in out and calls & set(out):
                out[name] = 'blizzard.j'
                changed = True
    if ref == REF_30:
        _CREATORS = out
    return out


def _call_name(call):
    f = call.func
    parts = []
    while isinstance(f, lua_ast.Index):
        if not (f.dot and isinstance(f.key, lua_ast.Literal) and isinstance(f.key.value, str)):
            return None
        parts.append(f.key.value)
        f = f.base
    if not isinstance(f, lua_ast.Name):
        return None
    name = '.'.join([f.name] + parts[::-1])
    return name + ':' + call.method if call.method else name


def _fn_body(expr):
    while isinstance(expr, lua_ast.Paren):
        expr = expr.inner
    return expr.body if isinstance(expr, lua_ast.FunctionExpr) else None


def _expr_calls(x, out, holder=None):
    if isinstance(x, lua_ast.Call):
        out.append((x, holder))
        body = _fn_body(x.func)
        if body is not None:
            out.append(('block', body))
        else:
            _expr_calls(x.func, out)
        name = _call_name(x)
        for i, a in enumerate(x.args or ()):
            if name in _RUNS_NOW and i == 0 and _fn_body(a) is not None:
                out.append(('block', _fn_body(a)))
            else:
                _expr_calls(a, out)
    elif isinstance(x, lua_ast.FunctionExpr):
        return
    elif isinstance(x, lua_ast.Index):
        _expr_calls(x.base, out)
        _expr_calls(x.key, out)
    elif isinstance(x, (lua_ast.Unary,)):
        _expr_calls(x.operand, out)
    elif isinstance(x, lua_ast.Binary):
        _expr_calls(x.left, out)
        _expr_calls(x.right, out)
    elif isinstance(x, lua_ast.Paren):
        _expr_calls(x.inner, out, holder)
    elif isinstance(x, lua_ast.Table):
        for k, v in x.fields:
            if k is not None and not isinstance(k, str):
                _expr_calls(k, out)
            _expr_calls(v, out)
    elif isinstance(x, (list, tuple)):
        for y in x:
            _expr_calls(y, out)


def _run_calls(block, local_names=None):
    out = []
    stack = [block]
    while stack:
        b = stack.pop()
        for s in b:
            found = []
            if isinstance(s, lua_ast.LocalStmt):
                for i, v in enumerate(s.values or ()):
                    _expr_calls(v, found, ('local', s.names[i]) if i < len(s.names) else None)
            elif isinstance(s, lua_ast.AssignStmt):
                for t in s.targets:
                    if not isinstance(t, lua_ast.Name):
                        _expr_calls(t, found)
                for i, v in enumerate(s.values or ()):
                    t = s.targets[i] if i < len(s.targets) else None
                    _expr_calls(v, found, ('global', t.name) if isinstance(t, lua_ast.Name) else
                                ('field', None) if t is not None else None)
            elif isinstance(s, lua_ast.CallStmt):
                _expr_calls(s.call, found)
            elif isinstance(s, lua_ast.IfStmt):
                for cond, body in s.branches:
                    if cond is not None:
                        _expr_calls(cond, found)
                    stack.append(body)
            elif isinstance(s, lua_ast.WhileStmt):
                _expr_calls(s.cond, found)
                stack.append(s.body)
            elif isinstance(s, lua_ast.RepeatStmt):
                stack.append(s.body)
                _expr_calls(s.cond, found)
            elif isinstance(s, lua_ast.NumericForStmt):
                _expr_calls([s.start, s.stop, s.step], found)
                stack.append(s.body)
            elif isinstance(s, lua_ast.GenericForStmt):
                _expr_calls(s.exprs, found)
                stack.append(s.body)
            elif isinstance(s, lua_ast.DoStmt):
                stack.append(s.body)
            elif isinstance(s, lua_ast.ReturnStmt):
                _expr_calls(s.values, found)
            for c, holder in found:
                if c == 'block':
                    stack.append(holder)
                else:
                    out.append((c, holder))
    return out


def _all_functions(tree):
    out = {}
    stack = [tree.body]
    while stack:
        x = stack.pop()
        if isinstance(x, lua_ast.FunctionStmt):
            out[x.name] = x.body
            stack.append(x.body)
        elif isinstance(x, (lua_ast.AssignStmt, lua_ast.LocalStmt)):
            targets = x.targets if isinstance(x, lua_ast.AssignStmt) else [lua_ast.Name(n) for n in x.names]
            for i, v in enumerate(x.values or ()):
                body = _fn_body(v)
                if body is not None and i < len(targets) and isinstance(targets[i], lua_ast.Name):
                    out.setdefault(targets[i].name, body)
            stack.extend(v for v in (x.values or ()))
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, lua_ast.Node):
            for cls in type(x).__mro__:
                for slot in getattr(cls, '__slots__', ()):
                    if slot not in ('line', 'comment', 'leading_comments', 'inner_comments', 'span'):
                        v = getattr(x, slot, None)
                        if isinstance(v, (list, lua_ast.Node)):
                            stack.append(v)
                        elif isinstance(v, tuple):
                            stack.extend(v)
    return out


def _assigned_in_functions(tree, functions):
    out = set()
    for body in functions.values():
        stack = [body]
        while stack:
            x = stack.pop()
            if isinstance(x, lua_ast.AssignStmt):
                out.update(t.name for t in x.targets if isinstance(t, lua_ast.Name))
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, lua_ast.Node):
                for cls in type(x).__mro__:
                    for slot in getattr(cls, '__slots__', ()):
                        if slot in ('line', 'comment', 'leading_comments', 'inner_comments', 'span'):
                            continue
                        v = getattr(x, slot, None)
                        if isinstance(v, (list, lua_ast.Node)):
                            stack.append(v)
                        elif isinstance(v, tuple):
                            stack.extend(y for y in v if isinstance(y, (list, lua_ast.Node, tuple)))
    return out


def scan(text, tree=None):
    res = {'items': [], 'error': None}
    if tree is None:
        try:
            tree = lua_ast.parse(text)
        except lua_ast.LuaSyntaxError as e:
            res['error'] = 'the script does not parse (%s)' % e
            return res
    made = creators()
    functions = _all_functions(tree)
    memo = {}

    def builds(name, seen):
        if name in memo:
            return memo[name]
        if name in seen or name not in functions:
            return None
        seen = seen | {name}
        found = None
        for c, _h in _run_calls(functions[name]):
            n = _call_name(c)
            if n is None:
                continue
            if n in made and n not in functions:
                found = ([], n)
                break
            sub = builds(n, seen)
            if sub is not None:
                found = ([n] + sub[0], sub[1])
                break
        memo[name] = found
        return found

    reassigned = None
    for c, holder in _run_calls(tree.body):
        n = _call_name(c)
        if n is None:
            continue
        if n in made and n not in functions:
            kind, via, native = 'direct', [], n
        else:
            got = builds(n, frozenset())
            if got is None:
                continue
            kind, via, native = 'via', [n] + got[0], got[1]
        target = holder[1] if holder and holder[0] == 'global' else None
        if target is not None and reassigned is None:
            reassigned = _assigned_in_functions(tree, functions)
        res['items'].append({'line': c.line, 'name': native, 'kind': kind, 'via': via, 'target': target,
                             'reassigned': bool(target and target in reassigned)})
    res['items'].sort(key=lambda x: x['line'])
    return res


def scan_map(path):
    import single_player
    a, sc, _strings = single_player.read_map(path)
    if sc['language'] != 'lua' or sc['bytes'] is None:
        return {'items': [], 'error': None, 'language': sc['language']}
    r = scan(sc['bytes'].decode('utf-8', 'surrogateescape'))
    r['language'] = 'lua'
    return r


def _where(x):
    s = 'line %d %s' % (x['line'], x['name'])
    if x['via']:
        s += ' (through %s)' % ' > '.join(x['via'][:3])
    return s


def reforged_items(result, item, limit=5):
    xs = (result or {}).get('items') or []
    if not xs:
        return []
    worst = [x for x in xs if x['reassigned']]
    rest = [x for x in xs if not x['reassigned']]
    out = []
    if worst:
        out.append(
            item(
                'lua_root_handle_reset',
                'warning',
                'The Lua script creates %d handle(s) while it loads, '
                'outside any function, into a global that a function sets again: %s%s. This is the shape of a '
                'measured multiplayer desync (a location created at the top of war3map.lua and created again '
                'in the map\'s init); single player is not affected. Keep only the one inside '
                'the function.'
                % (
                    len(worst),
                    ', '.join(_where(x) + ' (%s)' % x['target'] for x in worst[:limit]),
                    ', ...' if len(worst) > limit else '',
                ),
                'none',
                count=len(worst),
                sites=[_site(x) for x in worst[:limit]],
            )
        )
    if rest:
        body_text = (
            'The Lua script also creates %d other handle(s) while it loads, outside any function: %s%s. '
            if worst
            else 'The Lua script creates %d handle(s) while it loads, outside any function: %s%s. '
        )
        out.append(
            item(
                'lua_root_handles',
                'info',
                (
                    body_text + 'Handles made there are a known source of multiplayer '
                    'desyncs when they are thrown away and collected; if the map desyncs, move them into a function '
                    'the map runs at its start.'
                )
                % (len(rest), ', '.join(_where(x) for x in rest[:limit]), ', ...' if len(rest) > limit else ''),
                'none',
                count=len(rest),
                sites=[_site(x) for x in rest[:limit]],
            )
        )
    return out


def _site(x):
    return dict((k, x[k]) for k in ('line', 'name', 'kind', 'via', 'target', 'reassigned'))
