# The protection recipe: each step on its own copy of the map, every file checked after it.
import hashlib
import os
import re
import shutil
import sys
import time


HERE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
DEFAULT_REF = next((p for p in (os.path.join(ARCHIVE_ROOT, 'common', 'ref', '3.0'), os.path.join(HERE, 'ref', '3.0'))
                    if os.path.isfile(os.path.join(p, 'common.j'))), os.path.join(ARCHIVE_ROOT, 'common', 'ref', '3.0'))
STEPS = ('shuffle', 'lua', 'dds', 'obfuscate', 'slk', 'lock_editor', 'decoy', 'protect', 'bulk', 'cut_step')
NO_CONTENTS = ('(listfile)', '(attributes)', '(signature)')


def sha(file_path):
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def contents(file_path, name_list=None):
    import editor_lock
    import mpqread
    a = mpqread.Archive(file_path)
    out = {}
    listing = list(editor_lock.map_names(a)) + list(name_list or ())
    for n in listing:
        k = n.lower()
        if k in NO_CONTENTS or k in out:
            continue
        d = editor_lock._read(a, n)
        if d is not None:
            out[k] = d
    return out


def _digest_of(v):
    return v if isinstance(v, tuple) else (len(v), hashlib.blake2b(v, digest_size=16).digest())


def _size_of(v):
    return None if v is None else v[0] if isinstance(v, tuple) else len(v)


def difference(before, after_diag):
    out = {}
    for n in set(before) | set(after_diag):
        x, y = before.get(n), after_diag.get(n)
        if x == y:
            continue
        if x is None or y is None:
            out[n] = (_size_of(x), _size_of(y), None)
        elif isinstance(x, tuple) or isinstance(y, tuple):
            rx, ry = _digest_of(x), _digest_of(y)
            if rx != ry:
                out[n] = (rx[0], ry[0], None if rx[0] == ry[0] else abs(ry[0] - rx[0]))
        else:
            chg = (sum(1 for p, q in zip(x, y) if p != q) if len(x) == len(y) else abs(len(y) - len(x)))
            out[n] = (len(x), len(y), chg)
    return out


class _Stages(dict):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._order = list(self)
        self._digested = set()

    def __setitem__(self, hash_key, field_value):
        if hash_key in self._order:
            self._order.remove(hash_key)
        self._order.append(hash_key)
        self._digested.discard(hash_key)
        dict.__setitem__(self, hash_key, field_value)
        for old in self._order[:-2]:
            if old not in self._digested:
                dict.__setitem__(self, old, dict((n, _digest_of(v)) for n, v in dict.__getitem__(self, old).items()))
                self._digested.add(old)


def count_pjass(body_text):
    m = re.search(r'errors:\s*(\d+)\s+warnings:\s*(\d+)', body_text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def run_action(cmd, verbose):
    import contextlib
    import importlib
    import io
    kk = os.path.join(ARCHIVE_ROOT, 'common', 'kk')
    script = os.path.basename(str(cmd[1]))
    argv = [str(a) for a in cmd[2:]]
    modname = {'jass_obfuscate.py': 'jass_obfuscate', 'pjass.py': 'pjass'}.get(script)
    if modname is None:
        raise SystemExit('run: unexpected script in process: %r' % script)
    mod = importlib.import_module(modname)
    out = io.StringIO()
    old = sys.argv
    sys.argv = [script] + argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            try:
                code_part = mod.main(argv) if modname == 'pjass' else mod.main()
                code_part = int(code_part or 0)
            except SystemExit as e:
                code_part = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
                if e.code is not None and not isinstance(e.code, int):
                    out.write(str(e.code) + '\n')
    finally:
        sys.argv = old
    output = out.getvalue()
    if verbose:
        print(output.rstrip())
    return code_part, output


def pjass_run(script, ref, tmp, verbose):
    os.makedirs(tmp, exist_ok=True)
    code_part, output = run_action(
        [
            sys.executable,
            os.path.join(ARCHIVE_ROOT, 'common', 'kk', 'pjass.py'),
            '--root=' + tmp,
            '--j=' + script,
            '--ref=' + ref,
            '--tmp=' + os.path.join(tmp, '_pjass'),
        ],
        verbose,
    )
    return count_pjass(output), output


def same_file(a, b):
    return os.path.normcase(os.path.realpath(os.path.abspath(a))) == os.path.normcase(
        os.path.realpath(os.path.abspath(b))
    )


def _mark(p):
    try:
        st = os.stat(p)
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


def _inside(p, folder):
    a = os.path.normcase(os.path.realpath(os.path.abspath(p)))
    b = os.path.normcase(os.path.realpath(os.path.abspath(folder)))
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def _check_paths(entry, output, tmp, tsv, backup):
    tmp = os.path.abspath(tmp)
    if os.path.dirname(tmp) == tmp:
        raise SystemExit('the work folder cannot be the root of a drive (%s)' % tmp)
    for fname, p in (('the input', entry), ('the output', output), ('the key', tsv), ('the backup', backup),
                     ('the protector code', HERE)):
        if p and _inside(p, tmp):
            raise SystemExit('the work folder %s contains %s (%s) and is deleted at the start and at the end'
                             % (tmp, fname, p))
    if tsv and (same_file(tsv, entry) or same_file(tsv, output)):
        raise SystemExit('the key must be another file, not the input nor the output (%s)' % tsv)
    if backup:
        copy = os.path.join(backup, os.path.basename(entry))
        for fname, p in (('the input', entry), ('the output', output), ('the key', tsv)):
            if p and same_file(copy, p):
                raise SystemExit('the backup copy (%s) would land on %s' % (copy, fname))


def _deliver(tmp_folder, dest):
    done_list = []
    if not os.path.isdir(tmp_folder):
        return done_list
    for f in sorted(os.listdir(tmp_folder)):
        src = os.path.join(tmp_folder, f)
        if not os.path.isfile(src):
            continue
        os.makedirs(dest, exist_ok=True)
        dst = os.path.join(dest, f)
        try:
            os.replace(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
            os.remove(src)
        done_list.append(dst)
    return done_list


def _decoy_of_list(steps):
    p = next((p for p in steps if p.get('step') == 'decoy'), {})
    return any(
        n == '(listfile)' and x.get('action_code') == 'substituted' for n, x in (p.get('decoy_matrix') or {}).items()
    )


ART = ('.blp', '.tga', '.wav')


def _check_art(d, step):
    outside = sorted(n for n in d if not n.lower().endswith(ART))
    if outside:
        raise SystemExit('ABORT at step %s: the content of %s changed (only the art may change)' % (step, outside[:5]))


def _shrink_summary(res, level=''):
    lo = res.get('lossy') or {}
    with_loss = ''
    if lo.get('state') == 'done' and not lo.get('error'):
        with_loss = '; lossy: %d texture(s) at half size, %d sound(s) mono 22 kHz' % (lo.get('textures') or 0,
                                                                                      lo.get('sounds') or 0)
    return '%srepacked with %d KB sectors, %.1f -> %.1f MiB%s' % (
        level, (res.get('sector_after') or 0) >> 10, (res.get('size_before') or 0) / 1048576.0,
        (res.get('size_after') or 0) / 1048576.0, with_loss)


def _smaller_art(entry, output, optimization, pack_file, tmp):
    import shrink
    if not optimization.get('lossy') or os.path.getsize(output) <= shrink.LIMIT:
        return None
    smaller = os.path.join(tmp, 'optimize_art.w3x')
    lo = shrink.lossy(entry, smaller, os.path.getsize(output) - shrink.LOSSY_TARGET)
    if lo['state'] != 'done':
        return {'map_path': None, 'summary': 'the pack is above 512 MiB and the art was not made smaller: %s'
                                             % (lo.get('error') or 'nothing could be made smaller')}
    pack_file(smaller)
    summary = 'lossy (the pack was above 512 MiB): %d texture(s) at half size, %d sound(s) mono 22 kHz' % (
        lo['textures'], lo['sounds'])
    if os.path.getsize(output) > shrink.LIMIT:
        summary += '; still above 512 MiB: the game will not open it'
    return {'map_path': smaller, 'summary': summary}


def _guard(fn, entry, output, kw):
    if same_file(entry, output):
        raise SystemExit('the output must be another file (the input never changes)')
    output_abs = os.path.abspath(output)
    tmp = os.path.abspath(kw.get('tmp') or output_abs + '.work')
    tsv = os.path.abspath(
        kw.get('tsv') or os.path.splitext(output_abs)[0] + ('_ids' if fn is _campaign else '_ids.tsv')
    )
    backup = None if kw.get('backup') is None else os.path.abspath(kw['backup'] or output_abs + '.backup')
    _check_paths(entry, output_abs, tmp, tsv, backup)
    before = _mark(output_abs)
    try:
        return fn(entry, output, **kw)
    except BaseException:
        if os.path.isfile(output_abs) and _mark(output_abs) != before:
            try:
                os.remove(output_abs)
            except OSError:
                pass
        raise
    finally:
        if not kw.get('retains'):
            shutil.rmtree(tmp, ignore_errors=True)


def recipe(entry, output, **kw):
    return _guard(_recipe, entry, output, kw)


def campaign(entry, output, **kw):
    return _guard(_campaign, entry, output, kw)


def _recipe(
    entry,
    output,
    skip=(),
    lock_editor=('w3i', 'wtg', 'extra', 'units', 'doo'),
    force_flag=False,
    keep_names=(),
    seed=None,
    tsv=None,
    blp=False,
    lua_layers=2,
    decoys=(),
    variant=(),
    non_ascii_ids=False,
    optimization=None,
    convert_dds=False,
    convert_slk=False,
    slk_game=None,
    slk_txt='full',
    slk_max_level=None,
    ref=None,
    backup=None,
    tmp=None,
    retains=False,
    verbose=False,
    previous=None,
    log=print,
    clean=True,
    convert_lua=False,
    bulk=None,
    cut_step=False,
):
    import editor_lock
    import id_shuffle
    import mpqadd
    import mpqread
    import lua_obfuscate
    import sector_pack
    skip = set(skip)
    unknown_steps = skip - set(STEPS)
    if unknown_steps:
        raise SystemExit('unknown step in --skip: %s (valid: %s)' % (sorted(unknown_steps), ', '.join(STEPS)))
    mechanisms = set(lock_editor)
    valid_ids = {'w3i', 'wtg', 'w3r', 'extra', 'units', 'doo'}
    if mechanisms - valid_ids:
        raise SystemExit(
            'unknown mechanism in --block: %s (valid: %s)'
            % (sorted(mechanisms - valid_ids), ', '.join(sorted(valid_ids)))
        )
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if same_file(entry, output):
        raise SystemExit('the output must be another file (the input never changes)')
    ref = ref or DEFAULT_REF
    tmp = os.path.abspath(tmp or output + '.work')
    tsv = os.path.abspath(tsv or os.path.splitext(output)[0] + '_ids.tsv')
    _check_paths(entry, output, tmp, tsv, None if backup is None else os.path.abspath(backup or output + '.backup'))
    if mpqadd.format(entry) != 0:
        raise SystemExit('ABORT: the MPQ header of this map is not a normal MPQ v1 header (a map already protected by '
                         'another tool?): use the original map, as the World Editor saves it')
    if previous:
        previous = os.path.abspath(previous)
        if 'shuffle' in skip:
            log('[shuffle] --previous-key ignored: the shuffle step was skipped')
            previous = None
        else:
            id_shuffle.read_previous(previous)
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    tmp_key = os.path.join(tmp, '_key')
    os.makedirs(tmp_key)
    details = {'entry': entry, 'output': output, 'sha256_entry': sha(entry), 'skipped': sorted(skip), 'steps': [],
               'ok': False}
    silent = (lambda *a: None) if not verbose else log
    if backup is not None:
        folder = os.path.abspath(backup or output + '.backup')
        os.makedirs(folder, exist_ok=True)
        copy = os.path.join(folder, os.path.basename(entry))
        shutil.copyfile(entry, copy)
        if sha(copy) != details['sha256_entry']:
            raise SystemExit('the backup does not match the input (%s)' % copy)
        details['backup'] = copy
        log('backup: %s (sha256 checked)' % copy)
    current = os.path.join(tmp, '0_input.w3x')
    shutil.copyfile(entry, current)
    stages = _Stages({'entry': contents(current)})
    ref_names = list(stages['entry'])
    last = 'entry'

    def on_close(fname, status, t0, before, after_diag, extra=None):
        d = difference(stages[before], stages[after_diag]) if before in stages and after_diag in stages else {}
        p = {'step': fname, 'status': status, 'seconds': round(time.time() - t0, 1), 'files_changed': len(d),
             'detail': dict((k, list(v)) for k, v in sorted(d.items()))}
        p.update(extra or {})
        details['steps'].append(p)
        log('[%s] %s in %.1fs; %d file(s) changed%s' % (fname, status, p['seconds'], len(d),
                                                        ('; ' + p['summary']) if p.get('summary') else ''))
        return p

    def next_steps(fname):
        return os.path.join(tmp, '%d_%s.w3x' % (STEPS.index(fname) + 1, fname))

    if 'shuffle' in skip:
        details['steps'].append({'step': 'shuffle', 'status': 'skipped'})
        log('[shuffle] skipped')
    else:
        t0 = time.time()
        new = next_steps('shuffle')
        r = id_shuffle.shuffle(current, new, tsv=os.path.join(tmp_key, os.path.basename(tsv)), seed=seed,
                               keep_names=keep_names, non_ascii=non_ascii_ids, previous=previous, log=silent)
        if not r['ok']:
            raise SystemExit('ABORT at step shuffle: the self-check failed (%s)' % new)
        stages['shuffle'] = contents(new, ref_names)
        prev_item = r.get('previous')
        if prev_item:
            log('[shuffle] previous key: %d reused, %d new, %d without reuse%s'
                % (prev_item['reused'], prev_item['new_drawn'], len(prev_item['no_reuse']),
                   ''.join('\n  no reuse %s: %s' % kv for kv in list(prev_item['no_reuse'].items())[:20])))
        on_close(
            'shuffle',
            'ok',
            t0,
            last,
            'shuffle',
            {
                'ids_swapped': r['replaced'],
                'ids_kept': len(r['kept']),
                'hash_key': tsv,
                'open_graph': r.get('open_graph'),
                'orphans': r.get('orphans'),
                'previous': prev_item,
                'not_interpreted': dict((n, x['not_interpreted']) for n, x in r['matrix'].items()),
                'summary': '%d ids swapped, %d kept, graph closed, key in %s%s'
                % (
                    r['replaced'],
                    len(r['kept']),
                    tsv,
                    (
                        '; from the previous key: %d reused, %d new, %d without reuse'
                        % (prev_item['reused'], prev_item['new_drawn'], len(prev_item['no_reuse']))
                    )
                    if prev_item
                    else '',
                ),
            },
        )
        current, last = new, 'shuffle'

    if convert_lua and 'lua' not in skip:
        t0 = time.time()
        import jass_to_lua
        a = mpqread.Archive(current)
        j_name, script_j = editor_lock._script(a)
        if editor_lock._read(a, 'war3map.lua') is not None or script_j is None or j_name.lower().endswith('.lua'):
            why = 'the map is already Lua' if script_j is not None else 'no war3map.j'
            details['steps'].append({'step': 'lua', 'status': 'skipped (%s)' % why})
            log('[lua] skipped: %s' % why)
        else:
            owned = jass_to_lua.map_blizzard(lambda n: editor_lock._read(a, n))
            if owned:
                raise SystemExit(
                    'ABORT at step lua: the map has its own %s; in Lua mode the game does not read it, and its '
                    'functions would be gone' % owned
                )
            lua, r = jass_to_lua.converte(script_j.decode('utf-8', 'surrogateescape'), ref=ref, log=silent)
            waits = r.get('waits_in_callbacks') or {}
            warning = ('; WARNING: %d function(s) with a wait called back outside the trigger thread (%s): JASS '
                       'ignores that wait, in Lua it can stop the function' % (
                         len(waits), ', '.join('%s by %s' % (f, '/'.join(v)) for f, v in list(waits.items())[:4]))
                       if waits else '')
            if warning:
                log('[lua] ' + warning[2:])
            if not r['ok']:
                raise SystemExit('ABORT at step lua: %s' % '; '.join(str(v) for v in r['gates'].values()))
            new_w3i, w3i_reason = jass_to_lua.w3i_lua(editor_lock._read(a, 'war3map.w3i'))
            new = next_steps('lua')
            shutil.copyfile(current, new)
            lua_bytes = lua.encode('utf-8', 'surrogateescape')
            mpqadd.add_files(new, [('war3map.lua', lua_bytes), ('war3map.w3i', new_w3i)], to_delete=[j_name],
                             log=lambda *x: None)
            b = mpqread.Archive(new)
            if b.read('war3map.lua') != lua_bytes or b.read('war3map.w3i') != new_w3i or \
                    editor_lock._read(b, j_name) is not None:
                raise SystemExit('ABORT at step lua: the war3map.lua/w3i written is not the converted one')
            if 'war3map.lua' not in [x.lower() for x in ref_names]:
                ref_names.append('war3map.lua')
            stages['lua'] = contents(new, ref_names)
            outside = set(difference(stages[last], stages['lua'])) - {j_name.lower(), 'war3map.lua', 'war3map.w3i'}
            if outside:
                raise SystemExit('ABORT at step lua: something else changed (%s)' % ', '.join(sorted(outside)))
            on_close('lua', 'ok', t0, last, 'lua', {
                'gates': r['gates'],
                'waits_in_callbacks': waits,
                'summary': '%s -> war3map.lua (%d B); w3i: %s; %s%s' % (
                    j_name, len(lua_bytes), w3i_reason, '; '.join(str(v) for v in r['gates'].values()), warning)})
            current, last = new, 'lua'

    if convert_dds and 'dds' not in skip:
        t0 = time.time()
        new = next_steps('dds')
        import dds_to_blp
        r = dds_to_blp.converte(current, new, log=silent)
        if not r['ok']:
            raise SystemExit('ABORT at step dds: %s' % r.get('gate'))
        for _n, _x in r['matrix'].items():
            if _x.get('action_code') == 'converted_file' and _x.get('new'):
                old, new_name = _n.lower(), _x['new'].lower()
                ref_names = [new_name if x.lower() == old else x for x in ref_names]
                if new_name not in [x.lower() for x in ref_names]:
                    ref_names.append(new_name)
        stages['dds'] = contents(new, ref_names)
        on_close('dds', 'ok', t0, last, 'dds', {'summary': '%d .dds -> .blp' % r['replaced']})
        current, last = new, 'dds'

    script_before = None
    if 'obfuscate' in skip:
        details['steps'].append({'step': 'obfuscate', 'status': 'skipped'})
        log('[obfuscate] skipped')
    else:
        t0 = time.time()
        a = mpqread.Archive(current)
        lua = editor_lock._read(a, 'war3map.lua')
        fname, script = ('war3map.lua', lua) if lua else editor_lock._script(a)
        script_before = script
        if script is not None and fname.endswith('.lua'):
            r = lua_obfuscate.obfuscate(script, layers=lua_layers, log=silent)
            new = next_steps('obfuscate')
            shutil.copyfile(current, new)
            obfuscated = r['output'].encode('utf-8', 'surrogateescape')
            mpqadd.add_files(new, [(fname, obfuscated)], log=lambda *x: None)
            if mpqread.Archive(new).read(fname) != obfuscated:
                raise SystemExit('ABORT at step obfuscate: the script written in the map is not the obfuscated one')
            stages['obfuscate'] = contents(new, ref_names)
            on_close('obfuscate', 'ok', t0, last, 'obfuscate', {
                'script': fname, 'bytes_before': r['bytes_before'], 'bytes_after': r['bytes_after'],
                'names_swapped': r['names_swapped'], 'strings_encrypted': r['strings_encrypted'],
                'layers': [{'seed': m['seed'], 'hash_key': m['hash_key']} for m in r['layers']],
                'gates': r['gates'],
                'summary': '%s %d -> %d B; %d name(s), %d string(s), %d layer(s); %s' % (
                    fname, r['bytes_before'], r['bytes_after'], r['names_swapped'], r['strings_encrypted'],
                    len(r['layers']), '; '.join(r['gates'].values()))})
            current, last = new, 'obfuscate'
        elif script is None or b'function main' not in script:
            why = ('no script in the map' if script is None else
                   'the war3map.j (%d B) has no `function main`: the real script is not in it' % len(script))
            details['steps'].append({'step': 'obfuscate', 'status': 'skipped (%s)' % why})
            log('[obfuscate] skipped: %s' % why)
        else:
            entry_j = os.path.join(tmp, 'war3map_original.j')
            output_j = os.path.join(tmp, 'war3map_obfuscated.j')
            with open(entry_j, 'wb') as f:
                f.write(script)
            before_pj, _s = pjass_run(entry_j, ref, os.path.join(tmp, 'pj_before'), verbose)
            code_part, body_text = run_action(
                [
                    sys.executable,
                    os.path.join(HERE, 'jass_obfuscate.py'),
                    '--j=' + entry_j,
                    '--output=' + output_j,
                    '--common=' + os.path.join(ref, 'common.j'),
                    '--blizzard=' + os.path.join(ref, 'blizzard.j'),
                    '--map_path=' + os.path.join(tmp, 'obfuscate_map.json'),
                    '--verification=' + os.path.join(tmp, 'obfuscate_check.lua'),
                ],
                verbose,
            )
            if code_part:
                raise SystemExit(
                    'ABORT at step obfuscate (code %d): %s'
                    % (code_part, (body_text.strip().splitlines() or ['no output'])[-1][:200])
                )
            after_pj, _s = pjass_run(output_j, ref, os.path.join(tmp, 'pj_after'), verbose)
            gate = 'pjass did not run'
            if before_pj is not None and after_pj is not None:
                if after_pj[0] > before_pj[0] or sum(after_pj) > sum(before_pj):
                    raise SystemExit(
                        'ABORT at step obfuscate: pjass finds %s in the obfuscated one and %s in the original'
                        % (after_pj, before_pj)
                    )
                gate = 'pjass original=%s obfuscated=%s (errors, warnings)' % (before_pj, after_pj)
            new = next_steps('obfuscate')
            shutil.copyfile(current, new)
            with open(output_j, 'rb') as f:
                obfuscated = f.read()
            mpqadd.add_files(new, [(fname, obfuscated)], log=lambda *x: None)
            if mpqread.Archive(new).read(fname) != obfuscated:
                raise SystemExit('ABORT at step obfuscate: the script written in the map is not the obfuscated one')
            stages['obfuscate'] = contents(new, ref_names)
            on_close(
                'obfuscate',
                'ok',
                t0,
                last,
                'obfuscate',
                {
                    'script': fname,
                    'bytes_before': len(script),
                    'bytes_after': len(obfuscated),
                    'pjass_gate': gate,
                    'summary': '%s %d -> %d B; %s' % (fname, len(script), len(obfuscated), gate),
                },
            )
            current, last = new, 'obfuscate'

    if convert_slk and 'slk' not in skip:
        t0 = time.time()
        import obj2slk
        import objects as _ob_slk
        import slk_objects as _so_slk
        a = mpqread.Archive(current)
        _le_slk = lambda n: editor_lock._read(a, n)
        try:
            base_slk = _ob_slk.GameBase(game=slk_game, balance=_so_slk.balance_of(_le_slk('war3map.w3i')))
        except Exception as e:
            raise SystemExit(
                'ABORT at step slk: the game tables are needed and could not be read (%s). On '
                'Windows the installed Warcraft III is found on its own; on Linux pass --game=<folder of the '
                'Warcraft III>' % str(e)[:90]
            )
        slk_rep = obj2slk.convert(_le_slk, base_slk, list(ref_names), txt=slk_txt,
                                  max_level=slk_max_level or obj2slk.MAX_LEVEL)
        if not slk_rep['files']:
            why = '; '.join('%s: %s' % kv for kv in slk_rep['skipped'].items()) or 'nothing to convert'
            details['steps'].append({'step': 'slk', 'status': 'skipped (%s)' % why})
            log('[slk] skipped: %s' % why)
        else:
            new = next_steps('slk')
            shutil.copyfile(current, new)
            arquivos_slk = list(slk_rep['files'])
            lf = _le_slk('(listfile)')
            if lf is not None:
                present = set(x.strip().replace('/', '\\').lower()
                              for x in lf.decode('utf-8', 'surrogateescape').splitlines())
                missing_items = [n for n, _b in arquivos_slk if n.lower() not in present]
                if missing_items:
                    sep = b'' if not lf or lf.endswith(b'\n') else b'\r\n'
                    arquivos_slk.append(('(listfile)', lf + sep
                                         + '\r\n'.join(missing_items).encode('utf-8', 'surrogateescape') + b'\r\n'))
            mpqadd.add_files(new, arquivos_slk, grow=list(ref_names), log=lambda *x: None)
            b = mpqread.Archive(new)
            for n, by in slk_rep['files']:
                if n != '(listfile)' and editor_lock._read(b, n) != by:
                    raise SystemExit('ABORT at step slk: the table %s written is not the converted one' % n)
            for n, _b in arquivos_slk:
                if n.lower() not in [x.lower() for x in ref_names]:
                    ref_names.append(n)
            stages['slk'] = contents(new, ref_names)
            summary = '; '.join('%s: %d new, %d changed, %d left in the object file'
                                % (s, x.get('new', 0), x.get('originals', 0), x['objects_left'])
                                for s, x in slk_rep['report'].items())
            skipped = '; '.join('%s skipped (%s)' % kv for kv in slk_rep['skipped'].items())
            on_close('slk', 'ok', t0, last, 'slk', {
                'report': slk_rep['report'], 'skipped': slk_rep['skipped'], 'balance': base_slk.balance,
                'summary': 'object data -> game tables (%s profiles, layer %s); %s%s'
                          % (slk_txt, base_slk.balance, summary, ('; ' + skipped) if skipped else '')})
            current, last = new, 'slk'

    if 'lock_editor' in skip:
        details['steps'].append({'step': 'lock_editor', 'status': 'skipped'})
        log('[lock_editor] skipped')
    else:
        t0 = time.time()
        new = next_steps('lock_editor')
        r = editor_lock.lock_editor(current, new, w3i_='w3i' in mechanisms, wtg='wtg' in mechanisms,
                                    w3r_inflated='w3r' in mechanisms, editor_extra='extra' in mechanisms,
                                    units_doo='units' in mechanisms, doo='doo' in mechanisms, force_flag=force_flag,
                                    trusted_script=script_before, log=silent)
        if not r['ok']:
            raise SystemExit('ABORT at step lock_editor: %s' % r.get('problems'))
        stages['lock_editor'] = contents(new, ref_names)
        done_list = dict(
            (n, x['action_code']) for n, x in r['matrix'].items() if x['action_code'] in ('reworked', 'stripped')
        )
        refusals = dict(
            (n, x['why'])
            for n, x in r['matrix'].items()
            if x['action_code'] == 'not touched'
            and x['why']
            and not x['why'].startswith('the map does not have')
            and not x['why'].startswith('ja ')
        )
        on_close(
            'lock_editor',
            'ok',
            t0,
            last,
            'lock_editor',
            {
                'done_list': done_list,
                'refusals': refusals,
                'not_interpreted': r['not_interpreted'],
                'summary': 'done %s%s' % (done_list or 'nothing', '; REFUSALS %s' % refusals if refusals else ''),
            },
        )
        current, last = new, 'lock_editor'

    if not decoys or 'decoy' in skip:
        details['steps'].append({'step': 'decoy', 'status': 'skipped'})
        if 'decoy' in skip:
            log('[decoy] skipped')
    else:
        t0 = time.time()
        new = next_steps('decoy')
        import decoy_files
        r = decoy_files.decoys(current, new, chosen=tuple(decoys), seed=seed, log=silent)
        if not r['ok']:
            raise SystemExit('ABORT at step decoy: %s' % r.get('gate'))
        stages['decoy'] = contents(new, ref_names)
        done_names = dict((n, x['action_code']) for n, x in r['matrix'].items())
        _decoy_res = '%d decoy(s): %s' % (
            r['written_count'],
            '; '.join('%s %s' % (n, a) for n, a in sorted(done_names.items())),
        )
        if r.get('fill'):
            _decoy_res += '; fill: %s' % r['fill'].get('summary')
        on_close(
            'decoy',
            'ok',
            t0,
            last,
            'decoy',
            {
                'decoy_matrix': r['matrix'],
                'written_count': r['written_count'],
                'fill': r.get('fill'),
                'summary': _decoy_res,
            },
        )
        current, last = new, 'decoy'

    blp_512 = blp
    p_optimize = before_optimize = None
    if optimization is not None:
        optimization = dict(optimization)
        t0 = time.time()
        before_optimize = last
        if 'protect' in skip:
            import shrink
            new = os.path.join(tmp, '6_optimize.w3x')
            log('[optimize] Optimizing the size...')
            res = shrink.shrink(current, new, options=optimization)
            if res.get('state') == 'nothing_to_do':
                shutil.copyfile(current, new)
                summary = 'nothing to gain (already compact)'
            elif res.get('state') != 'done' or not os.path.isfile(new):
                raise SystemExit('ABORT at step optimize: %s' % (res.get('error') or res.get('state')))
            else:
                summary = _shrink_summary(res)
            stages['optimize'] = contents(new, ref_names)
            _check_art(difference(stages[last], stages['optimize']), 'optimize')
            p_optimize = on_close('optimize', 'ok', t0, last, 'optimize', {'summary': summary})
            current, last = new, 'optimize'
        else:
            blp_512 = blp or bool(optimization.get('blp', True))
            stages['optimize'] = stages[last]
            p_optimize = {'step': 'optimize', 'status': 'ok', 'seconds': 0.0, 'files_changed': 0, 'detail': {},
                          'summary': 'in the sector-512 pack: %s' % ('BLP textures rewritten without loss' if blp_512
                                                                     else 'nothing to add (BLP rewrite off)')}
            details['steps'].append(p_optimize)
            log('[optimize] Optimizing the size in the sector-512 pack...')
            last = 'optimize'

    if 'protect' in skip:
        details['steps'].append({'step': 'protect', 'status': 'skipped'})
        log('[protect] skipped')
        if clean and optimization is None and last != 'entry':
            log('[limpa] Dropping the old copies the steps replaced...')
            limpo = os.path.join(tmp, '7_clean.w3x')
            p = _clean_map(current, limpo, False)
            details['steps'].append(p)
            log('[clean] ok: %s' % p['summary'])
            shutil.copyfile(limpo, output)
        else:
            shutil.copyfile(current, output)
    else:
        t0 = time.time()
        drop_listfile = 'extra' in mechanisms and 'lock_editor' not in skip and not _decoy_of_list(details['steps'])

        def pack_file(origin):
            return sector_pack.protect(origin, output, blp=blp_512, orphan_blocks=True, no_listfile=drop_listfile,
                                       variant=tuple(variant))
        pack_file(current)
        smaller = _smaller_art(current, output, optimization, pack_file, tmp) if optimization is not None else None
        if smaller:
            p_optimize['summary'] += '; ' + smaller['summary']
            if smaller['map_path']:
                stages['optimize'] = contents(smaller['map_path'], ref_names)
                d_optimize = difference(stages[before_optimize], stages['optimize'])
                _check_art(d_optimize, 'optimize')
                p_optimize.update({'files_changed': len(d_optimize), 'seconds': round(time.time() - t0, 1),
                                   'detail': dict((k, list(v)) for k, v in sorted(d_optimize.items()))})
                current = smaller['map_path']
        stages['protect'] = contents(output, ref_names)
        d = difference(stages[last], stages['protect'])
        on_close(
            'protect',
            'ok' if (not d or blp_512) else 'CHANGED CONTENT',
            t0,
            last,
            'protect',
            {
                'summary': 'MPQ rewritten (sector 512%s), %d -> %d B'
                % (', lossless BLP' if blp_512 else '', os.path.getsize(current), os.path.getsize(output))
            },
        )
        if d and not blp_512:
            raise SystemExit('ABORT: the mpq_recompress changed the content of %s' % sorted(d)[:5])
    if bulk and 'bulk' not in skip:
        t0 = time.time()
        import decoy_files
        _spec_m = decoy_files.bulk_spec(bulk)
        _rm = decoy_files.bulk(output, bombs=_spec_m['bombs'], slices=_spec_m['slices'], listing=_spec_m['listing'],
                               seed=seed, log=silent)
        details['steps'].append(
            {
                'step': 'bulk',
                'status': 'ok',
                'seconds': round(time.time() - t0, 1),
                'bombs': _rm['bombs'],
                'slices': _rm['slices'],
                'listing': _rm['listing'],
                'claimed': _rm['claimed'],
                'bytes_written': _rm['bytes'],
                'fallback_fdf': _rm['fallback_fdf'],
                'summary': _rm['gate'],
            }
        )
        log('[bulk] %s' % _rm['gate'])
    if cut_step and 'cut_step' not in skip:
        t0 = time.time()
        _rc = {}
        _current_c = os.path.join(tmp, '%d_cut.w3x' % (STEPS.index('cut_step') + 1))
        with open(output, 'rb') as f:
            _b_c = f.read()
        _o_c = sector_pack.cut_hash(_b_c, stats=_rc, log=silent)
        with open(_current_c, 'wb') as f:
            f.write(_o_c)
        os.replace(_current_c, output)
        stages['cut_step'] = contents(output, ref_names)
        on_close(
            'cut_step',
            'ok',
            t0,
            last,
            'cut_step',
            {
                'summary': 'declared hash table %d, physical %d (the read-only '
                'of StormLib); %d -> %d B'
                % (_rc.get('hash_n', 0), _rc.get('physical', 0), _rc.get('entry', 0), _rc.get('output', 0))
            },
        )
        last = 'cut_step'

    if 'fill' in decoys and 'decoy' not in skip:
        t0 = time.time()
        import decoy_files
        _re = decoy_files.fill(output, seed=seed, log=silent)
        details['steps'].append(
            {
                'step': 'fill',
                'status': 'ok',
                'seconds': round(time.time() - t0, 1),
                'fill': dict(
                    (k, _re[k])
                    for k in (
                        'action_code',
                        'why',
                        'written_count',
                        'hash_entries',
                        'free_before',
                        'free_after',
                        'bytes',
                    )
                    if k in _re
                ),
                'summary': _re['summary'],
            }
        )
        log('[fill] %s' % _re['summary'])
    details['sha256_output'] = sha(output)
    matrix = {}
    for p in details['steps']:
        for n, v in (p.get('detail') or {}).items():
            matrix.setdefault(n, {})[p['step']] = {'before': v[0], 'after_diag': v[1], 'bytes_changed': v[2]}
    details['matrix'] = matrix
    details['not_interpreted'] = sum(sum(v for v in p.get('not_interpreted', {}).values() if isinstance(v, int))
                                     if isinstance(p.get('not_interpreted'), dict) else (p.get('not_interpreted') or 0)
                                     for p in details['steps'])
    details['ok'] = all(p['status'] in ('ok', 'skipped') or p['status'].startswith('skipped') for p in details['steps'])
    _deliver(tmp_key, os.path.dirname(tsv))
    if not retains:
        shutil.rmtree(tmp, ignore_errors=True)
    log('RECIPE %s: %s (%d B, sha256 %s...)' % ('OK' if details['ok'] else 'FAILED', output, os.path.getsize(output),
                                                  details['sha256_output'][:16]))
    return details


def _clean_map(entry, output, no_listfile, optimization=None):
    import editor_lock
    import mpqadd
    import mpqread
    import shrink
    t0 = time.time()
    a = mpqread.Archive(entry)
    name_list = list(editor_lock.map_names(a))
    removed_count = bool(no_listfile) and a.find('(listfile)') is not None
    source = entry
    if removed_count:
        source = output + '.no_list.w3x'
        shutil.copyfile(entry, source)
        mpqadd.add_files(source, [], to_delete=['(listfile)'], log=lambda *x: None, hero_attributes=False)
    res = shrink.shrink(source, output, options=dict(optimization) if optimization is not None else
                        {'recompress': False, 'blp': False, 'dedup': False})
    if res.get('state') == 'nothing_to_do':
        if source == entry:
            shutil.copyfile(entry, output)
        else:
            os.replace(source, output)
    elif res.get('state') != 'done' or not os.path.isfile(output):
        raise SystemExit('ABORT in the MPQ cleanup: %s' % (res.get('error') or res.get('state')))
    elif source != entry:
        os.remove(source)
    d = difference(contents(entry, name_list), contents(output, name_list))
    if optimization is not None:
        _check_art(d, 'optimize of the embedded map')
    elif d:
        raise SystemExit('ABORT: the MPQ cleanup changed the content of %s' % sorted(d)[:5])
    dropped_info = res.get('dropped') or {}
    nameless = ' without (listfile)' if removed_count else ''
    return {
        'step': 'clean',
        'status': 'ok',
        'seconds': round(time.time() - t0, 2),
        'dropped_listfile': removed_count,
        'optimize': optimization is not None,
        'art_changed': len(d),
        'orphan_blocks': dropped_info.get('orphan_blocks', 0),
        'bytes_unused': dropped_info.get('unused_bytes', 0),
        'summary': (
            'map optimized%s: %s' % (nameless, _shrink_summary(res))
            if optimization is not None and res.get('state') == 'done'
            else 'MPQ rewritten with only its live blocks%s, %d -> %d B'
            % (' and' + nameless if removed_count else '', os.path.getsize(entry), os.path.getsize(output))
        ),
    }


def _campaign(
    entry,
    output,
    skip=(),
    lock_editor=('w3i', 'wtg', 'extra', 'units', 'doo'),
    force_flag=False,
    keep_names=(),
    seed=None,
    tsv=None,
    blp=False,
    lua_layers=2,
    decoys=(),
    variant=(),
    non_ascii_ids=False,
    optimization=None,
    convert_dds=False,
    convert_slk=False,
    slk_game=None,
    slk_txt='full',
    slk_max_level=None,
    ref=None,
    backup=None,
    tmp=None,
    retains=False,
    verbose=False,
    previous=None,
    log=print,
    convert_lua=False,
    bulk=None,
    cut_step=False,
):
    if bulk is not None or cut_step:
        raise SystemExit('campaign: --bulk and --cut-hash only work on a SINGLE MAP (the .w3x): in a campaign the '
                         'embedded maps go through _clean_map (only the live blocks) and the .w3n through protect; the '
                         'bulk in a campaign is left for the queue (the window parity, when the page covers it)')
    if convert_slk:
        raise SystemExit(
            'campaign: --to-slk works only on a SINGLE MAP (the .w3x): each map of the campaign would have to '
            'convert with the game base, and it is left for the queue'
        )
    import campaign_info
    import editor_lock
    import mpqadd
    import mpqread
    import sector_pack
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if not entry.lower().endswith('.w3n'):
        raise SystemExit('the input is not a campaign (.w3n): %s' % entry)
    if same_file(entry, output):
        raise SystemExit('the output must be another file (the input never changes)')
    tmp = os.path.abspath(tmp or output + '.work')
    ids_folder = os.path.abspath(tsv or os.path.splitext(output)[0] + '_ids')
    _check_paths(
        entry, output, tmp, ids_folder, None if backup is None else os.path.abspath(backup or output + '.backup')
    )
    if mpqadd.format(entry) != 0:
        raise SystemExit('ABORT: the MPQ header of this campaign is not a normal MPQ v1 header (already protected by '
                         'another tool?): use the original campaign, as the World Editor saves it')
    if previous:
        previous = os.path.abspath(previous)
        if not os.path.isdir(previous):
            raise SystemExit(
                '--previous-key: for a campaign it is the FOLDER of the keys of the previous release (<output>_ids), and %s '
                'is not a folder' % previous
            )
    os.makedirs(os.path.dirname(output) or '.', exist_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    ids_tmp = os.path.join(tmp, '_ids')
    os.makedirs(ids_tmp)
    details = {
        'type_name': 'campaign',
        'entry': entry,
        'output': output,
        'sha256_entry': sha(entry),
        'map_list': [],
        'ok': False,
    }
    if backup is not None:
        folder = os.path.abspath(backup or output + '.backup')
        os.makedirs(folder, exist_ok=True)
        copy = os.path.join(folder, os.path.basename(entry))
        shutil.copyfile(entry, copy)
        if sha(copy) != details['sha256_entry']:
            raise SystemExit('the backup does not match the input (%s)' % copy)
        details['backup'] = copy
        log('backup: %s (sha256 checked)' % copy)
    a = mpqread.Archive(entry)
    ref_names = list(editor_lock.map_names(a))
    name_list, seen = [], set()
    w3f_data = editor_lock._read(a, campaign_info.FILE)
    if w3f_data is not None:
        try:
            m = campaign_info.parse(w3f_data)
            for b in m['buttons'] + m['maps']:
                n = b['map'].decode('utf-8', 'replace').replace('/', '\\')
                if n and n.lower() not in seen and a.find(n) is not None:
                    seen.add(n.lower())
                    name_list.append(n)
        except ValueError as e:
            log('[campaign] the w3f cannot be read (%s): I use the .w3x of the (listfile)' % e)
    if not name_list:
        for n in ref_names:
            if n.lower().endswith('.w3x') and n.lower() not in seen:
                seen.add(n.lower())
                name_list.append(n)
    details['w3f_maps'] = bool(w3f_data is not None and name_list)
    if not name_list:
        raise SystemExit('ABORT: the campaign has no maps (neither the w3f lists them, nor a .w3x in the (listfile))')
    current = os.path.join(tmp, '0_campaign.w3n')
    shutil.copyfile(entry, current)
    t0 = time.time()
    for i, fname in enumerate(name_list):
        data_bytes = editor_lock._read(a, fname)
        if data_bytes is None:
            details['map_list'].append({'fname': fname, 'status': 'still_missing'})
            log('[campaign] %s: MISSING in the MPQ' % fname)
            continue
        map_in = os.path.join(tmp, '%d_map.w3x' % i)
        map_out = os.path.join(tmp, '%d_output.w3x' % i)
        with open(map_in, 'wb') as f:
            f.write(data_bytes)
        hash_key = os.path.join(ids_tmp, fname.replace('/', '_').replace('\\', '_') + '.tsv')
        log('[campaign] %s (%d B)' % (fname, len(data_bytes)))
        prev_key_path = os.path.join(previous, os.path.basename(hash_key)) if previous else None
        if prev_key_path and not os.path.isfile(prev_key_path):
            log('[campaign] %s: no previous key (%s): all ids drawn' % (fname, prev_key_path))
            prev_key_path = None
        rm = recipe(
            map_in,
            map_out,
            skip=set(skip) | {'protect'},
            lock_editor=lock_editor,
            force_flag=force_flag,
            keep_names=keep_names,
            seed=seed,
            tsv=hash_key,
            blp=False,
            lua_layers=lua_layers,
            decoys=decoys,
            non_ascii_ids=non_ascii_ids,
            optimization=optimization if 'protect' in skip else None,
            convert_dds=convert_dds,
            convert_lua=convert_lua,
            ref=ref,
            backup=None,
            tmp=os.path.join(tmp, '%d_work' % i),
            retains=retains,
            verbose=verbose,
            previous=prev_key_path,
            log=log,
            clean=False,
        )
        clean = None
        if 'protect' not in skip or optimization is None:
            limpo = os.path.join(tmp, '%d_clean.w3x' % i)
            clean = _clean_map(map_out, limpo, 'protect' not in skip and 'extra' in set(lock_editor) and
                               'lock_editor' not in skip and not _decoy_of_list(rm['steps']),
                               optimization if 'protect' not in skip else None)
            log('[campaign] %s: %s' % (fname, clean['summary']))
            map_out = limpo
            if 'fill' in decoys and 'decoy' not in skip:
                import decoy_files
                _re = decoy_files.fill(map_out, seed=seed, log=log)
                rm['steps'].append(
                    {
                        'step': 'fill',
                        'status': 'ok',
                        'seconds': 0.0,
                        'fill': dict(
                            (k, _re[k])
                            for k in (
                                'action_code',
                                'why',
                                'written_count',
                                'hash_entries',
                                'free_before',
                                'free_after',
                                'bytes',
                            )
                            if k in _re
                        ),
                        'summary': _re['summary'],
                    }
                )
                log('[campaign] %s: fill: %s' % (fname, _re['summary']))
        with open(map_out, 'rb') as f:
            new_ones = f.read()
        mpqadd.add_files(current, [(fname, new_ones)], log=lambda *x: None)
        if mpqread.Archive(current).read(fname) != new_ones:
            raise SystemExit('ABORT: the map written in the campaign is not the processed one (%s)' % fname)
        done = {'fname': fname, 'details': rm, 'ok': rm.get('ok')}
        if clean:
            done['clean'] = clean
        details['map_list'].append(done)
    if 'protect' in skip and optimization is not None:
        import shrink
        t1 = time.time()
        log('[optimize] Optimizing the size...')
        res = shrink.shrink(current, output, options=dict(optimization))
        if res.get('state') == 'nothing_to_do':
            shutil.copyfile(current, output)
            summary = 'nothing to gain (already compact)'
        elif res.get('state') != 'done' or not os.path.isfile(output):
            raise SystemExit('ABORT at step optimize of the campaign: %s' % (res.get('error') or res.get('state')))
        else:
            summary = _shrink_summary(res, 'campaign ')
        _check_art(difference(contents(current, ref_names), contents(output, ref_names)), 'optimize of the campaign')
        details['protect'] = {
            'step': 'optimize',
            'status': 'ok',
            'seconds': round(time.time() - t1, 1),
            'summary': summary,
        }
        log('[optimize] ok: %s' % summary)
    elif 'protect' in skip:
        log('[limpa] Dropping the old copies the steps replaced...')
        limpo = os.path.join(tmp, 'campaign_clean.w3n')
        lc = _clean_map(current, limpo, False)
        shutil.copyfile(limpo, output)
        details['clean'] = lc
        details['protect'] = {
            'step': 'protect',
            'status': 'skipped',
            'summary': 'in the sector-512 pack; ' + lc['summary'],
        }
        log('[clean] ok: %s' % lc['summary'])
    else:
        t1 = time.time()
        blp_512 = blp or bool(optimization is not None and optimization.get('blp', True))
        if optimization is not None:
            log('[optimize] Optimizing the size in the sector-512 pack...')

        def pack_file(origin):
            sector_pack.protect(origin, output, blp=blp_512, orphan_blocks=True,
                                no_listfile='extra' in set(lock_editor) and 'lock_editor' not in skip,
                                variant=tuple(variant))
        pack_file(current)
        before = contents(current, ref_names)
        smaller = _smaller_art(current, output, optimization, pack_file, tmp) if optimization is not None else None
        if smaller and smaller['map_path']:
            with_art = contents(smaller['map_path'], ref_names)
            _check_art(difference(before, with_art), 'optimize of the campaign')
            current, before = smaller['map_path'], with_art
        d = difference(before, contents(output, ref_names))
        details['protect'] = {
            'step': 'protect',
            'status': 'ok' if (not d or blp_512) else 'CHANGED CONTENT',
            'seconds': round(time.time() - t1, 1),
            'files_changed': len(d),
            'summary': 'Campaign MPQ rewritten (sector 512%s), %d -> %d B%s'
            % (
                ', lossless BLP' if blp_512 else '',
                os.path.getsize(current),
                os.path.getsize(output),
                ('; ' + smaller['summary']) if smaller else '',
            ),
        }
        log('[protect] %s' % details['protect']['summary'])
        if d and not blp_512:
            raise SystemExit('ABORT: the mpq_recompress changed the content of %s' % sorted(d)[:5])
    if 'fill' in decoys and 'decoy' not in skip:
        import decoy_files
        _r = decoy_files.fill(output, seed=seed, log=log)
        details['fill'] = dict(
            (k, _r[k])
            for k in ('action_code', 'why', 'written_count', 'hash_entries', 'free_before', 'free_after', 'bytes')
            if k in _r
        )
        details['protect']['summary'] = (details['protect'].get('summary') or '') + '; fill: %s' % _r['summary']
        log('[fill] %s' % _r['summary'])
    details['sha256_output'] = sha(output)
    details['ok'] = all(m.get('ok') for m in details['map_list']) and details['protect'].get('status', 'ok') in (
        'ok',
        'skipped',
    )
    details['seconds'] = round(time.time() - t0, 1)
    if _deliver(ids_tmp, ids_folder):
        details['keys'] = ids_folder
        for m in details['map_list']:
            for p in (m.get('details') or {}).get('steps', []):
                if p.get('step') == 'shuffle' and p.get('hash_key'):
                    final = os.path.join(ids_folder, os.path.basename(p['hash_key']))
                    p['summary'] = (p.get('summary') or '').replace(p['hash_key'], final)
                    p['hash_key'] = final
    if not retains:
        shutil.rmtree(tmp, ignore_errors=True)
    log(
        'CAMPAIGN %s: %s (%d map(s), %d B, sha256 %s...)'
        % (
            'OK' if details['ok'] else 'FAILED',
            output,
            len(details['map_list']),
            os.path.getsize(output),
            details['sha256_output'][:16],
        )
    )
    return details

