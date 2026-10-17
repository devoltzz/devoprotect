# Reads and writes war3map.wtg and war3map.wct.
import os
import struct
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple



HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, '..', 'docs', 'script-para-gatilhos')
TRIGGERDATA_TXT = os.path.join(CORPUS, 'game', 'war3.w3mod__ui__triggerdata.txt')

NEW_FORMAT = 0x80000004
KINDS = ('event', 'condition', 'action', 'call')
DISABLED, PRESET, VARIABLE, FUNCTION, LITERAL = range(-1, 4)
ROOT, LIBRARY, CATEGORY, GUI, COMMENT, SCRIPT, VARIABLE_ITEM, UNKNOWN_ITEM = (1 << i for i in range(8))
CLASSIFIERS = (ROOT, LIBRARY, CATEGORY, GUI, COMMENT, SCRIPT, VARIABLE_ITEM, UNKNOWN_ITEM)

_I32 = struct.Struct('<i')
_NEW_I32 = NEW_FORMAT - (1 << 32)


class UnknownFunction(Exception):
    def __init__(self, name, kind=None, offset=None):
        super().__init__(name)
        self.name, self.kind, self.offset = name, kind, offset


@dataclass
class Category:
    id: int
    name: str
    is_comment: int = 0
    expanded: Optional[int] = None
    parent_id: Optional[int] = None


@dataclass
class Variable:
    name: str
    type: str
    is_array: int = 0
    array_size: int = 1
    initialized: int = 0
    initial_value: str = ''
    id: Optional[int] = None
    parent_id: Optional[int] = None
    unknown: int = 1


@dataclass
class Parameter:
    kind: int
    value: str
    function: Optional['Function'] = None
    index: Optional['Parameter'] = None


@dataclass
class Function:
    kind: int
    name: str
    enabled: int = 1
    params: List[Parameter] = field(default_factory=list)
    branch: Optional[int] = None
    children: List['Function'] = field(default_factory=list)


@dataclass
class Trigger:
    name: str
    description: str = ''
    is_comment: int = 0
    enabled: int = 1
    is_text: int = 0
    initially_off: int = 0
    run_on_init: int = 0
    category_id: int = 0
    functions: List[Function] = field(default_factory=list)
    id: Optional[int] = None

    @property
    def parent_id(self):
        return self.category_id

    @parent_id.setter
    def parent_id(self, value):
        self.category_id = value


@dataclass
class MapTriggers:
    version: int = 7
    sub_version: Optional[int] = None
    game_version: int = 2
    categories: List[Category] = field(default_factory=list)
    variables: List[Variable] = field(default_factory=list)
    triggers: List[Trigger] = field(default_factory=list)
    deleted: Optional[Dict[int, Tuple[int, List[int]]]] = None
    elements: Optional[List[Tuple[int, object]]] = None


@dataclass
class CustomText:
    is_new_format: bool = False
    comment: str = ''
    header: Optional[str] = None
    texts: List[Optional[str]] = field(default_factory=list)
    version: int = 1


def _arity(td, kind, name):
    if td is None:
        raise TypeError('reading functions needs a TriggerData (td) for their arities')
    try:
        n = td.arity(KINDS[kind], name)
    except UnknownFunction:
        raise
    except Exception as e:
        if isinstance(e, KeyError) or type(e).__name__ == 'UnknownFunction':
            raise UnknownFunction(name, KINDS[kind]) from e
        raise
    if n is None:
        raise UnknownFunction(name, KINDS[kind])
    return n


class _Reader(object):
    def __init__(self, data, td):
        self.b, self.p, self.td = bytes(data), 0, td
        self.version = 7
        self.arities = {}

    def i32(self):
        try:
            v = _I32.unpack_from(self.b, self.p)[0]
        except struct.error:
            raise ValueError('truncated at offset %d' % self.p) from None
        self.p += 4
        return v

    def count(self):
        n = self.i32()
        if n < 0 or n > len(self.b) - self.p:
            raise ValueError('impossible count %d at offset %d' % (n, self.p - 4))
        return n

    def text(self):
        e = self.b.find(b'\0', self.p)
        if e < 0:
            raise ValueError('unterminated string at offset %d' % self.p)
        s = self.b[self.p:e].decode('utf-8', 'surrogateescape')
        self.p = e + 1
        return s

    def flag(self):
        v = self.i32()
        if v not in (0, 1):
            raise ValueError('flag %d at offset %d' % (v, self.p - 4))
        return v

    def arity(self, kind, name, start):
        k = (kind, name)
        n = self.arities.get(k)
        if n is None:
            if not 0 <= kind < 4:
                raise ValueError('function kind %d at offset %d' % (kind, start))
            try:
                n = self.arities[k] = _arity(self.td, kind, name)
            except UnknownFunction as e:
                e.offset = start
                raise
        return n

    def parameter(self):
        kind, value = self.i32(), self.text()
        function = self.function(False) if self.flag() else None
        index = self.parameter() if self.flag() else None
        return Parameter(kind, value, function, index)

    def function(self, child):
        start = self.p
        kind = self.i32()
        branch = self.i32() if child else None
        name, enabled = self.text(), self.i32()
        params = [self.parameter() for _i in range(self.arity(kind, name, start))]
        children = [self.function(True) for _i in range(self.count())] if self.version >= 7 else []
        return Function(kind, name, enabled, params, branch, children)

    def category(self, new):
        c = Category(self.i32(), self.text())
        if self.version >= 7:
            c.is_comment = self.i32()
        if new:
            c.expanded, c.parent_id = self.i32(), self.i32()
        return c

    def variable(self, new):
        v = Variable(self.text(), self.text())
        v.unknown, v.is_array = self.i32(), self.i32()
        if self.version >= 7:
            v.array_size = self.i32()
        v.initialized, v.initial_value = self.i32(), self.text()
        if new:
            v.id, v.parent_id = self.i32(), self.i32()
        return v

    def trigger(self, new):
        t = Trigger(self.text(), self.text())
        if self.version >= 7:
            t.is_comment = self.i32()
        if new:
            t.id = self.i32()
        t.enabled, t.is_text, t.initially_off, t.run_on_init, t.category_id = (self.i32() for _i in range(5))
        t.functions = [self.function(False) for _i in range(self.count())]
        return t

    def classic(self, mt):
        mt.categories = [self.category(False) for _i in range(self.count())]
        mt.game_version = self.i32()
        mt.variables = [self.variable(False) for _i in range(self.count())]
        mt.triggers = [self.trigger(False) for _i in range(self.count())]

    def new(self, mt):
        mt.deleted = {}
        for c in CLASSIFIERS:
            counter = self.i32()
            mt.deleted[c] = (counter, [self.i32() for _i in range(self.count())])
        mt.game_version = self.i32()
        mt.variables = [self.variable(True) for _i in range(self.count())]
        by_id = {}
        for v in mt.variables:
            by_id.setdefault(v.id, v)
        mt.elements = []
        for _i in range(self.count()):
            c = self.i32()
            if c in (ROOT, LIBRARY, CATEGORY):
                item = self.category(True)
                if c == CATEGORY:
                    mt.categories.append(item)
            elif c in (GUI, COMMENT, SCRIPT):
                item = self.trigger(True)
                mt.triggers.append(item)
            elif c == VARIABLE_ITEM:
                vid, name, parent = self.i32(), self.text(), self.i32()
                item = by_id.get(vid)
                if item is None or item.name != name or item.parent_id != parent:
                    item = Variable(name, '', id=vid, parent_id=parent)
            else:
                raise ValueError('tree item of classifier %d at offset %d' % (c, self.p - 4))
            mt.elements.append((c, item))


def read_wtg(data, td, script_fallback=False):
    if isinstance(td, dict):
        td = Arities(td)
    if script_fallback:
        import triggerdata
        td = triggerdata.ScriptFallback(td)
    r = _Reader(data, td)
    if r.b[:4] != b'WTG!':
        raise ValueError('not a wtg (no WTG! signature)')
    r.p = 4
    mt = MapTriggers()
    v = r.i32()
    if v == _NEW_I32:
        mt.sub_version, v = NEW_FORMAT, r.i32()
    if v not in (4, 7):
        raise ValueError('wtg version %d' % v)
    mt.version = r.version = v
    try:
        (r.new if mt.sub_version else r.classic)(mt)
    except RecursionError:
        raise ValueError('functions nested too deep at offset %d' % r.p) from None
    if r.p != len(r.b):
        raise ValueError('%d bytes left after the last item (offset %d)' % (len(r.b) - r.p, r.p))
    return mt


class _Writer(object):
    def __init__(self, td, version):
        self.out, self.td, self.version = [], td, version
        self.arities = {}

    def i32(self, v):
        self.out.append(_I32.pack(v))

    def text(self, s):
        b = s.encode('utf-8', 'surrogateescape')
        if b'\0' in b:
            raise ValueError('NUL inside the string %r' % s[:60])
        self.out.append(b + b'\0')

    def sized(self, s):
        if s is None:
            self.i32(0)
        else:
            b = s.encode('utf-8', 'surrogateescape')
            self.i32(len(b) + 1)
            self.out.append(b + b'\0')

    def parameter(self, p):
        self.i32(p.kind)
        self.text(p.value)
        self.i32(0 if p.function is None else 1)
        if p.function is not None:
            self.function(p.function, False)
        self.i32(0 if p.index is None else 1)
        if p.index is not None:
            self.parameter(p.index)

    def function(self, f, child):
        if (f.branch is not None) != child:
            raise ValueError('%s: %s' % (f.name, 'a child needs a branch' if child else 'only children have a branch'))
        if self.td is not None:
            k = (f.kind, f.name)
            if k not in self.arities:
                if not 0 <= f.kind < 4:
                    raise ValueError('%s: function kind %d' % (f.name, f.kind))
                self.arities[k] = _arity(self.td, f.kind, f.name)
            if len(f.params) != self.arities[k]:
                raise ValueError('%s takes %d parameters, the model has %d' % (f.name, self.arities[k], len(f.params)))
        self.i32(f.kind)
        if child:
            self.i32(f.branch)
        self.text(f.name)
        self.i32(f.enabled)
        for p in f.params:
            self.parameter(p)
        if self.version >= 7:
            self.i32(len(f.children))
            for c in f.children:
                self.function(c, True)
        elif f.children:
            raise ValueError('%s: the version %d layout has no child functions' % (f.name, self.version))

    def category(self, c, new):
        self.i32(c.id)
        self.text(c.name)
        if self.version >= 7:
            self.i32(c.is_comment)
        if new:
            self.i32(c.expanded)
            self.i32(c.parent_id)

    def variable(self, v, new):
        self.text(v.name)
        self.text(v.type)
        self.i32(v.unknown)
        self.i32(v.is_array)
        if self.version >= 7:
            self.i32(v.array_size)
        self.i32(v.initialized)
        self.text(v.initial_value)
        if new:
            self.i32(v.id)
            self.i32(v.parent_id)

    def trigger(self, t, new):
        self.text(t.name)
        self.text(t.description)
        if self.version >= 7:
            self.i32(t.is_comment)
        if new:
            self.i32(t.id)
        for v in (t.enabled, t.is_text, t.initially_off, t.run_on_init, t.category_id):
            self.i32(v)
        self.i32(len(t.functions))
        for f in t.functions:
            self.function(f, False)


def _same_items(a, b):
    return len(a) == len(b) and all(x is y for x, y in zip(a, b))


def write_wtg(mt, td=None, new_format=False):
    if new_format:
        if mt.sub_version is None or mt.elements is None or mt.deleted is None:
            raise ValueError('the 1.31 layout needs the ids, the tree and the counters of a 1.31 model')
        if not (_same_items([i for c, i in mt.elements if c == CATEGORY], mt.categories) and
                _same_items([i for c, i in mt.elements if c in (GUI, COMMENT, SCRIPT)], mt.triggers)):
            raise ValueError('the 1.31 tree (elements) does not hold the categories and triggers of the model')
    elif mt.sub_version is not None:
        mt = to_classic(mt)
    if mt.version not in (4, 7):
        raise ValueError('wtg version %r' % mt.version)
    if mt.game_version not in (1, 2):
        raise ValueError('game version %r: 1 (RoC) or 2 (TFT); the editor does not read 0' % mt.game_version)
    if isinstance(td, dict):
        td = Arities(td)
    w = _Writer(td, mt.version)
    w.out.append(b'WTG!')
    if new_format:
        w.i32(_NEW_I32)
        w.i32(mt.version)
        for c in CLASSIFIERS:
            counter, ids = mt.deleted.get(c, (0, []))
            w.i32(counter)
            w.i32(len(ids))
            for i in ids:
                w.i32(i)
        w.i32(mt.game_version)
        w.i32(len(mt.variables))
        for v in mt.variables:
            w.variable(v, True)
        w.i32(len(mt.elements))
        for c, item in mt.elements:
            w.i32(c)
            if c in (ROOT, LIBRARY, CATEGORY):
                w.category(item, True)
            elif c in (GUI, COMMENT, SCRIPT):
                w.trigger(item, True)
            elif c == VARIABLE_ITEM:
                w.i32(item.id)
                w.text(item.name)
                w.i32(item.parent_id)
            else:
                raise ValueError('tree item of classifier %r' % c)
    else:
        w.i32(mt.version)
        w.i32(len(mt.categories))
        for c in mt.categories:
            w.category(c, False)
        w.i32(mt.game_version)
        w.i32(len(mt.variables))
        for v in mt.variables:
            w.variable(v, False)
        w.i32(len(mt.triggers))
        for t in mt.triggers:
            w.trigger(t, False)
    return b''.join(w.out)


def _sized(r):
    n = r.i32()
    if n == 0:
        return None
    if n < 0 or n > len(r.b) - r.p or r.b[r.p + n - 1] != 0:
        raise ValueError('bad text of size %d at offset %d' % (n, r.p - 4))
    s = r.b[r.p:r.p + n - 1].decode('utf-8', 'surrogateescape')
    r.p += n
    return s


def read_wct(data):
    r = _Reader(data, None)
    ct = CustomText()
    v = r.i32()
    if v == _NEW_I32:
        ct.is_new_format, v = True, r.i32()
    if v not in (0, 1):
        raise ValueError('wct version %d' % v)
    ct.version = v
    if v >= 1:
        ct.comment = r.text()
        ct.header = _sized(r)
    if ct.is_new_format:
        while r.p < len(r.b):
            ct.texts.append(_sized(r))
    else:
        ct.texts = [_sized(r) for _i in range(r.count())]
    if r.p != len(r.b):
        raise ValueError('%d bytes left after the last text (offset %d)' % (len(r.b) - r.p, r.p))
    return ct


def write_wct(ct):
    w = _Writer(None, 7)
    if ct.is_new_format:
        w.i32(_NEW_I32)
    w.i32(ct.version)
    if ct.version >= 1:
        w.text(ct.comment)
        w.sized(ct.header)
    elif ct.comment or ct.header is not None:
        raise ValueError('a version 0 wct has no comment and no custom script')
    if not ct.is_new_format:
        w.i32(len(ct.texts))
    for t in ct.texts:
        w.sized(t)
    return b''.join(w.out)


def tree(mt):
    stack, seen, out = [], {}, []
    at = {}
    for c, item in mt.elements:
        pid = item.parent_id
        parent = None
        where = at.get(pid)
        if where:
            k = where[-1]
            parent = stack[k]
            for gone in stack[k + 1:]:
                at[gone.id].pop()
            del stack[k + 1:]
        else:
            parent = seen.get(pid)
        out.append((c, item, parent))
        if c in (ROOT, LIBRARY, CATEGORY):
            at.setdefault(item.id, []).append(len(stack))
            stack.append(item)
            seen[item.id] = item
    return out


def _clone_function(f):
    return Function(f.kind, f.name, f.enabled, [_clone_parameter(p) for p in f.params], f.branch,
                    [_clone_function(c) for c in f.children])


def _clone_parameter(p):
    return Parameter(p.kind, p.value, None if p.function is None else _clone_function(p.function),
                     None if p.index is None else _clone_parameter(p.index))


def _clone_trigger(t, category_id, tid):
    return Trigger(t.name, t.description, t.is_comment, t.enabled, t.is_text, t.initially_off, t.run_on_init,
                   category_id, [_clone_function(f) for f in t.functions], tid)


def to_classic(mt):
    out = MapTriggers(mt.version, None, mt.game_version)
    if mt.sub_version is None:
        out.categories = [replace(c) for c in mt.categories]
        out.variables = [replace(v) for v in mt.variables]
        out.triggers = [_clone_trigger(t, t.category_id, t.id) for t in mt.triggers]
        return out
    new_id, parent_of, pending, root_name, extra = {}, {}, [], 'Triggers', None
    for c, item, parent in tree(mt):
        if c == ROOT:
            root_name = item.name or root_name
        if c in (ROOT, LIBRARY, CATEGORY):
            parent_of[id(item)] = parent
        if c == CATEGORY:
            new_id[id(item)] = len(out.categories)
            out.categories.append(Category(len(out.categories), item.name, item.is_comment))
        elif c in (GUI, COMMENT, SCRIPT):
            pending.append((item, parent))
    for t, p in pending:
        while p is not None and id(p) not in new_id:
            p = parent_of.get(id(p))
        if p is None:
            if extra is None:
                extra = Category(len(out.categories), root_name)
                out.categories.append(extra)
            cid = extra.id
        else:
            cid = new_id[id(p)]
        out.triggers.append(_clone_trigger(t, cid, None))
    out.variables = [replace(v, id=None, parent_id=None) for v in mt.variables]
    return out


class Arities(object):
    def __init__(self, table, multiple=None):
        self.table, self.multiple = table, multiple or {}

    def arity(self, kind, name):
        try:
            return self.table[kind][name]
        except KeyError:
            raise UnknownFunction(name, kind) from None

