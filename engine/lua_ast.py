# Parses Lua 5.3 into a syntax tree that keeps every literal and comment.
import os
import re
import sys


KEYWORDS = frozenset(('and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for', 'function', 'goto', 'if', 'in',
                      'local', 'nil', 'not', 'or', 'repeat', 'return', 'then', 'true', 'until', 'while'))
BINARY_PRIORITY = {'+': (10, 10), '-': (10, 10), '*': (11, 11), '%': (11, 11), '^': (14, 13), '/': (11, 11),
                   '//': (11, 11), '&': (6, 6), '|': (4, 4), '~': (5, 5), '<<': (7, 7), '>>': (7, 7),
                   '..': (9, 8), '==': (3, 3), '<': (3, 3), '<=': (3, 3), '~=': (3, 3), '>': (3, 3), '>=': (3, 3),
                   'and': (2, 2), 'or': (1, 1)}
UNARY_PRIORITY = 12
_UNARY = frozenset(('not', '-', '#', '~'))
_BLOCK_END = frozenset(('else', 'elseif', 'end', 'until', 'EOF'))
_LABEL_LAST = frozenset(('else', 'elseif', 'end', 'EOF'))
_LEVEL_LIMIT = 200
_LEVEL_BASE = 1
_MAX_LOCALS = 200
_MAX_UPVALUES = 255
_RECURSION = 20000


class LuaSyntaxError(Exception):
    def __init__(self, line, message):
        super().__init__(line, message)
        self.line = line
        self.message = message

    def __str__(self):
        return 'line %d: %s' % (self.line, self.message)


class Comment:
    __slots__ = ('text', 'line')

    def __init__(self, text, line=0):
        self.text = text
        self.line = line

    @property
    def value(self):
        body = self.text[2:]
        m = re.match(r'\[(=*)\[', body)
        return body[m.end():len(body) - len(m.group(1)) - 2] if m else body

    def __repr__(self):
        return 'Comment(%r)' % self.text


class Block(list):
    __slots__ = ('end_comments',)

    def __init__(self, stmts=()):
        list.__init__(self, stmts)
        self.end_comments = ()


class Node:
    __slots__ = ('line',)

    def __repr__(self):
        return '%s(%s)' % (type(self).__name__, ', '.join(repr(getattr(self, f)) for f in type(self).__slots__))


class Stmt(Node):
    __slots__ = ('comment', 'leading_comments', 'inner_comments', 'span')


def _stmt(node, line):
    node.line = line
    node.comment = None
    node.leading_comments = ()
    node.inner_comments = ()
    node.span = None


class LocalStmt(Stmt):
    __slots__ = ('names', 'attribs', 'values')

    def __init__(self, names, attribs, values, line=0):
        self.names, self.attribs, self.values = names, attribs, values
        _stmt(self, line)


class AssignStmt(Stmt):
    __slots__ = ('targets', 'values')

    def __init__(self, targets, values, line=0):
        self.targets, self.values = targets, values
        _stmt(self, line)


class CallStmt(Stmt):
    __slots__ = ('call',)

    def __init__(self, call, line=0):
        self.call = call
        _stmt(self, line)


class FunctionStmt(Stmt):
    __slots__ = ('name', 'is_local', 'params', 'is_vararg', 'body')

    def __init__(self, name, is_local, params, is_vararg, body, line=0):
        self.name, self.is_local, self.params, self.is_vararg, self.body = name, is_local, params, is_vararg, body
        _stmt(self, line)


class IfStmt(Stmt):
    __slots__ = ('branches',)

    def __init__(self, branches, line=0):
        self.branches = branches
        _stmt(self, line)


class WhileStmt(Stmt):
    __slots__ = ('cond', 'body')

    def __init__(self, cond, body, line=0):
        self.cond, self.body = cond, body
        _stmt(self, line)


class NumericForStmt(Stmt):
    __slots__ = ('var', 'start', 'stop', 'step', 'body')

    def __init__(self, var, start, stop, step, body, line=0):
        self.var, self.start, self.stop, self.step, self.body = var, start, stop, step, body
        _stmt(self, line)


class GenericForStmt(Stmt):
    __slots__ = ('names', 'exprs', 'body')

    def __init__(self, names, exprs, body, line=0):
        self.names, self.exprs, self.body = names, exprs, body
        _stmt(self, line)


class RepeatStmt(Stmt):
    __slots__ = ('body', 'cond')

    def __init__(self, body, cond, line=0):
        self.body, self.cond = body, cond
        _stmt(self, line)


class DoStmt(Stmt):
    __slots__ = ('body',)

    def __init__(self, body, line=0):
        self.body = body
        _stmt(self, line)


class ReturnStmt(Stmt):
    __slots__ = ('values',)

    def __init__(self, values, line=0):
        self.values = values
        _stmt(self, line)


class BreakStmt(Stmt):
    __slots__ = ()

    def __init__(self, line=0):
        _stmt(self, line)


class GotoStmt(Stmt):
    __slots__ = ('label',)

    def __init__(self, label, line=0):
        self.label = label
        _stmt(self, line)


class LabelStmt(Stmt):
    __slots__ = ('name',)

    def __init__(self, name, line=0):
        self.name = name
        _stmt(self, line)


class Name(Node):
    __slots__ = ('name',)

    def __init__(self, name, line=0):
        self.name, self.line = name, line


class Index(Node):
    __slots__ = ('base', 'key', 'dot')

    def __init__(self, base, key, dot=False, line=0):
        self.base, self.key, self.dot, self.line = base, key, dot, line


class Call(Node):
    __slots__ = ('func', 'args', 'method')

    def __init__(self, func, args, method=None, line=0):
        self.func, self.args, self.method, self.line = func, args, method, line


class FunctionExpr(Node):
    __slots__ = ('params', 'is_vararg', 'body')

    def __init__(self, params, is_vararg, body, line=0):
        self.params, self.is_vararg, self.body, self.line = params, is_vararg, body, line


class Literal(Node):
    __slots__ = ('kind', 'text', 'value')

    def __init__(self, kind, text, value, line=0):
        self.kind, self.text, self.value, self.line = kind, text, value, line


class Unary(Node):
    __slots__ = ('op', 'operand')

    def __init__(self, op, operand, line=0):
        self.op, self.operand, self.line = op, operand, line


class Binary(Node):
    __slots__ = ('op', 'left', 'right')

    def __init__(self, op, left, right, line=0):
        self.op, self.left, self.right, self.line = op, left, right, line


class Paren(Node):
    __slots__ = ('inner',)

    def __init__(self, inner, line=0):
        self.inner, self.line = inner, line


class Table(Node):
    __slots__ = ('fields',)

    def __init__(self, fields, line=0):
        self.fields, self.line = fields, line


class Chunk:
    __slots__ = ('body', 'functions', 'comments')

    def __init__(self, body, functions, comments):
        self.body, self.functions, self.comments = body, functions, comments

    def __repr__(self):
        return 'Chunk(%d statements, %d functions, %d comments)' % (len(self.body), len(self.functions),
                                                                     len(self.comments))


_LONG_LEVELS = re.compile(r'\[(=*)\[')
_PIECES = {}


def _pieces(level):
    regex = _PIECES.get(level)
    if regex is None:
        long = '|'.join(r'\[%s\[[\s\S]*?\]%s\]' % ('=' * n, '=' * n) for n in range(level + 1))
        regex = _PIECES[level] = re.compile(
            r'[ \t\n\r\f\v]+'
            r'|[A-Za-z_][A-Za-z0-9_]*'
            r'|--(?:' + long + r'|\[=*\[)'
            r'|--[^\n\r]*'
            r'|' + long +
            r'|\[=*\[?'
            r'|0[xX](?:[pP][+-]?|[0-9a-fA-F.])*|(?:[0-9]|\.[0-9])(?:[eE][+-]?|[0-9a-fA-F.])*'
            r'''|"[^"\\\n\r]*+(?:\\(?:z[ \t\n\r\f\v]*+|\r\n?|\n\r?|[\s\S])[^"\\\n\r]*+)*+"'''
            r'''|'[^'\\\n\r]*+(?:\\(?:z[ \t\n\r\f\v]*+|\r\n?|\n\r?|[\s\S])[^'\\\n\r]*+)*+\''''
            r'|\.\.\.|\.\.|==|~=|<=|>=|<<|>>|//|::|[-+*/%^#&~|<>=(){}\[\];:,.]'
            r'|[\s\S]')
    return regex


_STRING_PREFIX = re.compile(r'''(["'])(?:(?!\1)[^\\\n\r]|\\(?:z[ \t\n\r\f\v]*|\r\n?|\n\r?|[\s\S]))*''')
_NUMBER_OK = re.compile(r'(?:0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)(?:[pP][+-]?[0-9]+)?'
                        r'|(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\Z')
_OPERATORS = frozenset(('+', '-', '*', '/', '//', '%', '^', '#', '&', '~', '|', '<<', '>>', '==', '~=', '<=', '>=',
                        '<', '>', '=', '(', ')', '{', '}', '[', ']', '::', ';', ':', ',', '.', '..', '...'))
_BLANKS = frozenset(' \t\n\r\f\v')
_NAME_START = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_')
_OPENER = re.compile(r'\[=*\[')
_SIMPLE_ESCAPES = {'a': 7, 'b': 8, 'f': 12, 'n': 10, 'r': 13, 't': 9, 'v': 11, '\\': 92, '"': 34, "'": 39}
_HEX = frozenset('0123456789abcdefABCDEF')
_DIGITS = frozenset('0123456789')
_NEWLINES = re.compile(r'\r\n|\n\r|\r|\n')


def _nl_count(s):
    return s.count('\n') if '\r' not in s else len(_NEWLINES.findall(s))


def _utf8esc(x):
    if x < 0x80:
        return bytes((x,))
    out = []
    mfb = 0x3f
    while True:
        out.append(0x80 | (x & 0x3f))
        x >>= 6
        mfb >>= 1
        if x <= mfb:
            break
    out.append(((~mfb << 1) | x) & 0xff)
    return bytes(reversed(out))


def _unescape(body):
    out = bytearray()
    n = len(body)
    pos = 0
    while True:
        i = body.find('\\', pos)
        if i < 0 or i + 1 >= n:
            break
        out += body[pos:i].encode('utf-8', 'surrogateescape')
        c = body[i + 1]
        j = i + 2
        if c in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[c])
        elif c == '\n' or c == '\r':
            out.append(10)
            if j < n and body[j] in '\n\r' and body[j] != c:
                j += 1
        elif c == 'x':
            for k in (i + 2, i + 3):
                if k >= n or body[k] not in _HEX:
                    return None, (k + 1, 'hexadecimal digit expected')
            out.append(int(body[i + 2:i + 4], 16))
            j = i + 4
        elif c == 'z':
            while j < n and body[j] in ' \t\n\r\f\v':
                j += 1
        elif c in _DIGITS:
            j = i + 1
            v = 0
            while j < i + 4 and j < n and body[j] in _DIGITS:
                v = v * 10 + ord(body[j]) - 48
                j += 1
            if v > 255:
                return None, (j + 1, 'decimal escape too large')
            out.append(v)
        elif c == 'u':
            if body[j:j + 1] != '{':
                return None, (j + 1, "missing '{'")
            j += 1
            if j >= n or body[j] not in _HEX:
                return None, (j + 1, 'hexadecimal digit expected')
            v = 0
            while j < n and body[j] in _HEX:
                v = v * 16 + int(body[j], 16)
                if v > 0x10FFFF:
                    return None, (j + 1, 'UTF-8 value too large')
                j += 1
            if body[j:j + 1] != '}':
                return None, (j + 1, "missing '}'")
            out += _utf8esc(v)
            j += 1
        else:
            return None, (j, 'invalid escape sequence')
        pos = j
    out += body[pos:].encode('utf-8', 'surrogateescape')
    return out.decode('utf-8', 'surrogateescape'), None


def _long_value(text):
    level = text.index('[', 1) - 1
    body = text[level + 2:len(text) - level - 2]
    m = _NEWLINES.match(body)
    if m:
        body = body[m.end():]
    return _NEWLINES.sub('\n', body) if '\r' in body else body


def _number_value(s):
    if s[:2] in ('0x', '0X'):
        if '.' in s or 'p' in s or 'P' in s:
            try:
                return float.fromhex(s)
            except OverflowError:
                return float('inf')
        v = int(s[2:], 16) & 0xFFFFFFFFFFFFFFFF
        return v - (1 << 64) if v >= 1 << 63 else v
    if s.isdigit():
        digits = s.lstrip('0') or '0'
        if len(digits) <= 19 and int(digits) < 1 << 63:
            return int(digits)
    return float(s)


def _near_text(s):
    return "'%s'" % (s if len(s) <= 40 else s[:37] + '...')


def _escape_error(s, bad, line):
    part = s[:bad[0] + 1]
    return line + _nl_count(part), '%s near %s' % (bad[1], _near_text(part))


def _lex(text):
    if len(text) >= _LEX_NATIVE_MIN:
        out = _lex_native(text)
        if out is not None:
            return out
    return _lex_loop(text)


_LEX_NATIVE_MIN = 4096
_LEX_KINDS = ('NAME', 'NUMBER', 'STRING', 'EOF')
_LEX_FN = [None]
_LEX_SEP = '\x00'


def _lex_native(text):
    if _LEX_FN[0] is None:
        _LEX_FN[0] = False
        dll = _native()
        if dll and hasattr(dll, 'lua_lex_tokens'):
            import ctypes
            f = dll.lua_lex_tokens
            f.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p),
                          ctypes.POINTER(ctypes.c_size_t)]
            f.restype = ctypes.c_int
            _LEX_FN[0] = True
    if not _LEX_FN[0]:
        return None
    if sys.byteorder != 'little' or _LEX_SEP in text:
        return None
    try:
        data = text.encode('utf-8', 'surrogatepass')
    except UnicodeEncodeError:
        return None
    r, buf = _call_native('lua_lex_tokens', data)
    if r != 0:
        return None
    import struct
    ntok, ncom, nesc = struct.unpack_from('<3I', buf)
    end = 12 + 4 * (3 * ntok + 3 * ncom + nesc)
    v = memoryview(buf)[12:end].cast('I').tolist()
    n3 = 3 * ntok
    names = _LEX_KINDS + _NATIVE_KINDS[4:]
    kinds = list(map(names.__getitem__, v[0:n3:3]))
    lines = v[1:n3:3]
    offs = v[2:n3:3]
    comments, ctok = [], []
    p = end
    for k in range(n3, n3 + 3 * ncom, 3):
        n = v[k + 2]
        comments.append(Comment(buf[p:p + n].decode('utf-8', 'surrogatepass'), v[k]))
        ctok.append(v[k + 1])
        p += n
    texts = buf[p:].decode('utf-8', 'surrogatepass').split(_LEX_SEP)
    if len(texts) != ntok:
        return None
    strval = {}
    for j in v[n3 + 3 * ncom:]:
        value, bad = _unescape(texts[j][1:-1])
        if bad is not None:
            return None
        strval[j] = value
    return kinds, texts, lines, offs, comments, ctok, strval


def _lex_loop(text):
    kinds, texts, lines, offs = [], [], [], []
    comments, ctok, strval = [], [], {}
    keywords, operators, blanks, name_start = KEYWORDS, _OPERATORS, _BLANKS, _NAME_START
    line = 1
    pos = 0
    error = None
    levels = _LONG_LEVELS.findall(text)
    for s in _pieces(max(map(len, levels)) if levels else 0).findall(text):
        c = s[0]
        if c in blanks:
            if '\n' in s or '\r' in s:
                line += _nl_count(s)
            pos += len(s)
            continue
        if c in name_start:
            kind = s if s in keywords else 'NAME'
        elif s in operators:
            kind = s
        elif c == '-':
            if s[-1] == '[' and _OPENER.fullmatch(s, 2):
                error = (line + _nl_count(text[pos:]),
                         'unfinished long comment (starting at line %d) near <eof>' % line)
                break
            comments.append(Comment(s, line))
            ctok.append(len(kinds))
            if '\n' in s or '\r' in s:
                line += _nl_count(s)
            pos += len(s)
            continue
        elif c in _DIGITS or c == '.':
            if _NUMBER_OK.match(s) is None:
                error = (line, 'malformed number near ' + _near_text(s))
                break
            kind = 'NUMBER'
        elif c == '"' or c == "'":
            if len(s) == 1:
                part = _STRING_PREFIX.match(text, pos).group()
                bad = _unescape(part[1:])[1] if '\\' in part else None
                if bad is not None:
                    error = _escape_error(part, bad, line)
                elif text[pos + len(part):] in ('', '\\'):
                    error = (line + _nl_count(part), 'unfinished string near <eof>')
                else:
                    error = (line + _nl_count(part), 'unfinished string near ' + _near_text(part))
                break
            kind = 'STRING'
            if '\\' in s:
                value, bad = _unescape(s[1:-1])
                if bad is not None:
                    error = _escape_error(s, bad, line)
                    break
                strval[len(kinds)] = value
        elif c == '[':
            if s[-1] == '[':
                error = (line + _nl_count(text[pos:]),
                         'unfinished long string (starting at line %d) near <eof>' % line)
                break
            if s[-1] == '=':
                error = (line, 'invalid long string delimiter near ' + _near_text(s))
                break
            kind = 'STRING'
        else:
            kind = 'CHAR'
        kinds.append(kind)
        texts.append(s)
        lines.append(line)
        offs.append(pos)
        pos += len(s)
        if kind == 'STRING' and ('\n' in s or '\r' in s):
            line += _nl_count(s)
    if error is not None:
        kinds.append('ERROR')
        texts.append(error[1])
        lines.append(error[0])
        offs.append(len(text))
        line = error[0]
    for _ in range(3):
        kinds.append('EOF')
        texts.append('')
        lines.append(line)
        offs.append(len(text))
    return kinds, texts, lines, offs, comments, ctok, strval


_GLOBAL = object()
_ENV_VAR = ['_ENV', None]
_HIDDEN_NUM = ('(for index)', '(for limit)', '(for step)')
_HIDDEN_GEN = ('(for generator)', '(for state)', '(for control)')


class _FuncState:
    __slots__ = ('parent', 'line', 'vararg', 'actvar', 'nactive', 'vars', 'upvals', 'blocks', 'labels', 'gotos')

    def __init__(self, parent, line, vararg):
        self.parent, self.line, self.vararg = parent, line, vararg
        self.actvar = []
        self.nactive = 0
        self.vars = {}
        self.upvals = {}
        self.blocks = []
        self.labels = []
        self.gotos = []


class _Parser:
    def __init__(self, text):
        (self.k, self.t, self.l, self.p, self.comments, self.ctok, self.strval) = _lex(text)
        self.i = 0
        self.ci = 0
        self.nc = len(self.comments)
        self.level = _LEVEL_BASE
        self.fs = None
        self.inner = []
        self.labels_pending = []
        self.stmts = {'if': self._if, 'while': self._while, 'do': self._do, 'for': self._for,
                      'repeat': self._repeat, 'function': self._function, 'local': self._local, '::': self._label,
                      'return': self._return, 'break': self._break, 'goto': self._goto}

    def chunk(self):
        fs = self.fs = _FuncState(None, 0, True)
        fs.upvals['_ENV'] = _ENV_VAR
        self._enterblock(False)
        body = self._statlist()
        if self.k[self.i] != 'EOF':
            self._error_expected('EOF')
        self._leaveblock()
        functions = {}
        for s in body:
            if type(s) is FunctionStmt:
                functions[s.name] = s
        return Chunk(body, functions, self.comments)

    def _end_line(self, i):
        line = self.l[i]
        if self.k[i] == 'STRING':
            s = self.t[i]
            if '\n' in s or '\r' in s:
                line += _nl_count(s)
        return line

    def _near(self):
        kind = self.k[self.i]
        if kind == 'EOF':
            return '<eof>'
        s = self.t[self.i]
        if kind == 'CHAR':
            b = s.encode('utf-8', 'surrogateescape')[0]
            return "'%s'" % s if 32 <= b < 127 else "'<\\%d>'" % b
        return _near_text(s)

    def _raise(self, message, near=True):
        i = self.i
        if self.k[i] == 'ERROR':
            raise LuaSyntaxError(self.l[i], self.t[i])
        if near:
            message += ' near ' + self._near()
        raise LuaSyntaxError(self._end_line(i), message)

    def _error(self, message):
        self._raise(message)

    def _semerror(self, message):
        self._raise(message, near=False)

    def _error_expected(self, what):
        self._raise('%s expected' % {'EOF': '<eof>', 'NAME': '<name>'}.get(what, "'%s'" % what))

    def _limit(self, what, limit, fs=None):
        fs = fs or self.fs
        where = 'main function' if fs.line == 0 else 'function at line %d' % fs.line
        self._raise('too many %s (limit is %d) in %s' % (what, limit, where))

    def _checknext(self, what):
        if self.k[self.i] != what:
            self._error_expected(what)
        self.i += 1

    def _check_match(self, what, who, line):
        if self.k[self.i] != what:
            if line == self._end_line(self.i):
                self._error_expected(what)
            self._raise("'%s' expected (to close '%s' at line %d)" % (what, who, line))
        self.i += 1

    def _checkname(self):
        i = self.i
        if self.k[i] != 'NAME':
            self._error_expected('NAME')
        self.i = i + 1
        return self.t[i]

    def _take(self, j):
        ci, ctok, n = self.ci, self.ctok, self.nc
        start = ci
        while ci < n and ctok[ci] <= j:
            ci += 1
        self.ci = ci
        return self.comments[start:ci]

    def _statlist(self):
        k = self.k
        ctok = self.ctok
        body = Block()
        outer = self.inner
        if self.ci < self.nc and ctok[self.ci] < self.i:
            outer.extend(self._take(self.i - 1))
        stmts = self.stmts
        pending = self.labels_pending
        while True:
            i = self.i
            kind = k[i]
            if pending and kind != ';' and kind != '::':
                self._close_labels(kind)
            if kind in _BLOCK_END:
                break
            depth = 1 + len(pending)
            if kind == ';':
                if self.level + depth > _LEVEL_LIMIT:
                    self._limit('C levels', _LEVEL_LIMIT)
                self.i = i + 1
                continue
            lead = self._take(i) if self.ci < self.nc and ctok[self.ci] <= i else ()
            self.inner = inner = []
            self.level += depth
            if self.level > _LEVEL_LIMIT:
                self._limit('C levels', _LEVEL_LIMIT)
            f = stmts.get(kind)
            stmt = f() if f is not None else self._exprstat()
            self.level -= depth
            last = self.i - 1
            if self.ci < self.nc:
                if ctok[self.ci] <= last:
                    inner.extend(self._take(last))
                if self.ci < self.nc:
                    j = self.i
                    while k[j] == ';':
                        j += 1
                    c = self.comments[self.ci]
                    if ctok[self.ci] <= j and c.line == self._end_line(last):
                        stmt.comment = c
                        self.ci += 1
            stmt.leading_comments = lead
            if inner:
                stmt.inner_comments = inner
            stmt.span = (self.p[i], self.p[last] + len(self.t[last]))
            body.append(stmt)
            if kind == 'return':
                break
        self.inner = outer
        if self.ci < self.nc and ctok[self.ci] <= self.i:
            body.end_comments = self._take(self.i)
        return body

    def _block(self):
        self._enterblock(False)
        body = self._statlist()
        self._leaveblock()
        return body

    def _enterblock(self, isloop):
        fs = self.fs
        fs.blocks.append((fs.nactive, isloop, len(fs.labels), len(fs.gotos)))

    def _leaveblock(self):
        fs = self.fs
        nact, isloop, firstlabel, firstgoto = fs.blocks[-1]
        if isloop:
            self._findgotos(fs, ('break', 0, fs.nactive))
        fs.blocks.pop()
        if fs.nactive > nact:
            actvar, names = fs.actvar, fs.vars
            for idx in range(fs.nactive - 1, nact - 1, -1):
                name = actvar[idx][0]
                stack = names[name]
                stack.pop()
                if not stack:
                    del names[name]
            del actvar[nact:]
            fs.nactive = nact
        del fs.labels[firstlabel:]
        gotos = fs.gotos
        if len(gotos) > firstgoto:
            if not fs.blocks:
                gt = gotos[firstgoto]
                if gt[0] == 'break':
                    self._semerror('<break> at line %d not inside a loop' % gt[1])
                self._semerror("no visible label '%s' for <goto> at line %d" % (gt[0], gt[1]))
            i = firstgoto
            while i < len(gotos):
                if gotos[i][2] > nact:
                    gotos[i][2] = nact
                if not self._findlabel(fs, i):
                    i += 1

    def _findlabel(self, fs, gi):
        name = fs.gotos[gi][0]
        for lb in fs.labels[fs.blocks[-1][2]:]:
            if lb[0] == name:
                self._closegoto(fs, gi, lb)
                return True
        return False

    def _findgotos(self, fs, lb):
        gotos = fs.gotos
        i = fs.blocks[-1][3]
        while i < len(gotos):
            if gotos[i][0] == lb[0]:
                self._closegoto(fs, i, lb)
            else:
                i += 1

    def _closegoto(self, fs, gi, lb):
        gt = fs.gotos[gi]
        if gt[2] < lb[2]:
            self._semerror("<goto %s> at line %d jumps into the scope of local '%s'"
                           % (gt[0], gt[1], fs.actvar[gt[2]][0]))
        del fs.gotos[gi]

    def _new_localvar(self, name, attrib=None):
        fs = self.fs
        if len(fs.actvar) >= _MAX_LOCALS:
            self._limit('local variables', _MAX_LOCALS)
        fs.actvar.append([name, attrib])

    def _adjustlocalvars(self, n):
        fs = self.fs
        names = fs.vars
        for idx in range(fs.nactive, fs.nactive + n):
            name = fs.actvar[idx][0]
            stack = names.get(name)
            if stack is None:
                names[name] = [idx]
            else:
                stack.append(idx)
        fs.nactive += n

    def _resolve(self, fs, name):
        stack = fs.vars.get(name)
        if stack:
            return fs.actvar[stack[-1]]
        var = fs.upvals.get(name)
        if var is not None:
            return var
        if fs.parent is None:
            return _GLOBAL
        var = self._resolve(fs.parent, name)
        if var is _GLOBAL:
            return _GLOBAL
        if len(fs.upvals) >= _MAX_UPVALUES:
            self._limit('upvalues', _MAX_UPVALUES, fs)
        fs.upvals[name] = var
        return var

    def _singlevar(self, name):
        fs = self.fs
        if name not in fs.vars and self._resolve(fs, name) is _GLOBAL:
            self._resolve(fs, '_ENV')

    def _check_assignable(self, name):
        fs = self.fs
        stack = fs.vars.get(name)
        var = fs.actvar[stack[-1]] if stack else fs.upvals.get(name)
        if var is not None and var[1] is not None:
            self._semerror("attempt to assign to const variable '%s'" % name)

    def _if(self):
        k = self.k
        line = self.l[self.i]
        branches = []
        while True:
            self.i += 1
            cond = self._subexpr(0)
            self._checknext('then')
            branches.append((cond, self._block()))
            if k[self.i] != 'elseif':
                break
        if k[self.i] == 'else':
            self.i += 1
            branches.append((None, self._block()))
        self._check_match('end', 'if', line)
        return IfStmt(branches, line)

    def _while(self):
        line = self.l[self.i]
        self.i += 1
        cond = self._subexpr(0)
        self._enterblock(True)
        self._checknext('do')
        body = self._block()
        self._check_match('end', 'while', line)
        self._leaveblock()
        return WhileStmt(cond, body, line)

    def _do(self):
        line = self.l[self.i]
        self.i += 1
        body = self._block()
        self._check_match('end', 'do', line)
        return DoStmt(body, line)

    def _repeat(self):
        line = self.l[self.i]
        self.i += 1
        self._enterblock(True)
        self._enterblock(False)
        body = self._statlist()
        self._check_match('until', 'repeat', line)
        cond = self._subexpr(0)
        self._leaveblock()
        self._leaveblock()
        return RepeatStmt(body, cond, line)

    def _for(self):
        k = self.k
        line = self.l[self.i]
        self.i += 1
        self._enterblock(True)
        name = self._checkname()
        kind = k[self.i]
        if kind == '=':
            for hidden in _HIDDEN_NUM:
                self._new_localvar(hidden)
            self._new_localvar(name)
            self.i += 1
            start = self._subexpr(0)
            self._checknext(',')
            stop = self._subexpr(0)
            step = None
            if k[self.i] == ',':
                self.i += 1
                step = self._subexpr(0)
            stmt = NumericForStmt(name, start, stop, step, self._forbody(1), line)
        elif kind == ',' or kind == 'in':
            for hidden in _HIDDEN_GEN:
                self._new_localvar(hidden)
            self._new_localvar(name)
            names = [name]
            while k[self.i] == ',':
                self.i += 1
                names.append(self._checkname())
                self._new_localvar(names[-1])
            self._checknext('in')
            exprs = self._explist()
            stmt = GenericForStmt(names, exprs, self._forbody(len(names)), line)
        else:
            self._error("'=' or 'in' expected")
        self._check_match('end', 'for', line)
        self._leaveblock()
        return stmt

    def _forbody(self, nvars):
        self._adjustlocalvars(3)
        self._checknext('do')
        self._enterblock(False)
        self._adjustlocalvars(nvars)
        body = self._block()
        self._leaveblock()
        return body

    def _function(self):
        k = self.k
        line = self.l[self.i]
        self.i += 1
        name = self._checkname()
        self._singlevar(name)
        full = name
        is_method = False
        while k[self.i] == '.':
            self.i += 1
            full += '.' + self._checkname()
        if k[self.i] == ':':
            self.i += 1
            full += ':' + self._checkname()
            is_method = True
        params, vararg, body = self._funcbody(line, is_method)
        if full == name:
            self._check_assignable(name)
        return FunctionStmt(full, False, params, vararg, body, line)

    def _local(self):
        k = self.k
        line = self.l[self.i]
        self.i += 1
        if k[self.i] == 'function':
            self.i += 1
            name = self._checkname()
            self._new_localvar(name)
            self._adjustlocalvars(1)
            params, vararg, body = self._funcbody(self.l[self.i], False)
            return FunctionStmt(name, True, params, vararg, body, line)
        names, attribs = [], []
        close = False
        while True:
            name = self._checkname()
            self._new_localvar(name)
            attrib = None
            if k[self.i] == '<':
                self.i += 1
                attrib = self._checkname()
                self._checknext('>')
                if attrib != 'const' and attrib != 'close':
                    self._semerror("unknown attribute '%s'" % attrib)
                if attrib == 'close':
                    if close:
                        self._semerror('multiple to-be-closed variables in local list')
                    close = True
                self.fs.actvar[-1][1] = attrib
            names.append(name)
            attribs.append(attrib)
            if k[self.i] != ',':
                break
            self.i += 1
        values = []
        if k[self.i] == '=':
            self.i += 1
            values = self._explist()
        self._adjustlocalvars(len(names))
        return LocalStmt(names, attribs, values, line)

    def _label(self):
        line = self.l[self.i]
        self.i += 1
        name = self._checkname()
        fs = self.fs
        for lb in fs.labels[fs.blocks[-1][2]:]:
            if lb[0] == name:
                self._semerror("label '%s' already defined on line %d" % (name, lb[1]))
        self._checknext('::')
        lb = [name, line, fs.nactive]
        fs.labels.append(lb)
        self.labels_pending.append(lb)
        return LabelStmt(name, line)

    def _close_labels(self, kind):
        fs = self.fs
        pending = self.labels_pending
        while pending:
            lb = pending.pop()
            if kind in _LABEL_LAST:
                lb[2] = fs.blocks[-1][0]
            self._findgotos(fs, lb)

    def _return(self):
        k = self.k
        line = self.l[self.i]
        self.i += 1
        kind = k[self.i]
        values = [] if kind in _BLOCK_END or kind == ';' else self._explist()
        if k[self.i] == ';':
            self.i += 1
        return ReturnStmt(values, line)

    def _break(self):
        line = self.l[self.i]
        self.i += 1
        fs = self.fs
        fs.gotos.append(['break', line, fs.nactive])
        return BreakStmt(line)

    def _goto(self):
        line = self.l[self.i]
        self.i += 1
        name = self._checkname()
        fs = self.fs
        fs.gotos.append([name, line, fs.nactive])
        self._findlabel(fs, len(fs.gotos) - 1)
        return GotoStmt(name, line)

    def _exprstat(self):
        k = self.k
        line = self.l[self.i]
        e = self._suffixedexp()
        kind = k[self.i]
        if kind == '=' or kind == ',':
            targets = [e]
            self._check_target(e)
            while k[self.i] == ',':
                self.i += 1
                e = self._suffixedexp()
                if len(targets) + self.level > _LEVEL_LIMIT:
                    self._limit('C levels', _LEVEL_LIMIT)
                targets.append(e)
                self._check_target(e)
            self._checknext('=')
            return AssignStmt(targets, self._explist(), line)
        if type(e) is not Call:
            self._error('syntax error')
        return CallStmt(e, line)

    def _check_target(self, e):
        t = type(e)
        if t is Name:
            self._check_assignable(e.name)
        elif t is not Index:
            self._error('syntax error')

    def _explist(self):
        k = self.k
        values = [self._subexpr(0)]
        while k[self.i] == ',':
            self.i += 1
            values.append(self._subexpr(0))
        return values

    def _subexpr(self, limit):
        self.level += 1
        if self.level > _LEVEL_LIMIT:
            self._limit('C levels', _LEVEL_LIMIT)
        k = self.k
        i = self.i
        kind = k[i]
        if kind in _UNARY:
            self.i = i + 1
            e = Unary(kind, self._subexpr(UNARY_PRIORITY), self.l[i])
        else:
            e = self._simpleexp()
        priority = BINARY_PRIORITY
        while True:
            op = k[self.i]
            p = priority.get(op)
            if p is None or p[0] <= limit:
                break
            self.i += 1
            e = Binary(op, e, self._subexpr(p[1]), e.line)
        self.level -= 1
        return e

    def _simpleexp(self):
        i = self.i
        kind = self.k[i]
        if kind == 'NAME' or kind == '(':
            return self._suffixedexp()
        if kind == 'NUMBER':
            self.i = i + 1
            s = self.t[i]
            return Literal('number', s, _number_value(s), self.l[i])
        if kind == 'STRING':
            self.i = i + 1
            return self._string(i)
        if kind == 'nil':
            self.i = i + 1
            return Literal('nil', 'nil', None, self.l[i])
        if kind == 'true' or kind == 'false':
            self.i = i + 1
            return Literal('boolean', kind, kind == 'true', self.l[i])
        if kind == '...':
            if not self.fs.vararg:
                self._error("cannot use '...' outside a vararg function")
            self.i = i + 1
            return Literal('vararg', '...', None, self.l[i])
        if kind == '{':
            return self._table()
        if kind == 'function':
            self.i = i + 1
            params, vararg, body = self._funcbody(self.l[i + 1], False)
            return FunctionExpr(params, vararg, body, self.l[i])
        return self._suffixedexp()

    def _string(self, i):
        s = self.t[i]
        value = self.strval.get(i)
        if value is None:
            value = _long_value(s) if s[0] == '[' else s[1:-1]
        return Literal('string', s, value, self.l[i])

    def _suffixedexp(self):
        k = self.k
        i = self.i
        kind = k[i]
        line = self.l[i]
        if kind == 'NAME':
            name = self.t[i]
            self.i = i + 1
            self._singlevar(name)
            e = Name(name, line)
        elif kind == '(':
            self.i = i + 1
            inner = self._subexpr(0)
            self._check_match(')', '(', line)
            e = Paren(inner, line)
        else:
            self._error('unexpected symbol')
        while True:
            kind = k[self.i]
            if kind == '.':
                self.i += 1
                j = self.i
                name = self._checkname()
                e = Index(e, Literal('string', '"%s"' % name, name, self.l[j]), True, line)
            elif kind == '[':
                self.i += 1
                key = self._subexpr(0)
                self._checknext(']')
                e = Index(e, key, False, line)
            elif kind == ':':
                self.i += 1
                name = self._checkname()
                e = Call(e, self._funcargs(line), name, line)
            elif kind == '(' or kind == 'STRING' or kind == '{':
                e = Call(e, self._funcargs(line), None, line)
            else:
                return e

    def _funcargs(self, line):
        k = self.k
        i = self.i
        kind = k[i]
        if kind == '(':
            self.i = i + 1
            args = [] if k[i + 1] == ')' else self._explist()
            self._check_match(')', '(', line)
            return args
        if kind == 'STRING':
            self.i = i + 1
            return [self._string(i)]
        if kind == '{':
            return [self._table()]
        self._error('function arguments expected')

    def _table(self):
        k = self.k
        line = self.l[self.i]
        self.i += 1
        fields = []
        while k[self.i] != '}':
            kind = k[self.i]
            if kind == 'NAME' and k[self.i + 1] == '=':
                name = self.t[self.i]
                self.i += 2
                fields.append((name, self._subexpr(0)))
            elif kind == '[':
                self.i += 1
                key = self._subexpr(0)
                self._checknext(']')
                self._checknext('=')
                fields.append((key, self._subexpr(0)))
            else:
                fields.append((None, self._subexpr(0)))
            kind = k[self.i]
            if kind != ',' and kind != ';':
                break
            self.i += 1
        self._check_match('}', '{', line)
        return Table(fields, line)

    def _funcbody(self, line, is_method):
        k = self.k
        fs = self.fs = _FuncState(self.fs, line, False)
        self._enterblock(False)
        if is_method:
            self._new_localvar('self')
            self._adjustlocalvars(1)
        self._checknext('(')
        params = []
        vararg = False
        if k[self.i] != ')':
            while True:
                kind = k[self.i]
                if kind == 'NAME':
                    params.append(self.t[self.i])
                    self.i += 1
                    self._new_localvar(params[-1])
                elif kind == '...':
                    self.i += 1
                    vararg = True
                else:
                    self._error("<name> or '...' expected")
                if vararg or k[self.i] != ',':
                    break
                self.i += 1
        self._adjustlocalvars(len(params))
        fs.vararg = vararg
        self._checknext(')')
        body = self._statlist()
        self._check_match('end', 'function', line)
        self._leaveblock()
        self.fs = fs.parent
        return params, vararg, body


def parse(text):
    if len(text) >= _NATIVE_MIN:
        chunk = _parse_native(text)
        if chunk is not None:
            return chunk
    return _parse_python(text)


_NATIVE = [None]
_NATIVE_MIN = 512
_NATIVE_KINDS = (None, None, None, None, 'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for', 'function',
                 'goto', 'if', 'in', 'local', 'nil', 'not', 'or', 'repeat', 'return', 'then', 'true', 'until', 'while',
                 '+', '-', '*', '/', '//', '%', '^', '#', '&', '~', '|', '<<', '>>', '==', '~=', '<=', '>=', '<', '>',
                 '=', '(', ')', '{', '}', '[', ']', '::', ';', ':', ',', '.', '..', '...')


def _native():
    if _NATIVE[0] is None:
        _NATIVE[0] = False
        if os.environ.get('JASS_NATIVE') != '0' and sys.platform != 'emscripten':
            try:
                import ctypes
                import jass_native
                dll = jass_native._dll()
                if dll and hasattr(dll, 'lua_parse_tree'):
                    for f in (dll.lua_parse_tree, dll.canon_lua_reparen):
                        f.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p),
                                      ctypes.POINTER(ctypes.c_size_t)]
                        f.restype = ctypes.c_int
                    _NATIVE[0] = dll
            except (ImportError, OSError, AttributeError):
                pass
    return _NATIVE[0]


def _call_native(name, data):
    import ctypes
    dll = _native()
    if not dll:
        return 3, None
    out, n = ctypes.c_void_p(), ctypes.c_size_t()
    r = getattr(dll, name)(data, len(data), ctypes.byref(out), ctypes.byref(n))
    if r != 0:
        return r, None
    try:
        return 0, ctypes.string_at(out.value, n.value)
    finally:
        dll.jass_free(out, n)


def _parse_native(text):
    if not _native():
        return None
    try:
        data = text.encode('utf-8', 'surrogatepass')
    except UnicodeEncodeError:
        return None
    r, buf = _call_native('lua_parse_tree', data)
    if r != 0:
        return None
    import gc
    on = gc.isenabled()
    gc.disable()
    try:
        return _decode(buf)
    finally:
        if on:
            gc.enable()


def _decode(buf):
    import struct
    nstr, sep, blen, nints = struct.unpack_from('<4I', buf)
    S = buf[16:16 + blen].decode('utf-8', 'surrogatepass').split(chr(sep))
    if len(S) != nstr:
        return None
    off = 16 + blen + (-blen) % 4
    it = iter(memoryview(buf)[off:off + 4 * nints].cast('i').tolist())
    nx = it.__next__
    K = _NATIVE_KINDS
    comments = []
    for _k in range(nx()):
        comments.append(Comment(S[nx()], nx()))
    numbers = {}
    st = []
    push, pop = st.append, st.pop
    for op in it:
        if op == 0:
            push(Name(S[nx()], nx()))
        elif op == 21:
            nt = nx()
            L = len(st) - nx()
            values = st[L:]
            targets = st[L - nt:L]
            del st[L - nt:]
            s = AssignStmt(targets, values, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 7:
            v = S[nx()]
            st[-1] = Index(st[-1], Literal('string', S[nx()], v, nx()), True, nx())
        elif op == 1:
            t = nx()
            push(Literal('string', S[t] if t >= 0 else None, S[nx()], nx()))
        elif op == 14:
            st[-1] = Paren(st[-1], nx())
        elif op == 2:
            t = nx()
            v = numbers.get(t)
            if v is None:
                v = numbers[t] = _number_value(S[t])
            push(Literal('number', S[t], v, nx()))
        elif op == 41:
            L = len(st) - nx()
            b = Block(st[L:])
            del st[L:]
            push(b)
        elif op == 9:
            L = len(st) - nx()
            args = st[L:]
            del st[L:]
            st[-1] = Call(st[-1], args, None, nx())
        elif op == 13:
            r = pop()
            st[-1] = Binary(K[nx()], st[-1], r, nx())
        elif op == 24:
            nb = nx()
            has_else = nx()
            L = len(st) - 2 * nb - has_else
            items = st[L:]
            del st[L:]
            branches = [(items[k], items[k + 1]) for k in range(0, 2 * nb, 2)]
            if has_else:
                branches.append((None, items[-1]))
            s = IfStmt(branches, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 3:
            push(Literal('nil', 'nil', None, nx()))
        elif op == 40:
            s = st[-1]
            a = nx()
            m = nx()
            if m:
                s.leading_comments = comments[a:a + m]
            ni = nx()
            if ni:
                s.inner_comments = [comments[nx()] for _k in range(ni)]
            c = nx()
            if c >= 0:
                s.comment = comments[c]
        elif op == 12:
            st[-1] = Unary(K[nx()], st[-1], nx())
        elif op == 8:
            key = pop()
            st[-1] = Index(st[-1], key, nx() == 1, nx())
        elif op == 20:
            names, attribs = [], []
            for _k in range(nx()):
                names.append(S[nx()])
                a = nx()
                attribs.append(S[a] if a >= 0 else None)
            L = len(st) - nx()
            values = st[L:]
            del st[L:]
            s = LocalStmt(names, attribs, values, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 4:
            push(Literal('boolean', 'true', True, nx()))
        elif op == 5:
            push(Literal('boolean', 'false', False, nx()))
        elif op == 22:
            s = CallStmt(pop(), nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 23:
            name = S[nx()]
            is_local = nx() == 1
            params = [S[nx()] for _k in range(nx())]
            s = FunctionStmt(name, is_local, params, nx() == 1, pop(), nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 30:
            L = len(st) - nx()
            values = st[L:]
            del st[L:]
            s = ReturnStmt(values, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 18:
            L = len(st) - nx()
            fields = st[L:]
            del st[L:]
            push(Table(fields, nx()))
        elif op == 15:
            st[-1] = (None, st[-1])
        elif op == 16:
            st[-1] = (S[nx()], st[-1])
        elif op == 17:
            v = pop()
            st[-1] = (st[-1], v)
        elif op == 10:
            L = len(st) - nx()
            args = st[L:]
            del st[L:]
            st[-1] = Call(st[-1], args, S[nx()], nx())
        elif op == 42:
            a = nx()
            st[-1].end_comments = comments[a:a + nx()]
        elif op == 11:
            params = [S[nx()] for _k in range(nx())]
            st[-1] = FunctionExpr(params, nx() == 1, st[-1], nx())
        elif op == 25:
            body = pop()
            s = WhileStmt(pop(), body, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 26:
            var = S[nx()]
            body = pop()
            step = pop() if nx() else None
            stop = pop()
            s = NumericForStmt(var, pop(), stop, step, body, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 27:
            names = [S[nx()] for _k in range(nx())]
            body = pop()
            L = len(st) - nx()
            exprs = st[L:]
            del st[L:]
            s = GenericForStmt(names, exprs, body, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 28:
            cond = pop()
            s = RepeatStmt(pop(), cond, nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 29:
            s = DoStmt(pop(), nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 31:
            s = BreakStmt(nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 32:
            s = GotoStmt(S[nx()], nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 33:
            s = LabelStmt(S[nx()], nx())
            s.span = (nx(), nx())
            push(s)
        elif op == 6:
            push(Literal('vararg', '...', None, nx()))
        else:
            raise ValueError('lua_parse_tree: unknown op %d' % op)
    body = st.pop()
    functions = {}
    for s in body:
        if type(s) is FunctionStmt:
            functions[s.name] = s
    return Chunk(body, functions, comments)


def recursion_room(f):
    import functools

    @functools.wraps(f)
    def run(*args, **kwargs):
        old = sys.getrecursionlimit()
        if old < _RECURSION:
            sys.setrecursionlimit(_RECURSION)
        try:
            return f(*args, **kwargs)
        finally:
            if old < _RECURSION:
                sys.setrecursionlimit(old)
    return run


def _parse_python(text):
    old = sys.getrecursionlimit()
    if old < _RECURSION:
        sys.setrecursionlimit(_RECURSION)
    try:
        return _Parser(text).chunk()
    finally:
        if old < _RECURSION:
            sys.setrecursionlimit(old)


_INDENT = '    '
_WORD = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')
_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')


def _cat(a, b):
    if not a or not b:
        return a + b
    x, y = a[-1], b[0]
    if x in _WORD:
        space = y in _WORD or y == '.'
    elif x == '.':
        space = y == '.' or y in _WORD
    elif x == '-':
        space = y == '-'
    elif x == '[':
        space = y == '[' or y == '='
    else:
        space = y == '=' and x in '<>=~'
    return a + ' ' + b if space else a + b


def _is_name(s):
    return _NAME.match(s) is not None and s not in KEYWORDS


def _dot_name(index):
    if not index.dot:
        return None
    key = index.key
    t = type(key)
    name = key.value if t is Literal and key.kind == 'string' else key.name if t is Name else None
    return name if isinstance(name, str) and _is_name(name) else None


def _needs_paren(child, priority, left):
    t = type(child)
    if t is Binary:
        cl, cr = BINARY_PRIORITY[child.op]
        return priority > cr if left else cl <= priority
    return t is Unary and left and priority > UNARY_PRIORITY


def _quote(value):
    out = ['"']
    for c in value:
        o = ord(c)
        if c == '"' or c == '\\':
            out.append('\\' + c)
        elif c == '\n':
            out.append('\\n')
        elif o < 32 or o == 127:
            out.append('\\%03d' % o)
        elif 0xdc80 <= o <= 0xdcff:
            out.append('\\%03d' % (o - 0xdc00))
        else:
            out.append(c)
    out.append('"')
    return ''.join(out)


def _literal_text(lit):
    v = lit.value
    if lit.kind == 'string':
        return _quote(v)
    if lit.kind == 'number':
        if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
            return '(0/0)' if v != v else '1e999' if v > 0 else '-1e999'
        return repr(v)
    if lit.kind == 'boolean':
        return 'true' if v else 'false'
    return '...' if lit.kind == 'vararg' else 'nil'


class _Printer:
    def __init__(self, pretty):
        self.pretty = pretty
        self.comma = ', ' if pretty else ','
        self.eq = ' = ' if pretty else '='

    def words(self, *parts):
        if self.pretty:
            return ' '.join([p for p in parts if p])
        out = ''
        for p in parts:
            out = _cat(out, p)
        return out

    def exprs(self, values, level):
        return self.comma.join([self.expr(v, level) for v in values])

    def expr(self, e, level):
        t = type(e)
        if t is Name:
            return e.name
        if t is Literal:
            return e.text if e.text is not None else _literal_text(e)
        if t is Call or t is Index:
            return self.suffixed(e, level)
        if t is Binary:
            return self.binary(e, level)
        if t is Unary:
            s = self.expr(e.operand, level)
            if type(e.operand) is Binary and BINARY_PRIORITY[e.operand.op][0] <= UNARY_PRIORITY:
                s = '(' + s + ')'
            if e.op == 'not':
                return self.words('not', s)
            return e.op + ' ' + s if e.op == '-' and s[:1] == '-' else e.op + s
        if t is Paren:
            return '(' + self.expr(e.inner, level) + ')'
        if t is Table:
            return self.table(e, level)
        if t is FunctionExpr:
            return self.function('function', e.params, e.is_vararg, e.body, level)
        raise TypeError('not a Lua expression node: %r' % (e,))

    def suffixed(self, e, level):
        chain = []
        while True:
            t = type(e)
            if t is Call:
                chain.append(e)
                e = e.func
            elif t is Index:
                chain.append(e)
                e = e.base
            else:
                break
        s = self.expr(e, level)
        if type(e) is not Name and type(e) is not Paren:
            s = '(' + s + ')'
        for n in reversed(chain):
            if type(n) is Index:
                name = _dot_name(n)
                if name is not None:
                    s += '.' + name
                else:
                    key = self.expr(n.key, level)
                    s += '[' + (' ' if key[:1] == '[' else '') + key + ']'
            else:
                if n.method is not None:
                    s += ':' + n.method
                s += '(' + self.exprs(n.args, level) + ')'
        return s

    def binary(self, e, level):
        spine = []
        while type(e) is Binary:
            spine.append(e)
            e = e.left
        s = self.expr(e, level)
        left = e
        for n in reversed(spine):
            lp, rp = BINARY_PRIORITY[n.op]
            if _needs_paren(left, lp, True):
                s = '(' + s + ')'
            r = self.expr(n.right, level)
            if _needs_paren(n.right, rp, False):
                r = '(' + r + ')'
            s = self.words(s, n.op, r)
            left = n
        return s

    def table(self, e, level):
        parts = []
        for key, value in e.fields:
            v = self.expr(value, level)
            if key is None:
                parts.append(v)
            elif type(key) is str and _is_name(key):
                parts.append(key + self.eq + v)
            else:
                k = _quote(key) if type(key) is str else self.expr(key, level)
                parts.append('[' + (' ' if k[:1] == '[' else '') + k + ']' + self.eq + v)
        return '{' + self.comma.join(parts) + '}'

    def function(self, head, params, vararg, body, level):
        sig = head + '(' + self.comma.join(list(params) + (['...'] if vararg else [])) + ')'
        return self.compound(sig, body, 'end', level)

    def compound(self, head, body, tail, level):
        if not self.pretty:
            return _cat(_cat(head, ';'.join([self.stmt(s, 0) for s in body])), tail)
        lines = self.lines(body, level + 1)
        if not lines:
            return head + ' ' + tail
        return head + '\n' + '\n'.join(lines) + '\n' + _INDENT * level + tail

    def stmt(self, s, level):
        t = type(s)
        if t is CallStmt:
            return self.expr(s.call, level)
        if t is AssignStmt:
            return self.exprs(s.targets, level) + self.eq + self.exprs(s.values, level)
        if t is LocalStmt:
            fmt = ' <%s>' if self.pretty else '<%s>'
            names = self.comma.join([n + fmt % a if a else n for n, a in zip(s.names, s.attribs, strict=True)])
            if not s.values:
                return self.words('local', names)
            return self.words('local', names, '=', self.exprs(s.values, level))
        if t is FunctionStmt:
            head = self.words('local function' if s.is_local else 'function', s.name)
            return self.function(head, s.params, s.is_vararg, s.body, level)
        if t is IfStmt:
            return self.if_stmt(s, level)
        if t is ReturnStmt:
            return self.words('return', self.exprs(s.values, level))
        if t is WhileStmt:
            return self.compound(self.words('while', self.expr(s.cond, level), 'do'), s.body, 'end', level)
        if t is NumericForStmt:
            r = self.expr(s.start, level) + self.comma + self.expr(s.stop, level)
            if s.step is not None:
                r += self.comma + self.expr(s.step, level)
            return self.compound(self.words('for', s.var, '=', r, 'do'), s.body, 'end', level)
        if t is GenericForStmt:
            head = self.words('for', self.comma.join(s.names), 'in', self.exprs(s.exprs, level), 'do')
            return self.compound(head, s.body, 'end', level)
        if t is RepeatStmt:
            return self.compound('repeat', s.body, self.words('until', self.expr(s.cond, level)), level)
        if t is DoStmt:
            return self.compound('do', s.body, 'end', level)
        if t is BreakStmt:
            return 'break'
        if t is GotoStmt:
            return self.words('goto', s.label)
        if t is LabelStmt:
            return '::' + s.name + '::'
        raise TypeError('not a Lua statement node: %r' % (s,))

    def if_stmt(self, s, level):
        if not self.pretty:
            out = ''
            for n, (cond, body) in enumerate(s.branches):
                if cond is None:
                    out = _cat(out, 'else')
                else:
                    out = self.words(out, 'elseif' if n else 'if', self.expr(cond, level), 'then')
                out = _cat(out, ';'.join([self.stmt(x, 0) for x in body]))
            return _cat(out, 'end')
        ind = _INDENT * level
        parts = []
        for n, (cond, body) in enumerate(s.branches):
            head = 'else' if cond is None else '%s %s then' % ('elseif' if n else 'if', self.expr(cond, level))
            parts.append(ind + head if n else head)
            parts.extend(self.lines(body, level + 1))
        parts.append(ind + 'end')
        return '\n'.join(parts)

    def lines(self, body, level):
        ind = _INDENT * level
        out = []
        for n, s in enumerate(body):
            for c in s.leading_comments:
                out.append(ind + c.text)
            for c in s.inner_comments:
                out.append(ind + c.text)
            text = self.stmt(s, level)
            if n and text[:1] == '(':
                text = ';' + text
            if s.comment is not None:
                text += ' ' + s.comment.text
            out.append(ind + text)
        for c in getattr(body, 'end_comments', ()):
            out.append(ind + c.text)
        return out


def _write(node, pretty):
    old = sys.getrecursionlimit()
    if old < _RECURSION:
        sys.setrecursionlimit(_RECURSION)
    try:
        p = _Printer(pretty)
        if isinstance(node, Chunk):
            node = node.body
        if isinstance(node, list):
            if not pretty:
                return ';'.join([p.stmt(s, 0) for s in node])
            lines = p.lines(node, 0)
            return '\n'.join(lines) + '\n' if lines else ''
        if isinstance(node, Stmt):
            return '\n'.join(p.lines([node], 0)) if pretty else p.stmt(node, 0)
        if isinstance(node, Comment):
            return node.text if pretty else ''
        return p.expr(node, 0)
    finally:
        if old < _RECURSION:
            sys.setrecursionlimit(old)


def canonical(text_or_node):
    return _write(parse(text_or_node) if isinstance(text_or_node, str) else text_or_node, False)


_EDITOR = '''function Trig_Test_Conditions()
    if (not (GetTriggerUnit() == udg_Hero)) then
        return false
    end
    return true
end

function Trig_Test_Func003C()
    if (not (udg_Count > 0)) then
        return false
    end
    return true
end

function Trig_Test_Func005A()
    KillUnit(GetEnumUnit())
end

function Trig_Test_Actions()
    -- a comment action
    udg_Count = (udg_Count + 1)
    udg_Units[udg_Count] = GetTriggerUnit()
    if (Trig_Test_Func003C()) then
        DisplayTextToForce(GetPlayersAll(), "TRIGSTR_003")
    else
        DoNothing()
    end
    bj_forLoopAIndex = 1
    bj_forLoopAIndexEnd = 10
    while (true) do
        if (bj_forLoopAIndex > bj_forLoopAIndexEnd) then break end
        CreateNUnitsAtLoc(1, FourCC("hfoo"), Player(0), GetRectCenter(GetPlayableMapRect()), bj_UNIT_FACING)
        bj_forLoopAIndex = bj_forLoopAIndex + 1
    end
    ForGroupBJ(GetUnitsInRectAll(GetPlayableMapRect()), Trig_Test_Func005A)
end

function InitTrig_Test()
    gg_trg_Test = CreateTrigger()
    DisableTrigger(gg_trg_Test)
    TriggerRegisterPlayerChatEvent(gg_trg_Test, Player(0), "-ap", true)
    TriggerAddCondition(gg_trg_Test, Condition(Trig_Test_Conditions))
    TriggerAddAction(gg_trg_Test, Trig_Test_Actions)
end
'''
_COMMENTS = ('-- header\n--[[ long\ncomment ]]\nlocal a = 1 -- trailing\n--[==[ level ]==]\nlocal t = {\n  1, -- one\n'
             '  2, --[[ two ]]\n}\nfunction f()\n  -- inside\n  x = 1\n  -- before end\nend -- after end\n'
             'if a then -- then\nelse -- else\n  -- only comment\nend\n-- eof comment')


def _upvalues(n):
    names = ['a%d' % i for i in range(150)] + ['b%d' % i for i in range(n - 150)]
    return 'local %s\nlocal function f()\n  local %s\n  return function() local _ %s end\nend\n' % (
        ', '.join(names[:150]), ', '.join(names[150:]), ' '.join('_ = ' + v for v in names))


_GOOD = (
    ('assignment', 'a = 1\na, b.c, d[1] = 1, 2, 3\nx, y = f()\na.b.c.d = {}\na[b][c] = 1\na:b().c = 2\n'),
    ('local', 'local a\nlocal b, c = 1\nlocal d, e = ...\nlocal f = f\n'),
    ('local attributes', 'local x <const>, y <close> = 5, nil\nlocal z <const> = x\n'),
    ('function statements', 'function f(a, b, ...) return ... end\nfunction a.b.c:m(x) return self, x end\n'
                            'local function g(n) if n > 0 then return g(n - 1) end end\n'),
    ('calls', 'f()\nf "s"\nf {1, 2}\nf[[long]]\na.b:c(1)\na:b"x":c{}\nf()()\n(f)()\nobj:m"s"\n'),
    ('call across lines', 'local t = x\n(f)()\n'),
    ('if', 'if a then b() elseif c then d() elseif e then else f() end\nif x then end\n'
           'if a then if b then c() else d() end end\n'),
    ('while and for', 'while i < 10 do i = i + 1 end\nfor i = 1, 10 do end\nfor i = 10, 1, -1 do print(i) end\n'
                      'for k, v in pairs(t) do end\nfor a, b, c in next, t, nil do break end\n'),
    ('repeat', 'repeat local x = f() until x\nrepeat until true\n'),
    ('do and return', 'do local x = 1 end\ndo return end\nreturn 1, 2;'),
    ('goto and labels', 'for i = 1, 3 do\n  if i == 2 then goto continue end\n  local x = i\n  ::continue::\nend\n'
                        '::top:: do goto top end\ndo goto e; local z = 1; ::e:: end\nwhile true do goto out end\n'
                        '::out::'),
    ('precedence', 'x = a or b and c < d | e ~ f & g << h .. i + j * k ^ -l\nx = -x ^ 2\nx = 2 ^ -3\n'
                   'x = not a == b\nx = #t + 1\nx = ~x\nx = a // b % c\nx = a .. b .. c\nx = a ^ b ^ c\n'
                   'x = a < b == (c > d)\nx = - - x\nx = not not x\nx = a >> 1 << 2\nx = 1 + 2 - 3 * 4 / 5 % 6\n'
                   'x = (a + b) * c\nx = ((a))\nx = a~=b\nx = a ~ ~b\nx = 1 .. 2\nx = a..b\n'),
    ('tables', 't = {}\nt = {1, 2, 3,}\nt = {a = 1; b = 2}\nt = {[k] = v, [1 + 1] = 2}\nt = {{}, {{}}, f(), g}\n'
               't = {"x"; [[y]], z = {w = 1}}\nt = {[ [[k]] ] = 1}\nt = {f = function() end, 1}\n'),
    ('varargs', 'local function v(...) local a, b = ... return select("#", ...), {...}, (...) end\n'),
    ('function expressions', 'local f = function(x) return x end\n(function() end)()\nlocal g = function(...) end\n'),
    ('numbers', 'n = {0, 3, 3.0, 3.1416, 314.16e-2, 0.31416E1, 34e1, 0x0.1E, 0xA23p-4, 0X1.921FB54442D18P+1, 0xff,'
                ' .5, 5., 9223372036854775807, 9223372036854775808, 0xffffffffffffffff, 1e+10, 1E-2, 0x.8p1, 0xA.,'
                ' 007}\n'),
    ('strings', 's = {\'a\', "b\\"c", "\\65\\066\\x43\\u{48}\\z\n       !", \'tab\\tnl\\n\', "a\\\nb", [[x]],'
                ' [==[a]]b]==], [[\nfirst line]], \'\\\'\', "\\\\", "\\0", "\\255", "\\u{10FFFF}", "caf\u00e9"}\n'),
    ('Lua 5.3, not 5.4', 'x = 5y = 6\n::a:: do ::a:: end\ns = "\\u{10FFFF}"\n'),
    ('comments', _COMMENTS),
    ('semicolons', ';;a = 1;;b = 2;\nlocal c = 3;'),
    ('world editor', _EDITOR),
    ('minified', 'a=1 b=2 function f()return 1 end local x=y(f)()if a then b()elseif c then d()else e()end;'
                 'for i=1,2 do end;local t={a=1,[2]=3,"x"}return t'),
    ('methods', 'local obj = {}\nfunction obj:get() return self.v end\n'
                'function obj.new(v) return setmetatable({v = v}, {__index = obj}) end\nprint(obj.new(1):get())\n'),
    ('upvalues and _ENV', 'local a = 1\nlocal function outer()\n  local b = 2\n'
                          '  return function() return a + b + c end\nend\n'
                          'local _ENV = setmetatable({}, {__index = _G})\nfunction main() end\nx = 1\n'),
    ('suffix chains', 'x = a.b.c:d(1):e().f[g]["h"]\n'),
    ('CRLF', 'a = 1\r\nb = [[x\r\ny]]\r\n-- c\r\nc = "\\\r\n"\r\n'),
    ('empty', ''),
    ('only comments', '-- a\n--[[ b ]]'),
    ('197 levels', 'x = ' + '(' * 197 + '1' + ')' * 197),
    ('200 locals', 'local ' + ', '.join('a%d' % i for i in range(200))),
    ('199 targets', ', '.join(['a'] * 199) + ' = 1'),
    ('255 upvalues', _upvalues(255)),
    ('198 labels in a row', ''.join('::l%d:: ' % i for i in range(198)) + ';' * 250),
    ('3000 additions', 'x = a' + ' + a' * 3000),
    ('3000 fields', 'x = a' + '.b' * 3000),
)
_BAD = (
    ('unexpected end', 'x = '),
    ('operator without operand', 'x = 1 +'),
    ('unclosed call', 'f(\n1,\n'),
    ('unclosed if', 'if x then\n  y()\n'),
    ('for without comma', 'for i = 1 do end'),
    ('local number', 'local 1 = 2'),
    ('expression statement', 'x = 1\na + b = c'),
    ('parenthesized target', '(a) = 1'),
    ('call target', 'f() = 1'),
    ('bare index', 'a.b'),
    ('malformed number', 'x = 1..2'),
    ('hex without digits', 'x = 0x'),
    ('exponent without digits', 'x = 3e'),
    ('number touching a keyword', 'x = 1and 2'),
    ('unfinished string', 'x = "abc\ny = 1'),
    ('unfinished long string', 'x = [[abc\n\n'),
    ('unfinished long comment', 'x = 1\n--[[ abc\n'),
    ('invalid escape', 'x = "\\q"'),
    ('decimal escape too large', 'x = "\\300"'),
    ('hex escape', 'x = "\\xZZ"'),
    ('UTF-8 escape too large', 'x = "\\u{110000}"'),
    ('UTF-8 escape without brace', 'x = "\\u{12"'),
    ('hex escape after a digit', 'x = "\\x4Z"'),
    ('bad escape in an unfinished string', 'x = "\\300\ny = 1'),
    ('unfinished string at the end', 'x = "abc'),
    ('invalid long delimiter', 'x = [==x'),
    ('break outside a loop', 'x = 1\nbreak\n'),
    ('goto without label', 'goto nowhere'),
    ('goto into a local scope', 'do goto l; local x = 1; ::l:: print(x) end'),
    ('goto into the repeat scope', 'repeat goto l; local x ::l:: until x'),
    ('label twice', '::a:: ::a::'),
    ('vararg outside', 'function f() return ... end'),
    ('return not last', 'return 1; x = 2'),
    ('unknown attribute', 'local x <foo> = 1'),
    ('assignment to const', 'local x <const> = 1\nx = 2'),
    ('two to-be-closed', 'local a <close>, b <close> = nil, nil'),
    ('unknown character', 'x = 1 @ 2'),
    ('non-ASCII name', 'local caf\u00e9 = 1'),
    ('field without value', 'local t = {a = }'),
    ('extra end', 'x = function() end end'),
    ('method without arguments', 'a:b'),
    ('string with a suffix', 'x = "a":len()'),
    ('parameter after dots', 'function f(..., a) end'),
    ('goto a keyword', 'goto break'),
    ('error after a long string', 'local s = [[\n\n]] +'),
    ('201 locals', 'local ' + ', '.join('a%d' % i for i in range(201))),
    ('198 levels', 'x = ' + '(' * 198 + '1' + ')' * 198),
    ('200 targets', ', '.join(['a'] * 200) + ' = 1'),
    ('256 upvalues', _upvalues(256)),
    ('200 labels in a row', ''.join('::l%d:: ' % i for i in range(200))),
    ('semicolon 200 levels deep', 'do ' * 199 + ';' + ' end' * 199),
    ('bad label after a label', 'goto c local x = 1 ::c:: ::\nend'),
)