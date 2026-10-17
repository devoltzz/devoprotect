# Reads the World Editor's TriggerData.txt from the game files.
import contextlib
import functools
import hashlib
import json
import os
import re



HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.normpath(os.path.join(HERE, '..', 'cache'))
CACHE_FORMAT = 1

KINDS = ('event', 'condition', 'action', 'call')
FUNCTION_SECTIONS = {'triggerevents': 'event', 'triggerconditions': 'condition', 'triggeractions': 'action',
                     'triggercalls': 'call'}
KNOWN_EXTRA_SECTIONS = ('DefaultTriggerCategories', 'DefaultTriggers')
META_SUFFIXES = ('Defaults', 'Limits', 'Category', 'DisplayName', 'Parameters', 'ScriptName', 'UseWithAI',
                 'AIDefaults')
SPECIAL_TYPES = ('nothing', 'Null')
RX_META = re.compile(r'^_(.+)_([A-Za-z]+)$')
RX_LINES = re.compile(r'\r\n|\r|\n')
MULTIPLE = {
    'IfThenElseMultiple': ('condition', 'action', 'action'),
    'AndMultiple': ('condition',),
    'OrMultiple': ('condition',),
    'ForLoopAMultiple': ('action',),
    'ForLoopBMultiple': ('action',),
    'ForLoopVarMultiple': ('action',),
    'ForGroupMultiple': ('action',),
    'ForForceMultiple': ('action',),
    'EnumDestructablesInRectAllMultiple': ('action',),
    'EnumDestructablesInCircleBJMultiple': ('action',),
    'EnumItemsInRectBJMultiple': ('action',),
}

DROPPING = frozenset(('duplicate key', 'duplicate metadata', 'orphan metadata', 'malformed metadata key',
                      'entry outside a section', 'empty key'))

_MEMO = {}


class UnknownFunction(KeyError):
    def __init__(self, kind, name):
        KeyError.__init__(self, kind, name)
        self.kind = kind
        self.name = name

    def __str__(self):
        return 'unknown %s function: %s' % (self.kind, self.name)


class _Record(object):
    FIELDS = ()

    def __init__(self, **values):
        for f in self.FIELDS:
            setattr(self, f, values.get(f))

    def __eq__(self, other):
        return type(self) is type(other) and all(getattr(self, f) == getattr(other, f) for f in self.FIELDS)

    def __hash__(self):
        return hash((type(self).__name__, self.name))

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, ', '.join('%s=%r' % (f, getattr(self, f)) for f in self.FIELDS[:4]))

    def to_dict(self):
        return dict((f, getattr(self, f)) for f in self.FIELDS)


class TriggerFunction(_Record):
    FIELDS = ('name', 'kind', 'version', 'arg_types', 'return_type', 'usable_in_event', 'script_name', 'defaults',
              'category', 'display_name', 'meta')

    @property
    def arity(self):
        return len(self.arg_types)


class Preset(_Record):
    FIELDS = ('name', 'version', 'type', 'code', 'display')


class TriggerType(_Record):
    FIELDS = ('name', 'version', 'can_be_global', 'can_be_compared', 'display', 'base_type', 'import_type',
              'treat_as_base')


def _kind_name(kind):
    return KINDS[kind] if isinstance(kind, int) and 0 <= kind < len(KINDS) else kind


def _unquote(s):
    if s.startswith('"'):
        return s[1:-1] if len(s) > 1 and s.endswith('"') else s[1:]
    return s


def _fields(value):
    out, cur, quoted = [], [], False
    for c in value:
        if c == '"':
            quoted = not quoted
        elif c == ',' and not quoted:
            out.append(''.join(cur))
            cur = []
            continue
        cur.append(c)
    out.append(''.join(cur))
    return [_unquote(x.strip()) for x in out]


def _list(value):
    return [] if not value.strip() else _fields(value)


def _script_text(code):
    if code.startswith('`'):
        inner = code[1:-1] if len(code) > 1 and code.endswith('`') else code[1:]
        return '"%s"' % inner
    return code


class TriggerData(object):
    def __init__(self):
        self.events, self.conditions, self.actions, self.calls = {}, {}, {}, {}
        self.presets, self.presets_by_code = {}, {}
        self.types, self.type_defaults = {}, {}
        self.categories = {}
        self.extra_sections = {}
        self.by_script, self.by_script_all = {}, {}
        self.multiple = {}
        self.warnings = []
        self.stats = {'entries': 0, 'dropped': 0}
        self.md5 = None
        self.source = None

    def _table(self, kind):
        return {'event': self.events, 'condition': self.conditions, 'action': self.actions,
                'call': self.calls}.get(_kind_name(kind))

    def get(self, kind, name):
        table = self._table(kind)
        return None if table is None else table.get(name)

    def arity(self, kind, name):
        f = self.get(kind, name)
        if f is None:
            raise UnknownFunction(_kind_name(kind), name)
        return len(f.arg_types)

    def base_type(self, t):
        seen = set()
        while t in self.types and self.types[t].base_type and t not in seen:
            seen.add(t)
            t = self.types[t].base_type
        return t

    def functions(self):
        for kind in KINDS:
            for f in self._table(kind).values():
                yield f

    def held(self):
        n = len(self.categories) + len(self.types) + len(self.type_defaults) + len(self.presets)
        n += sum(1 + len(f.meta) for f in self.functions())
        return n + sum(len(s) for s in self.extra_sections.values())

    def _index(self):
        self.presets_by_code = {}
        for p in self.presets.values():
            self.presets_by_code.setdefault((p.type, p.code), p)
        groups = {}
        for f in self.functions():
            groups.setdefault((f.kind, f.script_name), []).append(f)
        self.by_script_all = dict((k, sorted(v, key=lambda f, s=k[1]: (f.name != s, f.name in MULTIPLE)))
                                  for k, v in groups.items())
        self.by_script = dict((k, v[0]) for k, v in self.by_script_all.items())
        self.multiple = {}
        for name, child_kinds in MULTIPLE.items():
            f = self.conditions.get(name) or self.actions.get(name)
            if f is not None:
                self.multiple[name] = {'branches': len(child_kinds), 'kind': f.kind, 'child_kinds': list(child_kinds)}

    def to_dict(self):
        return {'functions': dict((kind, [f.to_dict() for f in self._table(kind).values()]) for kind in KINDS),
                'presets': [p.to_dict() for p in self.presets.values()],
                'types': [t.to_dict() for t in self.types.values()],
                'type_defaults': self.type_defaults,
                'categories': dict((k, list(v)) for k, v in self.categories.items()),
                'extra_sections': self.extra_sections,
                'warnings': self.warnings,
                'stats': self.stats}

    @classmethod
    def from_dict(cls, d):
        td = cls()
        for kind in KINDS:
            table = td._table(kind)
            for values in d['functions'][kind]:
                table[values['name']] = TriggerFunction(**values)
        td.presets = dict((v['name'], Preset(**v)) for v in d['presets'])
        td.types = dict((v['name'], TriggerType(**v)) for v in d['types'])
        td.type_defaults = dict(d['type_defaults'])
        td.categories = dict((k, tuple(v)) for k, v in d['categories'].items())
        td.extra_sections = dict((k, dict(v)) for k, v in d['extra_sections'].items())
        td.warnings = list(d['warnings'])
        td.stats = dict(d['stats'])
        td._index()
        return td

    def __eq__(self, other):
        return isinstance(other, TriggerData) and self.to_dict() == other.to_dict()

    __hash__ = None


_SECTIONS = ('triggercategories', 'triggertypes', 'triggertypedefaults', 'triggerparams') + tuple(FUNCTION_SECTIONS)
_KNOWN_SECTIONS = frozenset(_SECTIONS + tuple(s.lower() for s in KNOWN_EXTRA_SECTIONS))
_CANONICAL_SUFFIX = dict((s.lower(), s) for s in META_SUFFIXES)


def _number(s, name, note):
    try:
        return int(s)
    except ValueError:
        note('bad number', '%s: %r' % (name, s))
        return None


def _function(kind, name, f, note):
    if kind == 'call':
        if len(f) < 3:
            note('short definition', name)
        g = f + [''] * (3 - len(f))
        usable = _number(g[1], name, note) if g[1] else 0
        if usable not in (0, 1, None):
            note('usable-in-event value', '%s=%s, read as %s' % (name, g[1], bool(usable)))
        version, ret, args = g[0], g[2] or None, f[3:]
    else:
        version, ret, usable, args = f[0], None, 0, f[1:]
    types = []
    for a in args:
        if not a:
            note('empty argument type', name)
        elif a != 'nothing':
            types.append(a)
    return TriggerFunction(name=name, kind=kind, version=_number(version, name, note), arg_types=types,
                           return_type=ret, usable_in_event=bool(usable), script_name=name, defaults=[],
                           category=None, display_name=None, meta={})


def parse(text):
    td = TriggerData()
    found = []
    line = [0]

    def note(category, detail, at=None):
        found.append((line[0] if at is None else at, category, detail))
        if category in DROPPING:
            td.stats['dropped'] += 1

    section = None
    seen = {}
    pending = []
    where = {}
    for n, raw in enumerate(RX_LINES.split(text.lstrip('\ufeff')), 1):
        line[0] = n
        s = raw.strip()
        if not s or s.startswith('//'):
            continue
        if raw != raw.rstrip():
            note('trailing whitespace', s)
        if s.startswith('[') and s.endswith(']'):
            section = s[1:-1].strip()
            if section.lower() not in _KNOWN_SECTIONS:
                note('unknown section', '[%s] kept as raw text in extra_sections' % section)
            continue
        if '=' not in s:
            note("line without '='", s)
            continue
        key, value = [x.strip() for x in s.split('=', 1)]
        td.stats['entries'] += 1
        if value.count('"') % 2:
            note('unterminated quote', key)
        if section is None or not key:
            note('entry outside a section' if key else 'empty key', key or s)
            continue
        low = section.lower()
        kind = FUNCTION_SECTIONS.get(low)
        if kind and key.startswith('_'):
            pending.append((kind, key, value, n))
            continue
        first = seen.setdefault(low, {})
        if key in first:
            note('duplicate key', '[%s] %s, the line %d is kept' % (section, key, first[key]))
            continue
        first[key] = n
        f = _fields(value)
        if kind:
            td._table(kind)[key] = _function(kind, key, f, note)
            where[(kind, key)] = n
        elif low == 'triggertypes':
            g = f + [''] * (7 - len(f))
            td.types[key] = TriggerType(name=key, version=_number(g[0], key, note), display=g[3],
                                        can_be_global=bool(_number(g[1] or '0', key, note)),
                                        can_be_compared=bool(_number(g[2] or '0', key, note)),
                                        base_type=g[4] or None, import_type=g[5] or None,
                                        treat_as_base=bool(_number(g[6] or '0', key, note)))
        elif low == 'triggertypedefaults':
            td.type_defaults[key] = _script_text(f[0])
        elif low == 'triggercategories':
            td.categories[key] = (f[0], f[1] if len(f) > 1 else '')
        elif low == 'triggerparams':
            if len(f) < 4:
                note('short definition', key)
            g = f + [''] * (4 - len(f))
            if g[2].startswith('`') and not (len(g[2]) > 1 and g[2].endswith('`')):
                note('unterminated backquote', key)
            td.presets[key] = Preset(name=key, version=_number(g[0], key, note), type=g[1], code=_script_text(g[2]),
                                     display=g[3])
        else:
            td.extra_sections.setdefault(section, {})[key] = value

    for kind, key, value, n in pending:
        line[0] = n
        m = RX_META.match(key)
        if not m:
            note('malformed metadata key', key)
            continue
        name, suffix = m.groups()
        f = td._table(kind).get(name)
        if f is None:
            note('orphan metadata', '%s: there is no %s %s' % (key, kind, name))
            continue
        canonical = _CANONICAL_SUFFIX.get(suffix.lower())
        if canonical is None:
            note('unknown metadata suffix', '%s, kept in meta as written' % key)
            canonical = suffix
        elif canonical != suffix:
            note('metadata suffix case', '%s read as _%s_%s' % (key, name, canonical))
        if canonical in f.meta:
            note('duplicate metadata', '%s, the first is kept' % key)
            continue
        f.meta[canonical] = value

    for f in td.functions():
        m = f.meta
        f.defaults = _list(m.get('Defaults', ''))
        f.category = _unquote(m['Category']) if m.get('Category') else None
        f.display_name = _unquote(m['DisplayName']) if 'DisplayName' in m else None
        f.script_name = _unquote(m['ScriptName']) if m.get('ScriptName') else f.name
        for t in f.arg_types + ([f.return_type] if f.return_type else []):
            if t not in td.types and t not in SPECIAL_TYPES:
                note('unknown type', '%s in the %s %s' % (t, f.kind, f.name), where[(f.kind, f.name)])
    td.warnings = ['line %d: %s: %s' % w for w in sorted(found, key=lambda w: w[0])]
    td._index()
    return td


def _decode(data):
    try:
        return data.decode('utf-8-sig'), None
    except UnicodeDecodeError as e:
        return data.decode('latin-1'), 'line %d: encoding: not UTF-8 (%s), read as latin-1' % (
            data[:e.start].count(b'\n') + 1, e.reason)


def _cache_file(cache_dir, md5):
    return os.path.join(cache_dir, 'triggerdata_%s.json' % md5)


def _write_atomic(path, text):
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.remove(tmp)


@functools.lru_cache(maxsize=None)
def _parser_id():
    try:
        with open(os.path.abspath(__file__), 'rb') as f:
            return '%d.%s' % (CACHE_FORMAT, hashlib.md5(f.read()).hexdigest())
    except OSError:
        return str(CACHE_FORMAT)


def _cached(md5, cache_dir):
    td = _MEMO.get(md5)
    if td is None:
        try:
            with open(_cache_file(cache_dir, md5), encoding='utf-8') as f:
                d = json.load(f)
            if d.get('parser') != _parser_id() or d.get('md5') != md5:
                return None
            td = TriggerData.from_dict(d['data'])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None
        td.md5 = md5
        _MEMO[md5] = td
    return td


def _from_bytes(data, source, cache_dir):
    md5 = hashlib.md5(data).hexdigest()
    td = _cached(md5, cache_dir)
    if td is None:
        text, problem = _decode(data)
        td = parse(text)
        if problem:
            td.warnings.insert(0, problem)
        td.md5 = md5
        _MEMO[md5] = td
        _write_atomic(_cache_file(cache_dir, md5),
                      json.dumps({'parser': _parser_id(), 'md5': md5, 'data': td.to_dict()}, ensure_ascii=False))
    td.source = source
    return td


def from_file(path, cache_dir=None):
    with open(path, 'rb') as f:
        return _from_bytes(f.read(), os.path.abspath(path), cache_dir or CACHE_DIR)


REF_DIR = next(
    (
        p
        for p in (os.path.normpath(os.path.join(HERE, '..', 'ref', '3.0')), os.path.join(HERE, 'ref', '3.0'))
        if os.path.isfile(os.path.join(p, 'common.j'))
    ),
    os.path.normpath(os.path.join(HERE, '..', 'ref', '3.0')),
)
REF_SCRIPTS = ('common.j', 'blizzard.j', 'common.ai')
RX_SIGNATURE = re.compile(r'(?m)^[ \t]*+(?:constant[ \t]++)?(?:native|function)[ \t]++(\w+)[ \t]++takes[ \t]++'
                          r'([^\n]*?)[ \t]++returns[ \t]++(\w+)')
_SIGNATURES = {}


_GAME_SCRIPTS = {}


def game_script(name, ref_dir=None, game=None):
    key = (ref_dir or REF_DIR, name, game)
    text = _GAME_SCRIPTS.get(key)
    if text is None:
        data = None
        try:
            with open(os.path.join(key[0], name), 'rb') as f:
                data = f.read()
        except OSError:
            try:
                import casc_wc3
                casc = casc_wc3.CascWC3(game or casc_wc3.DEFAULT_GAME)
                try:
                    data = casc.read_wc3('scripts\\' + name)
                finally:
                    casc.on_close()
            except Exception:
                data = None
        text = _GAME_SCRIPTS[key] = (data or b'').decode('utf-8', 'surrogateescape')
    return text


def script_signatures(ref_dir=None, extra=()):
    ref_dir = ref_dir or REF_DIR
    base = _SIGNATURES.get(ref_dir)
    if base is None:
        base = {}
        for name in REF_SCRIPTS:
            base.update(_signatures(game_script(name, ref_dir), base))
        _SIGNATURES[ref_dir] = base
    out = dict(base)
    for text in extra:
        out.update(_signatures(text, out))
    return out


def _signatures(text, known):
    out = {}
    for m in RX_SIGNATURE.finditer(text):
        if m.group(1) not in known and m.group(1) not in out:
            args = m.group(2).strip()
            out[m.group(1)] = (0 if args == 'nothing' else args.count(',') + 1, m.group(3))
    return out


class ScriptFallback(object):
    def __init__(self, td, signatures=None):
        self.td = td
        self.signatures = script_signatures() if signatures is None else signatures
        self.derived = {}

    def arity(self, kind, name):
        try:
            return self.td.arity(kind, name)
        except Exception as e:
            if not (isinstance(e, KeyError) or type(e).__name__ == 'UnknownFunction'):
                raise
            sig = self.signatures.get(name)
            if sig is None:
                raise
        n = max(sig[0] - 1, 0) if _kind_name(kind) == 'event' else sig[0]
        self.derived[(_kind_name(kind), name)] = n
        return n

    def __getattr__(self, name):
        if name == 'td':
            raise AttributeError(name)
        return getattr(self.td, name)

