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
STEPS = ('anticheat', 'shuffle', 'imported', 'lua', 'dds', 'error_list', 'content', 'obfuscate', 'slk', 'lock_editor',
         'decoy', 'protect', 'bulk', 'cut_step')
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


def unnamed_encrypted(entry):
    import editor_lock
    import mpqread
    import sector_pack
    a = mpqread.Archive(entry)
    name_list = list(editor_lock.map_names(a))
    encrypted_count = [bi for bi in a.pointed_blocks() if a.blocks[bi][3] & sector_pack.MPQ_FILE_ENCRYPTED]
    if not encrypted_count:
        return None, name_list
    with_name = set()
    for n in list(sector_pack.SPECIAL_FILES) + name_list:
        for e in a.hash_entries(n):
            with_name.add(e[3])
    nameless = [bi for bi in encrypted_count if bi not in with_name]
    return (a.blocks[nameless[0]][0] if nameless else None), name_list


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


def images_summary(r):
    conv = {}
    for n, x in r['matrix'].items():
        if x.get('action_code') == 'converted_file':
            conv[n.lower()[-3:]] = conv.get(n.lower()[-3:], 0) + 1
    pieces = ['%d .%s' % (conv.get(t, 0), t) for t in r.get('types', ()) if t in conv or t != 'dds']
    g = r.get('stored_value') or {}
    before, after_diag = sum(v['before'] for v in g.values()), sum(v['after_diag'] for v in g.values())
    words = sum(v['paletted_count'] for v in g.values())
    txt = '%s -> .blp' % ', '.join(pieces)
    if before:
        txt += ' (%d without loss, paletted; %d JPEG at high quality), stored %.1f -> %.1f KB' % (
            words, sum(v['converted'] for v in g.values()) - words, before / 1024.0, after_diag / 1024.0)
    reasons = {}
    for x in r['matrix'].values():
        if x.get('action_code') == 'retained' and x.get('why'):
            m = re.sub(r'\s*\([^)]*\)', '', x['why'])
            reasons[m] = reasons.get(m, 0) + 1
    if reasons:
        txt += '; kept: ' + ', '.join('%d %s' % (k, m) for m, k in sorted(reasons.items(), key=lambda kv: -kv[1])[:3])
    return txt


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


MODEL_LEVELS = ('lossless_keys', 'lossy_keys')
SOUND_KBPS = (32, 48, 64, 96, 128)


def normalize_content(content):
    if not content:
        return None
    c = dict(content)
    outside = sorted(set(c) - {'models', 'sounds', 'script', 'ffmpeg', 'textures'})
    if outside:
        raise SystemExit(
            'content: unknown key %s (valid: models, sounds, script, ffmpeg, textures)' % ', '.join(outside)
        )
    textures = c.get('textures') or None
    if textures is not None:
        import blp_squish
        t = {'factor': 2, 'min_side': blp_squish.MIN_SIDE}
        if isinstance(textures, dict):
            t.update(textures)
        elif textures is not True:
            t['min_side'] = textures
        if sorted(t) != ['factor', 'min_side'] or t['factor'] not in blp_squish.FACTORS or \
                not isinstance(t['min_side'], int) or isinstance(t['min_side'], bool) or \
                t['min_side'] not in blp_squish.MIN_SIDES:
            raise SystemExit('content: textures=%r (the factor %s and the minimum side %s)' % (
                textures, blp_squish.FACTORS, blp_squish.MIN_SIDES))
        textures = t
    models = c.get('models') or None
    if models is not None and models not in MODEL_LEVELS:
        raise SystemExit('content: models=%r is not one of %s' % (models, ', '.join(MODEL_LEVELS)))
    sounds = c.get('sounds') or None
    if sounds is not None:
        try:
            sounds = int(sounds)
        except (TypeError, ValueError):
            sounds = None if str(c.get('sounds')).strip() == '' else -1
        if sounds not in SOUND_KBPS:
            raise SystemExit('content: sounds=%r is not one of the rates %s (kbps)' % (c.get('sounds'), SOUND_KBPS))
    out = {'models': models, 'sounds': sounds, 'script': bool(c.get('script')), 'ffmpeg': c.get('ffmpeg') or None,
           'textures': textures}
    return out if (out['models'] or out['sounds'] or out['script'] or out['textures']) else None


def _content_step(origin, new, content, name_list, ref, tmp, keep_names, short_names, verbose):
    import editor_lock
    import mpqadd
    import mpqread
    a = mpqread.Archive(origin)
    unique_names, seen = [], set()
    for n in name_list:
        if n.lower() not in seen:
            seen.add(n.lower())
            unique_names.append(n)
    swap, piece_list = [], {}
    script_before = None

    def saved(n, data_bytes):
        swap.append((n, data_bytes))

    if content['sounds']:
        import audio_shrink
        exe = audio_shrink.find_ffmpeg(content['ffmpeg'])
        mp3 = [n for n in unique_names if n.lower().endswith('.mp3') and a.find(n)]
        if not mp3:
            piece_list['MP3'] = 'no MP3 in the map'
        elif not exe:
            piece_list['MP3'] = 'skipped: ffmpeg was not found (put it on the PATH, or give its path)'
        else:
            before = after_diag = done_list = failures = 0
            for n in mp3:
                d = editor_lock._read(a, n)
                if not d:
                    continue
                try:
                    nd, info = audio_shrink.shrink_bytes(d, '.mp3', kbps=content['sounds'], ffmpeg=exe)
                except RuntimeError:
                    failures += 1
                    nd, info = d, {'shrunk': False}
                before += len(d)
                after_diag += len(nd)
                if info['shrunk']:
                    done_list += 1
                    saved(n, nd)
            piece_list['MP3'] = '%d of %d re-encoded (mono, 22 kHz, %d kbps), %d -> %d B%s' % (
                done_list, len(mp3), content['sounds'], before, after_diag,
                '; %d could not be read by ffmpeg and stay as they were' % failures if failures else '')
    if content['models']:
        import mdx_optimize
        lossy_keys = content['models'] == 'lossy_keys'
        mdx = [n for n in unique_names if n.lower().endswith('.mdx') and a.find(n)]
        before = after_diag = done_list = keys_in = keys_out = rounded = 0
        for n in mdx:
            d = editor_lock._read(a, n)
            if not d:
                continue
            try:
                nd, r = mdx_optimize.optimize(d, lossy_keys, floats=lossy_keys)
            except Exception:
                nd = None
            if nd is None:
                continue
            done_list += 1
            rounded += 1 if (r.get('floats') or {}).get('changed') else 0
            before, after_diag = before + len(d), after_diag + len(nd)
            keys_in, keys_out = keys_in + r['keys_before'], keys_out + r['keys_after']
            saved(n, nd)
        if not done_list:
            piece_list['models'] = 'no MDX model in the map' if not mdx else 'nothing to drop in %d model(s)' % len(mdx)
        elif lossy_keys:
            piece_list['models'] = (
                '%d of %d changed, lossy (%d -> %d animation keys, %d -> %d B; floats rounded in %d)'
                % (done_list, len(mdx), keys_in, keys_out, before, after_diag, rounded)
            )
        else:
            piece_list['models'] = '%d of %d with fewer animation keys%s (%d -> %d keys, %d -> %d B)' % (
                done_list, len(mdx), '', keys_in, keys_out, before, after_diag)
    if content.get('textures'):
        import blp_squish
        t = content['textures']
        ok, keep = blp_squish.reducible(a, unique_names)
        blps = [n for n in unique_names if n.lower().endswith('.blp')]
        before = after_diag = 0
        done_list, by_chain, too_small = 0, 0, 0
        for n in blps:
            if n.lower().replace('/', '\\') not in ok:
                continue
            d = editor_lock._read(a, n)
            if not d:
                continue
            nd, r = blp_squish.half_bytes(d, t['factor'], t['min_side'])
            if nd is None:
                too_small += (r.get('why') or '').startswith('below')
                continue
            done_list += 1
            by_chain += r['how'] == 'mipmaps'
            before, after_diag = before + len(d), after_diag + len(nd)
            saved(n, nd)
        piece_list['textures'] = (
            '%d of %d at half size (%d from their own mipmaps, %d rewritten), %d -> %d B; kept: %d '
            'the interface uses, %d no model cites, %d below %d px'
            % (
                done_list,
                len(blps),
                by_chain,
                done_list - by_chain,
                before,
                after_diag,
                sum(1 for m in keep.values() if 'no model' not in m),
                sum(1 for m in keep.values() if 'no model' in m),
                too_small,
                t['min_side'] * t['factor'],
            )
            if blps
            else 'no BLP texture in the map'
        )
    if content['script']:
        lua_bytes = editor_lock._read(a, 'war3map.lua')
        name_s, script = ('war3map.lua', lua_bytes) if lua_bytes else editor_lock._script(a)
        owned = [n for n in ('Scripts\\common.j', 'Scripts\\Blizzard.j') if editor_lock._read(a, n)]
        if script is None:
            piece_list['script'] = 'skipped: no script in the map'
        elif name_s.lower().endswith('.lua'):
            piece_list['script'] = 'skipped: the script is Lua (the Lua obfuscator already minifies it)'
        elif b'function main' not in script:
            piece_list['script'] = 'skipped: %s has no main function' % name_s
        elif owned:
            piece_list['script'] = 'skipped: the map carries its own %s' % ' and '.join(owned)
        else:
            import jass_minify
            body_text = script.decode('latin-1')
            libs = [os.path.join(ref, 'common.j'), os.path.join(ref, 'blizzard.j')]
            new_t, r = jass_minify.minify_text(
                body_text, {'rename': short_names, 'keep': list(keep_names), 'libraries': libs}
            )
            if r['state'] != 'done' or r['after'] >= r['before']:
                piece_list['script'] = 'kept as it was: %s' % (r.get('reason') or 'nothing to remove')
            else:
                new_b = new_t.encode('latin-1')
                j_a, j_b = os.path.join(tmp, 'content_before.j'), os.path.join(tmp, 'content_after.j')
                with open(j_a, 'wb') as f:
                    f.write(script)
                with open(j_b, 'wb') as f:
                    f.write(new_b)
                pj_a, _s = pjass_run(j_a, ref, os.path.join(tmp, 'pj_content_before'), verbose)
                pj_b, _s = pjass_run(j_b, ref, os.path.join(tmp, 'pj_content_after'), verbose)
                if pj_a is not None and pj_b is not None and (pj_b[0] > pj_a[0] or sum(pj_b) > sum(pj_a)):
                    piece_list['script'] = (
                        'kept as it was: pjass finds %s (errors, warnings) in the minified script and %s '
                        'in the original' % (list(pj_b), list(pj_a))
                    )
                else:
                    saved(name_s, new_b)
                    script_before = script
                    piece_list['script'] = (
                        '%s %d -> %d B: %d function(s) and %d global(s) removed, %d constant use(s) '
                        'written in%s; pjass %s'
                        % (
                            name_s,
                            r['before'],
                            r['after'],
                            r['removed_functions'],
                            r['removed_globals'],
                            r['inlined'],
                            ', %d name(s) shortened' % r['renamed'] if short_names else '',
                            'did not run'
                            if pj_a is None or pj_b is None
                            else '%s -> %s (errors, warnings)' % (list(pj_a), list(pj_b)),
                        )
                    )
    summary = '; '.join('%s: %s' % kv for kv in piece_list.items())
    if not swap:
        return {
            'map_path': None,
            'may_change': set(),
            'piece_list': piece_list,
            'summary': summary,
            'script_before': None,
        }
    shutil.copyfile(origin, new)
    mpqadd.add_files(new, swap, log=lambda *x: None)
    b = mpqread.Archive(new)
    for n, data_bytes in swap:
        if editor_lock._read(b, n) != data_bytes:
            raise SystemExit('ABORT at step content: the %s written to the map is not the optimized one' % n)
    return {
        'map_path': new,
        'may_change': set(n.lower() for n, _d in swap),
        'piece_list': piece_list,
        'summary': summary,
        'script_before': script_before,
    }


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
    convert_tga_png=False,
    convert_slk=False,
    slk_game=None,
    slk_pack=None,
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
    anticheat=None,
    content=None,
    imported=True,
    error_list=True,
    cipher=True,
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
    if anticheat is not None:
        import anticheat as _anticheat
        anticheat = _anticheat.normalize(anticheat)
    content = normalize_content(content)
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if same_file(entry, output):
        raise SystemExit('the output must be another file (the input never changes)')
    ref = ref or DEFAULT_REF
    tmp = os.path.abspath(tmp or output + '.work')
    tsv = os.path.abspath(tsv or os.path.splitext(output)[0] + '_ids.tsv')
    _check_paths(entry, output, tmp, tsv, None if backup is None else os.path.abspath(backup or output + '.backup'))
    version_num, why = mpqadd.format(entry, why=True)
    if version_num is None:
        raise SystemExit('ABORT: cannot read the map %s: %s' % (entry, why))
    if version_num != 0:
        raise SystemExit('ABORT: the MPQ header of this map is not a normal MPQ v1 header (a map already protected by '
                         'another tool?): use the original map, as the World Editor saves it')
    _fpos, input_names = unnamed_encrypted(entry)
    if _fpos is not None and 'protect' not in skip:
        raise SystemExit('encrypted block at %d: this script does not decrypt it (it needs the file name)' % _fpos)
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

    keep_for_obfuscator = []

    def anticheat_step(origin, previous):
        import anticheat as _ac
        t0 = time.time()
        a = mpqread.Archive(origin)
        lua_bytes = editor_lock._read(a, 'war3map.lua')
        fname, script = ('war3map.lua', lua_bytes) if lua_bytes else editor_lock._script(a)
        lang = 'lua' if script is not None and fname.endswith('.lua') else 'jass'
        if script is None or (lang == 'jass' and b'function main' not in script):
            why = ('no script in the map' if script is None else
                   'the war3map.j (%d B) has no `function main`: the real script is not in it' % len(script))
            details['steps'].append({'step': 'anticheat', 'status': 'skipped (%s)' % why})
            log('[anticheat] skipped: %s' % why)
            return origin, previous
        new_t, r = _ac.applies(script, lang, ref=ref, **anticheat)
        if not r['applied']:
            why = 'no piece applied: %s' % '; '.join(r['line_list'])[:200]
            details['steps'].append({'step': 'anticheat', 'status': 'skipped (%s)' % why, 'pieces': {
                k: v['status'] for k, v in r['pieces'].items()}})
            log('[anticheat] skipped: %s' % why)
            return origin, previous
        if lang == 'jass':
            j_before, j_after = os.path.join(tmp, 'anticheat_before.j'), os.path.join(tmp, 'anticheat_after.j')
            with open(j_before, 'wb') as f:
                f.write(script)
            with open(j_after, 'wb') as f:
                f.write(new_t)
            pj_before, _s = pjass_run(j_before, ref, os.path.join(tmp, 'pj_ac_before'), verbose)
            pj_after, _s = pjass_run(j_after, ref, os.path.join(tmp, 'pj_ac_after'), verbose)
            if pj_before is not None and pj_after is not None and (pj_after[0] > pj_before[0] or
                                                                   sum(pj_after) > sum(pj_before)):
                raise SystemExit('ABORT at step anticheat: pjass finds %s with the anti-cheat and %s without it'
                                 % (pj_after, pj_before))
        new = next_steps('anticheat')
        shutil.copyfile(origin, new)
        mpqadd.add_files(new, [(fname, new_t)], log=lambda *x: None)
        if mpqread.Archive(new).read(fname) != new_t:
            raise SystemExit('ABORT at step anticheat: the script written in the map is not the injected one')
        stages['anticheat'] = contents(new, ref_names)
        outside = set(difference(stages[previous], stages['anticheat'])) - {fname.lower()}
        if outside:
            raise SystemExit('ABORT at step anticheat: something else changed (%s)' % ', '.join(sorted(outside)))
        keep_for_obfuscator.extend(r['keep_names'])
        on_close('anticheat', 'ok', t0, previous, 'anticheat', {
            'script': fname, 'language': lang, 'pieces': dict((k, v['status']) for k, v in r['pieces'].items()),
            'action_codes': r['action_codes'], 'keep_names': list(r['keep_names']), 'extra_bytes': r['bytes'],
            'summary': '%s +%d B; %s' % (fname, r['bytes'], '; '.join(r['line_list']))})
        return new, 'anticheat'

    anticheat_deferred = False
    if anticheat and 'anticheat' not in skip:
        _language0 = mpqread.Archive(current)
        _lua0 = editor_lock._read(_language0, 'war3map.lua')
        _name0, _script0 = ('war3map.lua', _lua0) if _lua0 else editor_lock._script(_language0)
        anticheat_deferred = bool(convert_lua and 'lua' not in skip and _script0 is not None
                                  and not _name0.endswith('.lua'))
        if not anticheat_deferred:
            current, last = anticheat_step(current, last)
    elif anticheat:
        details['steps'].append({'step': 'anticheat', 'status': 'skipped'})
        log('[anticheat] skipped')

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

    if imported and 'imported' not in skip:
        t0 = time.time()
        import rename_imports
        new = next_steps('imported')
        r = rename_imports.renomeia(current, new, seed=seed, log=silent)
        if not r['ok']:
            raise SystemExit('ABORTS in the imported-files step: %s' % r.get('gate'))
        replaced = r.get('replacements') or {}
        old_new = dict((v.lower(), k) for k, v in replaced.items())
        old_low = set(old_new)
        ref_names = [old_new.get(n.lower(), n) for n in ref_names if n.lower() not in old_low]
        ref_names += [n for n in replaced if n.lower() not in [x.lower() for x in ref_names]]
        input_names = [old_new.get(n.lower(), n) for n in input_names if n.lower() not in old_low]
        input_names += [n for n in replaced if n.lower() not in [x.lower() for x in input_names]]
        stages['imported'] = contents(new, ref_names)
        on_close('imported', 'ok', t0, last, 'imported', {
            'renamed': r['renamed'], 'citations': r['citations'], 'skipped': r['skipped'],
            'replacements': replaced, 'gate': r['gate'],
            'summary': r['gate']})
        current, last = new, 'imported'
    else:
        details['steps'].append({'step': 'imported', 'status': 'skipped'})
        log('[imported] skipped')

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
            warnings = [x for x in (jass_to_lua.waits_warning(waits),
                                    jass_to_lua.game_cases_warning(r.get('game_cases') or {})) if x]
            warning = ''.join('; WARNING: ' + x for x in warnings)
            for x in warnings:
                log('[lua] WARNING: ' + x)
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
            if 'war3map.lua' not in [x.lower() for x in input_names]:
                input_names.append('war3map.lua')
            stages['lua'] = contents(new, ref_names)
            outside = set(difference(stages[last], stages['lua'])) - {j_name.lower(), 'war3map.lua', 'war3map.w3i'}
            if outside:
                raise SystemExit('ABORT at step lua: something else changed (%s)' % ', '.join(sorted(outside)))
            on_close('lua', 'ok', t0, last, 'lua', {
                'gates': r['gates'],
                'waits_in_callbacks': waits,
                'game_cases': r.get('game_cases') or {},
                'summary': '%s -> war3map.lua (%d B); w3i: %s; %s%s' % (
                    j_name, len(lua_bytes), w3i_reason, '; '.join(str(v) for v in r['gates'].values()), warning)})
            current, last = new, 'lua'

    if anticheat_deferred:
        current, last = anticheat_step(current, last)

    image_kinds = (('dds',) if convert_dds else ()) + (('tga', 'png') if convert_tga_png else ())
    if image_kinds and 'dds' not in skip:
        t0 = time.time()
        new = next_steps('dds')
        import dds_to_blp

        r = dds_to_blp.converte(
            current, new, log=silent, types=image_kinds, sector_bytes=None if 'protect' in skip else 512
        )
        if not r['ok']:
            raise SystemExit('ABORT at step dds: %s' % r.get('gate'))
        for _n, _x in r['matrix'].items():
            if _x.get('action_code') == 'converted_file' and _x.get('new'):
                old, new_name = _n.lower(), _x['new'].lower()
                ref_names = [new_name if x.lower() == old else x for x in ref_names]
                if new_name not in [x.lower() for x in ref_names]:
                    ref_names.append(new_name)
                input_names = [new_name if x.lower() == old else x for x in input_names]
                if new_name not in [x.lower() for x in input_names]:
                    input_names.append(new_name)
        stages['dds'] = contents(new, ref_names)
        on_close('dds', 'ok', t0, last, 'dds', {'summary': '%d .dds -> .blp' % r['replaced'] if image_kinds == ('dds',)
                                                else images_summary(r)})
        current, last = new, 'dds'

    if error_list and 'error_list' not in skip:
        t0 = time.time()
        import clean_errors
        a = mpqread.Archive(current)
        lua_bytes = editor_lock._read(a, 'war3map.lua')
        name_e, script_e = ('war3map.lua', lua_bytes) if lua_bytes else editor_lock._script(a)
        if script_e is None:
            details['steps'].append({'step': 'error_list', 'status': 'skipped (no script in the map)'})
            log('[errors] skipped: no script in the map')
        else:
            r = clean_errors.clean(script_e, 'lua' if name_e.endswith('.lua') else 'jass', log=silent)
            if not r['ok']:
                raise SystemExit('ABORTS in the errors step: %s' % r['gate'])
            if r['output'] == script_e:
                details['steps'].append({'step': 'error_list', 'status': 'skipped (no error message)',
                                         'removed': 0, 'deleted_slots': 0})
                log('[errors] skipped: no error message')
            else:
                new = next_steps('error_list')
                shutil.copyfile(current, new)
                mpqadd.add_files(new, [(name_e, r['output'])], log=lambda *x: None)
                if mpqread.Archive(new).read(name_e) != r['output']:
                    raise SystemExit('ABORTS in the errors step: the written script is not the cleaned one')
                stages['error_list'] = contents(new, ref_names)
                outside = set(difference(stages[last], stages['error_list'])) - {name_e.lower()}
                if outside:
                    raise SystemExit(
                        'ABORTS in the errors step: changed what it should not (%s)' % ', '.join(sorted(outside))
                    )
                on_close('error_list', 'ok', t0, last, 'error_list', {
                    'script': name_e, 'removed': r['removed'], 'deleted_slots': r['deleted_slots'],
                    'by_kind': r['by_kind'], 'gate': r['gate'],
                    'summary': '%s: %d -> %d B; %s' % (name_e, r['before'], r['after_diag'], r['gate'])})
                current, last = new, 'error_list'
    else:
        details['steps'].append({'step': 'error_list', 'status': 'skipped'})
        log('[errors] skipped')

    script_before_minify = None
    if content and 'content' not in skip:
        t0 = time.time()
        log('[content] Shrinking the models, sounds and script...')
        r_c = _content_step(current, next_steps('content'), content, ref_names, ref, tmp, keep_for_obfuscator,
                            short_names='obfuscate' in skip, verbose=verbose)
        if r_c['map_path']:
            stages['content'] = contents(r_c['map_path'], ref_names)
            outside = sorted(set(difference(stages[last], stages['content'])) - r_c['may_change'])
            if outside:
                raise SystemExit('ABORT at step content: something else changed (%s)' % ', '.join(outside[:5]))
        else:
            stages['content'] = stages[last]
        on_close('content', 'ok', t0, last, 'content', {'piece_list': r_c['piece_list'], 'summary': r_c['summary']})
        if r_c['map_path']:
            current = r_c['map_path']
        script_before_minify = r_c['script_before']
        last = 'content'
    elif content:
        details['steps'].append({'step': 'content', 'status': 'skipped'})
        log('[content] skipped')

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
            r = lua_obfuscate.obfuscate(script, layers=lua_layers, keep_names=keep_for_obfuscator, ref=ref, log=silent)
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
                'globals_renamed': r['globals_renamed'], 'globals_kept': r['globals_kept'],
                'layers': [{'seed': m['seed'], 'hash_key': m['hash_key']} for m in r['layers']],
                'gates': r['gates'],
                'summary': '%s %d -> %d B; %d name(s) (%d global(s); kept: %s), %d string(s), %d layer(s); %s' % (
                    fname, r['bytes_before'], r['bytes_after'], r['names_swapped'], r['globals_renamed'],
                    ', '.join('%s %d' % kv for kv in sorted(r['globals_kept'].items())) or 'none',
                    r['strings_encrypted'], len(r['layers']), '; '.join(r['gates'].values()))})
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
                ]
                + (['--keep_names=' + ','.join(keep_for_obfuscator)] if keep_for_obfuscator else []),
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
            slk_casc, slk_source = obj2slk.open_tables(game=slk_game, pack=slk_pack)
            base_slk = _ob_slk.GameBase(casc=slk_casc, balance=_so_slk.balance_of(_le_slk('war3map.w3i')))
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
            details['steps'].append({'step': 'slk', 'status': 'skipped (%s)' % why, 'tables': slk_source})
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
                if n.lower() not in [x.lower() for x in input_names]:
                    input_names.append(n)
            stages['slk'] = contents(new, ref_names)
            summary = '; '.join('%s: %d new, %d changed, %d left in the object file'
                                % (s, x.get('new', 0), x.get('originals', 0), x['objects_left'])
                                for s, x in slk_rep['report'].items())
            skipped = '; '.join('%s skipped (%s)' % kv for kv in slk_rep['skipped'].items())
            on_close(
                'slk',
                'ok',
                t0,
                last,
                'slk',
                {
                    'report': slk_rep['report'],
                    'skipped': slk_rep['skipped'],
                    'balance': base_slk.balance,
                    'tables': slk_source,
                    'files': [n for n, _b in slk_rep['files']],
                    'summary': 'object data -> game tables (%s profiles, layer %s, Warcraft III %s tables from the %s); %s%s'
                    % (
                        slk_txt,
                        base_slk.balance,
                        slk_source['version'],
                        'installed game' if slk_source['source'] == 'game' else 'tables pack',
                        summary,
                        ('; ' + skipped) if skipped else '',
                    ),
                },
            )
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
                                    trusted_script=script_before_minify or script_before, log=silent)
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
        _which = tuple(x for x in decoys if not (x == 'fill' and bulk and 'bulk' not in skip))
        if len(_which) != len(tuple(decoys)):
            log('[decoy] the fill waits until after the bulk')
        r = decoy_files.decoys(current, new, chosen=_which, seed=seed, log=silent,
                               spare_last=bool(cut_step and 'cut_step' not in skip))
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

        pack_rel = {}

        def pack_file(origin):
            r = sector_pack.protect(origin, output, blp=blp_512, orphan_blocks=True, no_listfile=drop_listfile,
                                    name_list=input_names, cipher=cipher, variant=tuple(variant))
            pack_rel.clear()
            pack_rel.update(r)
            return r
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
                'encrypted_count': pack_rel.get('encrypted_count', 0),
                'encrypt_skipped': pack_rel.get('encrypt_skipped', 0),
                'summary': 'MPQ repacked (512-byte sectors%s), %d -> %d B%s'
                % (
                    ', lossless BLP' if blp_512 else '',
                    os.path.getsize(current),
                    os.path.getsize(output),
                    ', %d block(s) encrypted by name' % pack_rel.get('encrypted_count', 0)
                    if pack_rel.get('encrypted_count')
                    else '',
                ),
            },
        )
        if d and not blp_512:
            raise SystemExit('ABORT: the mpq_recompress changed the content of %s' % sorted(d)[:5])
    if bulk and 'bulk' not in skip:
        t0 = time.time()
        import decoy_files
        _spec_m = decoy_files.bulk_spec(bulk)
        _rm = decoy_files.bulk(output, bombs=_spec_m['bombs'], slices=_spec_m['slices'],
                               seed=seed, log=silent)
        details['steps'].append(
            {
                'step': 'bulk',
                'status': 'ok',
                'seconds': round(time.time() - t0, 1),
                'bombs': _rm['bombs'],
                'slices': _rm['slices'],
                'claimed': _rm['claimed'],
                'bytes_written': _rm['bytes'],
                'fallback_fdf': _rm['fallback_fdf'],
                'summary': _rm['gate'],
            }
        )
        log('[bulk] %s' % _rm['gate'])
    if 'fill' in decoys and 'decoy' not in skip:
        t0 = time.time()
        import decoy_files
        _cut_follows = bool(cut_step and 'cut_step' not in skip)
        _re = decoy_files.fill(output, seed=seed, log=silent, spare_last=_cut_follows, together=_cut_follows)
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
    convert_tga_png=False,
    convert_slk=False,
    slk_game=None,
    slk_pack=None,
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
    anticheat=None,
    content=None,
    imported=True,
    error_list=True,
    cipher=True,
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
    content = normalize_content(content)
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
    version_num, why = mpqadd.format(entry, why=True)
    if version_num is None:
        raise SystemExit('ABORT: cannot read the campaign %s: %s' % (entry, why))
    if version_num != 0:
        raise SystemExit('ABORT: the MPQ header of this campaign is not a normal MPQ v1 header (already protected by '
                         'another tool?): use the original campaign, as the World Editor saves it')
    _fpos, input_names = unnamed_encrypted(entry)
    if _fpos is not None and 'protect' not in skip:
        raise SystemExit('encrypted block at %d: this script does not decrypt it (it needs the file name)' % _fpos)
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
    input_names += [n for n in name_list if n not in input_names]
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
            convert_tga_png=convert_tga_png,
            convert_lua=convert_lua,
            ref=ref,
            backup=None,
            anticheat=anticheat,
            imported=imported,
            error_list=error_list,
            cipher=cipher,
            tmp=os.path.join(tmp, '%d_work' % i),
            retains=retains,
            verbose=verbose,
            previous=prev_key_path,
            log=log,
            clean=False,
            content=content,
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

        pack_rel = {}

        def pack_file(origin):
            r = sector_pack.protect(origin, output, blp=blp_512, orphan_blocks=True,
                                    no_listfile='extra' in set(lock_editor) and 'lock_editor' not in skip,
                                    name_list=input_names, cipher=cipher, variant=tuple(variant))
            pack_rel.clear()
            pack_rel.update(r)
            return r
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
            'encrypted_count': pack_rel.get('encrypted_count', 0),
            'encrypt_skipped': pack_rel.get('encrypt_skipped', 0),
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

