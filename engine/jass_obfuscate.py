# Obfuscates a JASS map script: every name renamed, strings and raw codes encrypted.
import collections
import hashlib
import itertools
import json
import os
import random
import re
import subprocess
import sys
import time

import sstrhash


TOKEN = re.compile(r'''(?P<comment>//[^\n]*)|(?P<str>"(?:[^"\\]|\\.)*")|(?P<raw>'(?:[^'\\]|\\.)*')'''
                   r'''|(?P<num>0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|\d+\.\d*|\.\d+|\d+)|(?P<id>[A-Za-z_]\w*)'''
                   r'''|(?P<nl>\r?\n)|(?P<ws>[ \t\r\f\v]+)|(?P<op>.)''', re.S)
TOKEN_CR = re.compile(r'''(?P<com>//[^\r\n]*)|(?P<str>"(?:[^"\\]|\\.)*")|(?P<raw>'(?:[^'\\]|\\.)*')'''
                      r'''|(?P<num>0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|\d+\.\d*|\.\d+|\d+)|(?P<id>[A-Za-z_]\w*)'''
                      r'''|(?P<nl>\r\n|\n|\r)|(?P<ws>[ \t\f\v]+)|(?P<op>.)''', re.S)
_RX_BARE_CR = re.compile(r'\r(?!\n)')
PIECE = re.compile(r'\\.|.', re.S)
WORD_PIECE = re.compile(r'\\.|[A-Za-z0-9]+|.', re.S)
KEYWORDS = set('''function takes returns return nothing endfunction local set call if then else elseif
endif loop endloop exitwhen globals endglobals constant native type extends array and or not true false
null debug integer real boolean string handle code'''.split())
MODULUS = 9973
WIDTH = 4
SEGMENT = 250
ALPHABET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
VECTOR_CAP = 30000


def arg(fname, default_value=None):
    for a in sys.argv[1:]:
        if a.startswith('--%s=' % fname):
            return a.split('=', 1)[1]
    return default_value


def flag(fname):
    return ('--%s' % fname) in sys.argv[1:]


TOKEN_KINDS = ('comment', 'str', 'raw', 'num', 'id', 'nl', 'ws', 'op')
_LEXER = []


def _native_lexer():
    if not _LEXER:
        try:
            import jass_native
            _LEXER.append(jass_native.load_lexer())
        except Exception:
            _LEXER.append(None)
    return _LEXER[0]


def tokenize(body_text):
    if _token_of(body_text) is TOKEN_CR:
        return tokenize_regex(body_text)
    lex = _native_lexer()
    r = lex(body_text, 0) if lex is not None else None
    if r is not None:
        types, ends = r
        kinds = list(map(TOKEN_KINDS.__getitem__, types))
        texts = list(map(body_text.__getitem__, map(slice, itertools.chain((0,), ends), ends)))
        return kinds, texts
    return tokenize_regex(body_text)


def _token_of(body_text):
    return TOKEN_CR if '\r' in body_text and _RX_BARE_CR.search(body_text) else TOKEN


def tokenize_regex(body_text):
    kinds, texts = [], []
    ka, ta = kinds.append, texts.append
    for m in _token_of(body_text).finditer(body_text):
        ka(m.lastgroup)
        ta(m.group())
    return kinds, texts


def engine_ids(paths):
    out = set()
    for c in paths:
        t = open(c, 'rb').read().decode('utf-8', 'surrogateescape')
        kinds, texts = tokenize(t)
        out.update(x for k, x in zip(kinds, texts) if k == 'id')
    return out


class Function(object):
    def __init__(self, fname, li0):
        self.fname = fname
        self.li0 = li0
        self.li1 = None
        self.local_vars = []
        self.new_ones = {}


class Generator(object):
    def __init__(self, rng, forbidden):
        self.rng = rng
        self.in_use = set(forbidden)

    def new(self, lmin, lmax, local_vars=None):
        rng = self.rng
        while True:
            n = rng.randint(lmin, lmax)
            s = rng.choice('Il') + ''.join(rng.choice('Il1') for _ in range(n - 1))
            if s in self.in_use or (local_vars is not None and s in local_vars):
                continue
            if local_vars is None:
                self.in_use.add(s)
            else:
                local_vars.add(s)
            return s


def lines_of(kinds, texts):
    line_list = []
    current = []
    inv_slot = {}
    seen_ = False
    for i, k in enumerate(kinds):
        if k == 'nl':
            line_list.append(current)
            current = []
            seen_ = False
            continue
        if k == 'ws' or k == 'comment':
            seen_ = True
            continue
        if seen_:
            inv_slot[i] = True
        seen_ = False
        current.append(i)
    line_list.append(current)
    return line_list, inv_slot


def structure(line_list, texts):
    globals_block = []
    natives = set()
    func_list = {}
    order = []
    li_globals = li_endglobals = None
    status = 'topo'
    current = None
    for li, lin in enumerate(line_list):
        if not lin:
            continue
        t0 = texts[lin[0]]
        if status == 'globals':
            if t0 == 'endglobals':
                status = 'topo'
                li_endglobals = li
                continue
            j = 0
            const = False
            if texts[lin[j]] == 'constant':
                const = True
                j += 1
            type_name = texts[lin[j]]
            j += 1
            arr = False
            if j < len(lin) and texts[lin[j]] == 'array':
                arr = True
                j += 1
            name_i = lin[j]
            begin = None
            if j + 1 < len(lin) and texts[lin[j + 1]] == '=':
                begin = lin[j + 2:]
            globals_block.append(
                {
                    'fname': texts[name_i],
                    'const': const,
                    'type_name': type_name,
                    'arr': arr,
                    'begin': begin,
                    'li': li,
                    'j_name': j,
                }
            )
            continue
        if t0 == 'globals':
            status = 'globals'
            li_globals = li
            continue
        t1 = texts[lin[1]] if len(lin) > 1 else ''
        if t0 == 'native' or (t0 == 'constant' and t1 == 'native'):
            natives.add(texts[lin[1 if t0 == 'native' else 2]])
            continue
        if t0 == 'function' or (t0 == 'constant' and t1 == 'function'):
            j = 1 if t0 == 'function' else 2
            fname = texts[lin[j]]
            current = Function(fname, li)
            func_list[fname] = current
            order.append(fname)
            k = j + 1
            if texts[lin[k]] == 'takes' and texts[lin[k + 1]] != 'nothing':
                k += 1
                while k < len(lin) and texts[lin[k]] != 'returns':
                    if texts[lin[k]] == ',':
                        k += 1
                        continue
                    current.local_vars.append(texts[lin[k + 1]])
                    k += 2
            status = 'function'
            continue
        if status == 'function':
            if t0 == 'endfunction':
                current.li1 = li
                status = 'topo'
                current = None
                continue
            if t0 == 'local':
                j = 2
                if texts[lin[j]] == 'array':
                    j += 1
                current.local_vars.append(texts[lin[j]])
    return globals_block, natives, func_list, order, li_globals, li_endglobals


def on_close(lin, texts, a):
    max_depth = 0
    for b in range(a, len(lin)):
        t = texts[lin[b]]
        if t == '(':
            max_depth += 1
        elif t == ')':
            max_depth -= 1
            if max_depth == 0:
                return b
    return None


def content(tok):
    return tok[1:-1]


def operands(lin, texts, a, b):
    while a < b and texts[lin[a]] == '(' and on_close(lin, texts, a) == b:
        a += 1
        b -= 1
    out = []
    max_depth = 0
    begin = a
    for c in range(a, b + 1):
        t = texts[lin[c]]
        if t == '(':
            max_depth += 1
        elif t == ')':
            max_depth -= 1
        elif t == '+' and max_depth == 0:
            out.append((begin, c - 1))
            begin = c + 1
    out.append((begin, b))
    return out


def arguments(lin, texts, a, q):
    out = []
    max_depth = 0
    begin = a + 1
    for c in range(a + 1, q):
        t = texts[lin[c]]
        if t == '(' or t == '[':
            max_depth += 1
        elif t == ')' or t == ']':
            max_depth -= 1
        elif t == ',' and max_depth == 0:
            out.append((begin, c - 1))
            begin = c + 1
    if begin < q:
        out.append((begin, q - 1))
    return out


def literal_only(lin, texts, kinds, a, b):
    while a < b and texts[lin[a]] == '(' and texts[lin[b]] == ')':
        a += 1
        b -= 1
    if a == b and kinds[lin[a]] == 'str':
        return content(texts[lin[a]])
    return None


def piece_list(s, rx=PIECE):
    return rx.findall(s)


def base36(v, alf, n=4):
    d = []
    for _ in range(n):
        d.append(alf[v % 36])
        v //= 36
    return ''.join(reversed(d))


def main():
    t0 = time.time()
    entry = arg('j')
    output = arg('output')
    common = arg('common')
    blizz = arg('blizzard')
    if not (entry and output and common and blizz):
        print(__doc__)
        return 2
    raw_bytes = open(entry, 'rb').read()
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        raw_bytes = raw_bytes[3:]
    body_text = raw_bytes.decode('utf-8', 'surrogateescape')
    seed = int(arg('seed', '0') or 0) or int(hashlib.sha256(raw_bytes).hexdigest()[:12], 16)
    rng = random.Random(seed)
    do_names = not flag('no-names')
    do_strings = not flag('no-strings')
    do_ids = not flag('no-ids')
    block_entry = int(arg('block_entry', '4000'))
    piece_rx = WORD_PIECE if arg('piece_list', 'character') == 'word' else PIECE
    keep_names = set(x for x in (arg('keep_names', '') or '').split(',') if x)

    kinds, texts = tokenize(body_text)
    line_list, inv_slot = lines_of(kinds, texts)
    globals_block, natives, func_list, order, li_globals_, li_endglobals_ = structure(line_list, texts)
    if li_globals_ is None or li_endglobals_ is None or 'main' not in func_list:
        raise SystemExit('ERROR: expected a globals block and the main function')
    engine = engine_ids([common, blizz])
    print('input: %s (%d B, %d lines, %d tokens); functions %d, globals %d, natives %d; seed %d'
          % (entry, len(raw_bytes), len(line_list), len(kinds), len(func_list), len(globals_block), len(natives), seed))

    owner = [None] * len(line_list)
    for f in func_list.values():
        for li in range(f.li0, (f.li1 or f.li0) + 1):
            owner[li] = f

    called = {}
    for f in func_list.values():
        tgt = set()
        for li in range(f.li0 + 1, f.li1 or f.li0):
            lin = line_list[li]
            for p, ti in enumerate(lin):
                if kinds[ti] != 'id':
                    continue
                next_item = texts[lin[p + 1]] if p + 1 < len(lin) else ''
                if texts[ti] in func_list:
                    prev = texts[lin[p - 1]] if p > 0 else ''
                    if next_item == '(' or prev == 'function':
                        tgt.add(texts[ti])
                elif texts[ti] == 'ExecuteFunc' and next_item == '(':
                    q = on_close(lin, texts, p + 1)
                    if q is not None:
                        vals = [literal_only(lin, texts, kinds, x, y) for x, y in operands(lin, texts, p + 2, q - 1)]
                        if all(v is not None for v in vals) and ''.join(vals) in func_list:
                            tgt.add(''.join(vals))
        called[f.fname] = tgt
    fm = func_list['main']
    li_first = None
    init_locals = []
    for li in range(fm.li0 + 1, fm.li1):
        lin = line_list[li]
        if not lin:
            continue
        if texts[lin[0]] == 'local':
            if len(lin) > 3:
                eq = [p for p, ti in enumerate(lin) if texts[ti] == '=']
                if eq:
                    init_locals.append((lin, eq[0] + 1))
            continue
        li_first = li
        break
    if li_first is None:
        li_first = fm.li1
    roots = ['config'] if 'config' in func_list else []
    for lin, a in init_locals:
        for p in range(a, len(lin)):
            fname = texts[lin[p]]
            if kinds[lin[p]] == 'id' and fname in func_list and fname != 'main' and \
                    ((p + 1 < len(lin) and texts[lin[p + 1]] == '(') or texts[lin[p - 1]] == 'function'):
                roots.append(fname)
    early_funcs = set()
    stack = roots
    while stack:
        n = stack.pop()
        if n in early_funcs:
            continue
        early_funcs.add(n)
        stack.extend(called.get(n, ()))

    frozen = set()
    read_early = set()
    for g in globals_block:
        if g['begin']:
            for ti in g['begin']:
                frozen.add(ti)
                if kinds[ti] == 'id':
                    read_early.add(texts[ti])
    for n in early_funcs:
        f = func_list[n]
        for li in range(f.li0, (f.li1 or f.li0) + 1):
            for ti in line_list[li]:
                frozen.add(ti)
                if kinds[ti] == 'id':
                    read_early.add(texts[ti])
    for lin, a in init_locals:
        for ti in lin[a:]:
            frozen.add(ti)
            if kinds[ti] == 'id':
                read_early.add(texts[ti])

    converted = {}
    for g in globals_block:
        begin = g['begin']
        if g['arr'] or not begin or g['fname'] in read_early:
            continue
        a, b = 0, len(begin) - 1
        while a < b and texts[begin[a]] == '(' and texts[begin[b]] == ')':
            a += 1
            b -= 1
        if a != b:
            continue
        ti = begin[a]
        if (kinds[ti] == 'str' and g['type_name'] == 'string' and do_strings and texts[ti] != '""') or \
           (kinds[ti] == 'raw' and g['type_name'] == 'integer' and do_ids):
            converted[g['fname']] = ti
            frozen.discard(ti)

    var_lit = []
    var_pattern = set()
    n_var_dyn = 0
    for lin in line_list:
        for p, ti in enumerate(lin):
            if kinds[ti] != 'id' or texts[ti] != 'TriggerRegisterVariableEvent':
                continue
            if p + 1 >= len(lin) or texts[lin[p + 1]] != '(':
                continue
            q = on_close(lin, texts, p + 1)
            args = arguments(lin, texts, p + 1, q) if q is not None else []
            if len(args) < 2:
                continue
            a, b = args[1]
            vals = [literal_only(lin, texts, kinds, x, y) for x, y in operands(lin, texts, a, b)]
            if all(v is not None for v in vals):
                var_lit.append((lin, a, b, ''.join(vals)))
                continue
            var_pattern.add((vals[0] if len(vals) > 1 and vals[0] is not None else '',
                             vals[-1] if len(vals) > 1 and vals[-1] is not None else ''))
            n_var_dyn += 1
    keep_var = set(g['fname'] for g in globals_block if g['type_name'] == 'real' and
                   any(g['fname'].startswith(pa) and g['fname'].endswith(su) for pa, su in var_pattern))

    forbidden = (
        set(engine)
        | KEYWORDS
        | set(natives)
        | keep_names
        | set(func_list)
        | set(g['fname'] for g in globals_block)
        | set(v[3] for v in var_lit)
    )
    ger = Generator(rng, forbidden)
    keep_f = set(['main', 'config']) | keep_names | engine | natives
    fmap, gmap = {}, {}
    if do_names:
        f_names = [n for n in order if n not in keep_f]
        for n in f_names:
            fmap[n] = ger.new(10, 16)
        for g in globals_block:
            if g['fname'] not in keep_names and g['fname'] not in engine and g['fname'] not in keep_var:
                gmap[g['fname']] = ger.new(10, 16)
        for f in func_list.values():
            in_use = set()
            for n in f.local_vars:
                if n not in f.new_ones:
                    f.new_ones[n] = ger.new(3, 9, in_use)

    subst = {}
    to_delete = set()
    before = {}
    after_diag = {}
    patterns = set()
    dynamic_fields = []
    n_ef_literal = n_ef_dynamic = 0
    for f in func_list.values():
        for li in range(f.li0 + 1, f.li1 or f.li0):
            lin = line_list[li]
            for p, ti in enumerate(lin):
                if kinds[ti] != 'id' or texts[ti] != 'ExecuteFunc':
                    continue
                if p + 1 >= len(lin) or texts[lin[p + 1]] != '(':
                    continue
                q = on_close(lin, texts, p + 1)
                a, b = p + 2, q - 1
                ops = operands(lin, texts, a, b)
                vals = [literal_only(lin, texts, kinds, x, y) for x, y in ops]
                if all(v is not None for v in vals):
                    fname = ''.join(vals)
                    if fname in fmap:
                        subst[lin[a]] = '"%s"' % fmap[fname]
                        kinds[lin[a]] = 'str'
                        for c in range(a + 1, b + 1):
                            to_delete.add(lin[c])
                        n_ef_literal += 1
                    continue
                prefix = vals[0] if len(vals) > 1 and vals[0] is not None else ''
                suffix = vals[-1] if len(vals) > 1 and vals[-1] is not None else ''
                patterns.add((prefix, suffix))
                dynamic_fields.append((lin[a], lin[b]))
                n_ef_dynamic += 1
    name_table = []
    if patterns and fmap:
        for orig, new in fmap.items():
            if any(orig.startswith(pa) and orig.endswith(su) for pa, su in patterns):
                name_table.append((orig, new))
    colisoes = name_collisions(name_table)
    if colisoes:
        print(
            'WARNING: %d Reforged StringHash value(s) repeated in the name table (StringHash does not tell the letter case apart): %s; '
            'the table keeps the names of the group in a chain, checked by text'
            % (len(colisoes), '; '.join('/'.join(g) for g in colisoes[:5]) + (' ...' if len(colisoes) > 5 else ''))
        )
    if name_table:
        for ta, tb in dynamic_fields:
            before[ta] = before.get(ta, '') + '\x00NOMEFN('
            after_diag[tb] = ')' + after_diag.get(tb, '')
    print('ExecuteFunc: %d literal name(s) renamed, %d built at run time (patterns %s); '
          'name table: %d' % (n_ef_literal, n_ef_dynamic, sorted(patterns), len(name_table)))
    n_var_lit = 0
    for lin, a, b, fname in var_lit:
        if fname in gmap:
            subst[lin[a]] = '"%s"' % gmap[fname]
            kinds[lin[a]] = 'str'
            for c in range(a + 1, b + 1):
                to_delete.add(lin[c])
            n_var_lit += 1
    if var_lit or n_var_dyn:
        print('TriggerRegisterVariableEvent: %d literal(s) renamed, %d built at run time '
              '(patterns %s); real globals kept: %d' % (n_var_lit, n_var_dyn, sorted(var_pattern), len(keep_var)))
    if keep_var:
        print(
            'WARNING: TriggerRegisterVariableEvent with a name built at run time: %d real global(s) keep '
            'the name (%s)' % (len(keep_var), ', '.join(sorted(keep_var)[:10]) + (' ...' if len(keep_var) > 10 else ''))
        )

    str_index, raw_index = {}, {}
    str_uses = raw_uses = 0
    li_global_decl = set(g['li'] for g in globals_block)
    for li, lin in enumerate(line_list):
        if li in li_global_decl:
            continue
        for ti in lin:
            if ti in frozen or ti in to_delete:
                continue
            k = kinds[ti]
            if k == 'str' and do_strings:
                s = subst.get(ti, texts[ti])
                if s == '""':
                    continue
                c = content(s)
                if c not in str_index:
                    str_index[c] = None
                str_uses += 1
            elif k == 'raw' and do_ids:
                c = content(texts[ti])
                if c not in raw_index:
                    raw_index[c] = None
                raw_uses += 1
    for n, ti in converted.items():
        c = content(texts[ti])
        if kinds[ti] == 'str':
            str_index.setdefault(c, None)
        else:
            raw_index.setdefault(c, None)
    for orig, _ in name_table:
        str_index.setdefault(orig, None)
    str_list = list(str_index)
    rng.shuffle(str_list)
    for k, c in enumerate(str_list):
        str_index[c] = k
    raw_list = list(raw_index)
    rng.shuffle(raw_list)
    for k, c in enumerate(raw_list):
        raw_index[c] = k
    if len(raw_list) > VECTOR_CAP:
        raise SystemExit('ERROR: %d distinct rawcodes exceed the cap of one vector' % len(raw_list))

    new = lambda: ger.new(10, 16)
    n_str_vectors = max(1, (len(str_list) + VECTOR_CAP - 1) // VECTOR_CAP)
    V_S = [new() for _ in range(n_str_vectors)]
    V_I, V_T, F_D, F_R, F_INI, F_NAME = new(), new(), new(), new(), new(), new()
    H_ALF, H_NAME = new(), new()

    def ref_s(c):
        k = str_index[c]
        return '%s[%d]' % (V_S[k // VECTOR_CAP], k % VECTOR_CAP)

    def ref_r(c):
        return '%s[%d]' % (V_I, raw_index[c])

    unit_ = dict((c, piece_list(c, piece_rx)) for c in str_list)
    all_entries = {}
    for us in unit_.values():
        for x in us:
            all_entries[x] = None
    pairs = collections.Counter()
    if piece_rx is PIECE:
        for us in unit_.values():
            for pair in zip(us, us[1:]):
                pairs[pair] += 1
    slot = MODULUS - 2 - len(all_entries)
    chosen = set(k for k, n in pairs.most_common(max(0, slot)) if n >= 3)
    pieces_of = {}
    for c, us in unit_.items():
        ps = []
        i = 0
        while i < len(us):
            if i + 1 < len(us) and (us[i], us[i + 1]) in chosen:
                ps.append(us[i] + us[i + 1])
                i += 2
            else:
                ps.append(us[i])
                i += 1
        pieces_of[c] = ps
        for x in ps:
            all_entries[x] = None
    all_entries[''] = None
    table = list(all_entries)
    rng.shuffle(table)
    if len(table) >= MODULUS:
        raise SystemExit('ERROR: %d distinct pieces exceed the modulus %d' % (len(table), MODULUS))
    if len(table) > 32000:
        raise SystemExit('ERROR: %d distinct pieces exceed the cap of one vector' % len(table))
    pos = dict((x, i) for i, x in enumerate(table))
    step = rng.randint(1000, MODULUS - 1000)
    n_pieces = 0

    def cipher(c):
        nonlocal n_pieces
        ps = pieces_of[c]
        n_pieces += len(ps)
        pieces = []
        for a in range(0, len(ps), SEGMENT):
            seg = ps[a:a + SEGMENT]
            if len(seg) % 2:
                seg = seg + ['']
            x = rng.randrange(MODULUS)
            x0 = x
            dig = []
            for piece in seg:
                dig.append('%0*d' % (WIDTH, (pos[piece] + x) % MODULUS))
                x = (x + step) % MODULUS
            pieces.append('%s(%d,"%s")' % (F_D, x0, ''.join(dig)))
        return '+'.join(pieces)

    alf = list(ALPHABET)
    rng.shuffle(alf)
    hs = [sstrhash.sstrhash2(ch) for ch in alf]
    if len(set(hs)) != 36:
        raise SystemExit('ERROR: a StringHash repeats inside the alphabet')
    a1, b1 = rng.randint(1000, 49999), rng.randint(0, 65535)
    a2, b2 = rng.randint(1000, 49999), rng.randint(0, 65535)

    def rawval(c):
        c = re.sub(r'\\(.)', r'\1', c, flags=re.S)
        if not c:
            return 0
        v = 0
        for ch in c.encode('utf-8', 'surrogateescape'):
            v = v * 256 + (ch - 256 if ch >= 128 else ch)
        return v & 0xFFFFFFFF

    def encrypt_raw(c):
        k = raw_index[c]
        v = rawval(c)
        hi, lo = (v >> 16) & 0xFFFF, v & 0xFFFF
        ka = (k * a1 + b1) % 65536
        kb = (k * a2 + b2) % 65536
        e = base36((hi + ka) % 65536, alf) + base36((lo + kb) % 65536, alf)
        cut = rng.randint(2, 6)
        return '%s(%d,"%s"+"%s")' % (F_R, k, e[:cut], e[cut:])

    outside_globals = set()
    by_line = {}
    for g in globals_block:
        by_line[g['li']] = g
        if g['fname'] in converted:
            outside_globals.add(g['li'])

    def resolve(ti, lin, p, f):
        fname = texts[ti]
        if not do_names or fname in KEYWORDS:
            return fname
        prev = texts[lin[p - 1]] if p > 0 else ''
        next_item = texts[lin[p + 1]] if p + 1 < len(lin) else ''
        if next_item == '(' or prev == 'function':
            return fmap.get(fname, fname)
        if f is not None and fname in f.new_ones:
            return f.new_ones[fname]
        if fname in gmap:
            return gmap[fname]
        return fmap.get(fname, fname)

    word_ch = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$.')
    not_op = word_ch | frozenset('"\'()[],')
    quoted = frozenset('"\'')

    def emit(lin, f, skip_init=None):
        out = []
        last_pos = ''
        last_op = False
        extra = bool(before or after_diag)
        for p, ti in enumerate(lin):
            if skip_init is not None and p >= skip_init:
                break
            if ti in to_delete:
                continue
            k = kinds[ti]
            if k == 'id':
                t = resolve(ti, lin, p, f)
            elif k == 'str':
                s = subst.get(ti, texts[ti])
                if do_strings and ti not in frozen and s != '""' and content(s) in str_index:
                    t = ref_s(content(s))
                else:
                    t = s
            elif k == 'raw':
                if do_ids and ti not in frozen and content(texts[ti]) in raw_index:
                    t = ref_r(content(texts[ti]))
                else:
                    t = texts[ti]
            else:
                t = texts[ti]
            if extra:
                t = before.get(ti, '') + t + after_diag.get(ti, '')
            if '\x00' in t:
                t = t.replace('\x00NOMEFN', F_NAME)
            if out:
                c0 = t[0]
                if (
                    (last_pos in word_ch and (c0 in word_ch or c0 in quoted))
                    or (last_pos in quoted and c0 in word_ch)
                    or (last_op and c0 not in not_op and inv_slot.get(ti))
                ):
                    out.append(' ')
            out.append(t)
            last_pos = t[-1]
            last_op = last_pos not in not_op
        return ''.join(out)

    li_first_function = min(f.li0 for f in func_list.values())
    out_l = []
    for li, lin in enumerate(line_list):
        if li == li_endglobals_:
            for v in V_S:
                out_l.append('string array %s' % v)
            out_l.append('integer array %s' % V_I)
            out_l.append('string array %s' % V_T)
            out_l.append('hashtable %s=InitHashtable()' % H_ALF)
            if name_table:
                out_l.append('hashtable %s=InitHashtable()' % H_NAME)
            out_l.append('endglobals')
            continue
        if li == li_first_function:
            out_l.extend(new_pieces(locals()))
        if not lin:
            continue
        f = owner[li]
        if li == li_first:
            out_l.append('call %s()' % F_INI)
        if li in outside_globals:
            g = by_line[li]
            init_pos = lin.index(g['begin'][0]) - 1
            txt = emit(lin, None, skip_init=init_pos)
            if txt.startswith('constant '):
                txt = txt[len('constant '):]
            out_l.append(txt)
            continue
        out_l.append(emit(lin, f))

    out_text = '\n'.join(out_l) + '\n'
    open(output, 'wb').write(out_text.encode('utf-8', 'surrogateescape'))
    print('strings: %d ocorrencia(s) de %d literal(is), %d pieces (%d distinct); rawcodes: %d ocorrencia(s) de %d'
          % (str_uses, len(str_list), n_pieces, len(table), raw_uses, len(raw_list)))
    print('names: %d functions, %d globals, %d locals/parameters; converted globals: %d; frozen: %d tokens'
          % (len(fmap), len(gmap), sum(len(f.new_ones) for f in func_list.values()), len(converted), len(frozen)))
    print('output: %s (%d B, %d lines) in %.1fs' % (output, len(out_text.encode('utf-8', 'surrogateescape')),
                                                     len(out_l), time.time() - t0))
    map_path = arg('map_path')
    if map_path:
        json.dump({'seed': seed, 'func_list': fmap, 'globals_block': gmap,
                   'local_vars': dict((f.fname, f.new_ones) for f in func_list.values() if f.new_ones),
                   'piece_list': {'string_vectors': V_S, 'rawcode_vector': V_I, 'table': V_T, 'decrypt': F_D,
                                  'decrypt_rawcode': F_R, 'initialize': F_INI, 'dynamic_name': F_NAME}},
                  open(map_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
        print('symbol map: %s' % map_path)
    verif = arg('verification')
    if verif:
        write_verification(verif, str_list, raw_list, rawval, ref_s, ref_r, name_table, fmap, patterns, F_NAME)
    pj = arg('pjass')
    if pj:
        return run_pjass(pj, common, blizz, output)
    return 0


def jass_value(c):
    esc = {'\\': '\\', '"': '"', 'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f'}
    return re.sub(r'\\(.)', lambda m: esc.get(m.group(1), m.group(1)), c, flags=re.S)


def lua_lit(s):
    out = []
    for b in s.encode('utf-8', 'surrogateescape'):
        ch = chr(b)
        if 32 <= b < 127 and ch not in '"\\':
            out.append(ch)
        else:
            out.append('\\%03d' % b)
    return '"%s"' % ''.join(out)


def write_verification(file_path, str_list, raw_list, rawval, ref_s, ref_r, name_table, fmap, patterns, F_NAME):
    line_list = ['__esp = { s = {}, r = {}, nomes = {}, fn = %s }' % lua_lit(F_NAME)]
    for c in str_list:
        line_list.append('__esp.s[#__esp.s + 1] = { %s, %s }' % (lua_lit(ref_s(c)), lua_lit(jass_value(c))))
    for c in raw_list:
        line_list.append(
            '__esp.r[#__esp.r + 1] = { %s, %d }'
            % (lua_lit(ref_r(c)), rawval(c) - (1 << 32) if rawval(c) >= (1 << 31) else rawval(c))
        )
    for orig, new in fmap.items():
        if any(orig.startswith(pa) and orig.endswith(su) for pa, su in patterns):
            line_list.append('__esp.nomes[#__esp.nomes + 1] = { %s, %s }' % (lua_lit(orig), lua_lit(new)))
    open(file_path, 'w', encoding='utf-8').write('\n'.join(line_list) + '\n')
    print('verification: %s (%d strings, %d rawcodes, %d dynamic names)'
          % (file_path, len(str_list), len(raw_list), len(name_table)))


def hash_groups(name_table):
    n_by_hash = collections.Counter()
    output = []
    for orig, new in name_table:
        h = sstrhash.hybrid_stringhash(orig, True)
        output.append((orig, new, 2 * n_by_hash[h]))
        n_by_hash[h] += 1
    return output


def name_collisions(name_table):
    by_hash = collections.defaultdict(list)
    for orig, _ in name_table:
        by_hash[sstrhash.hybrid_stringhash(orig, True)].append(orig)
    return [g for g in by_hash.values() if len(g) > 1]


def new_pieces(L):
    F_D, F_R, F_INI, F_NAME = L['F_D'], L['F_R'], L['F_INI'], L['F_NAME']
    V_T, V_I, H_ALF, H_NAME = L['V_T'], L['V_I'], L['H_ALF'], L['H_NAME']
    ger, rng, block_entry = L['ger'], L['rng'], L['block_entry']
    step, table, alf = L['step'], L['table'], L['alf']
    a1, b1, a2, b2 = L['a1'], L['b1'], L['a2'], L['b2']
    str_list, raw_list, cipher, encrypt_raw = L['str_list'], L['raw_list'], L['cipher'], L['encrypt_raw']
    ref_s, ref_r = L['ref_s'], L['ref_r']
    name_table, converted, gmap, texts, kinds = L['name_table'], L['converted'], L['gmap'], L['texts'], L['kinds']
    n = ger.new
    out = []
    u = set()
    e, x, p, v, r, c, m, q, t, h = [n(3, 9, u) for _ in range(10)]
    one = ['if %s<0 then' % v,
           'set %s=%s+%d' % (v, v, MODULUS),
           'endif',
           'set %s=%s+%s[%s]' % (c, c, V_T, v),
           'set %s=%s+%d' % (x, x, step),
           'if %s>=%d then' % (x, MODULUS),
           'set %s=%s-%d' % (x, x, MODULUS),
           'endif']
    out += ['function %s takes integer %s,string %s returns string' % (F_D, x, e),
            'local integer %s=StringLength(%s)' % (q, e),
            'local integer %s=0' % p,
            'local integer %s' % v,
            'local integer %s' % t,
            'local integer %s' % h,
            'local string %s=""' % r,
            'local string %s=""' % c,
            'local integer %s=0' % m,
            'loop',
            'exitwhen %s>=%s' % (p, q),
            'set %s=S2I(SubString(%s,%s,%s+%d))' % (t, e, p, p, 2 * WIDTH),
            'set %s=%s/%d' % (h, t, 10 ** WIDTH),
            'set %s=%s-%s' % (v, h, x)] + one + [
            'set %s=%s-%s*%d-%s' % (v, t, h, 10 ** WIDTH, x)] + one + [
            'set %s=%s+%d' % (p, p, 2 * WIDTH),
            'set %s=%s+1' % (m, m),
            'if %s==8 then' % m,
            'set %s=%s+%s' % (r, r, c),
            'set %s=""' % c,
            'set %s=0' % m,
            'endif',
            'endloop',
            'return %s+%s' % (r, c),
            'endfunction']
    u = set()
    k, e2, i, hi, lo, a, b = [n(3, 9, u) for _ in range(7)]
    out += ['function %s takes integer %s,string %s returns integer' % (F_R, k, e2),
            'local integer %s=0' % i,
            'local integer %s=0' % hi,
            'local integer %s=0' % lo,
            'local integer %s=%s*%d+%d' % (a, k, a1, b1),
            'local integer %s=%s*%d+%d' % (b, k, a2, b2),
            'set %s=%s-(%s/65536)*65536' % (a, a, a),
            'set %s=%s-(%s/65536)*65536' % (b, b, b),
            'loop',
            'exitwhen %s>=4' % i,
            'set %s=%s*36+LoadInteger(%s,0,StringHash(SubString(%s,%s,%s+1)))' % (hi, hi, H_ALF, e2, i, i),
            'set %s=%s*36+LoadInteger(%s,0,StringHash(SubString(%s,%s+4,%s+5)))' % (lo, lo, H_ALF, e2, i, i),
            'set %s=%s+1' % (i, i),
            'endloop',
            'set %s=%s-%s' % (hi, hi, a),
            'if %s<0 then' % hi,
            'set %s=%s+65536' % (hi, hi),
            'endif',
            'set %s=%s-%s' % (lo, lo, b),
            'if %s<0 then' % lo,
            'set %s=%s+65536' % (lo, lo),
            'endif',
            'if %s>=32768 then' % hi,
            'return (%s-65536)*65536+%s' % (hi, lo),
            'endif',
            'return %s*65536+%s' % (hi, lo),
            'endfunction']
    if name_table:
        u = set()
        s, h = n(3, 9, u), n(3, 9, u)
        if name_collisions(name_table):
            k = n(3, 9, u)
            out += ['function %s takes string %s returns string' % (F_NAME, s),
                    'local integer %s=StringHash(%s)' % (h, s),
                    'local integer %s=0' % k,
                    'loop',
                    'exitwhen not HaveSavedString(%s,%s,%s+1)' % (H_NAME, h, k),
                    'if LoadStr(%s,%s,%s+1)==%s then' % (H_NAME, h, k, s),
                    'return LoadStr(%s,%s,%s)' % (H_NAME, h, k),
                    'endif',
                    'set %s=%s+2' % (k, k),
                    'endloop',
                    'return %s' % s,
                    'endfunction']
        else:
            out += ['function %s takes string %s returns string' % (F_NAME, s),
                    'local integer %s=StringHash(%s)' % (h, s),
                    'if HaveSavedString(%s,%s,1) then' % (H_NAME, h),
                    'if LoadStr(%s,%s,1)==%s then' % (H_NAME, h, s),
                    'return LoadStr(%s,%s,0)' % (H_NAME, h),
                    'endif',
                    'endif',
                    'return %s' % s,
                    'endfunction']
    block_list = []

    def new_block(lines_):
        fname = n(10, 16)
        block_list.append(fname)
        out.append('function %s takes nothing returns nothing' % fname)
        out.extend(lines_)
        out.append('endfunction')

    lt = []
    for idx, piece in enumerate(table):
        lt.append('set %s[%d]="%s"' % (V_T, idx, piece))
        if len(lt) >= 4000:
            new_block(lt)
            lt = []
    if lt:
        new_block(lt)
    la = ['call SaveInteger(%s,0,StringHash("%s"),%d)' % (H_ALF, ch, alf.index(ch)) for ch in alf]
    lr = list(la)
    for c in raw_list:
        lr.append('set %s=%s' % (ref_r(c), encrypt_raw(c)))
        if len(lr) >= 800:
            new_block(lr)
            lr = []
    if lr:
        new_block(lr)
    ls = []
    custo = 0
    for c in str_list:
        ls.append('set %s=%s' % (ref_s(c), cipher(c)))
        custo += len(L['pieces_of'][c]) + 4
        if custo >= block_entry:
            new_block(ls)
            ls = []
            custo = 0
    if ls:
        new_block(ls)
    txt_ln = []
    for orig, nv, slot in hash_groups(name_table):
        txt_ln.append('call SaveStr(%s,StringHash(%s),%d,"%s")' % (H_NAME, ref_s(orig), slot, nv))
        txt_ln.append('call SaveStr(%s,StringHash(%s),%d,%s)' % (H_NAME, ref_s(orig), slot + 1, ref_s(orig)))
        if len(txt_ln) >= 3000:
            new_block(txt_ln)
            txt_ln = []
    if txt_ln:
        new_block(txt_ln)
    lg = []
    for fname, ti in converted.items():
        tgt = gmap.get(fname, fname)
        c = texts[ti][1:-1]
        lg.append('set %s=%s' % (tgt, ref_s(c) if kinds[ti] == 'str' else ref_r(c)))
    if lg:
        new_block(lg)
    out.append('function %s takes nothing returns nothing' % F_INI)
    for b_ in block_list:
        out.append('call ExecuteFunc("%s")' % b_)
    out.append('endfunction')
    return out


def run_pjass(pj, common, blizz, output):
    tmp = output + '.pjass_lf.j'
    t = open(output, 'rb').read().replace(b'\r\n', b'\n').replace(b'\r', b'\n')
    open(tmp, 'wb').write(t)
    r = subprocess.run([pj, common, blizz, tmp], capture_output=True, text=True, encoding='utf-8', errors='replace')
    os.remove(tmp)
    txt = (r.stdout or '') + (r.stderr or '')
    line_list = [lx for lx in txt.splitlines() if lx.strip()]
    for lx in line_list[-15:]:
        print('  pjass: ' + lx)
    invalid = r.returncode != 0 or any(
        ('error' in lx.lower() or 'warning' in lx.lower()) and 'Parse successful' not in lx for lx in line_list
    )
    print('pjass: %s' % ('FAIL' if invalid else 'PASS'))
    return 1 if invalid else 0


if __name__ == '__main__':
    sys.exit(main())
