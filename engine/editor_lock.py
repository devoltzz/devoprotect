# Removes or empties the files only the World Editor reads, when the game does not need them.
import os
import re
import shutil
import struct

import mpqread
import w3i


FUCK_MARK = 0x4B435546
SCRIPTS = ('war3map.j', 'scripts\\war3map.j', 'war3map.lua')
UNTOUCHABLE = ('war3map.j', 'scripts\\war3map.j', 'war3map.lua', 'war3map.doo', 'war3mapunits.doo', 'war3map.w3e',
               'war3map.wpm', 'war3map.shd', 'war3map.mmp', 'war3map.imp')
EDITOR_ONLY_NOT_REQUESTED = ('war3map.w3c', 'war3map.w3s', 'war3map.imp', 'war3mapunits.doo', 'war3map.doo')
RX_CAMERA = re.compile(rb'\bCreateCameraSetup\s*\(')
RX_SOUND = re.compile(rb'\bCreateSound\w*\s*\(')
RX_MUSIC = re.compile(rb'\bgg_snd_\w+\s*=\s*"')
RX_MAIN = re.compile(rb'(?m)\bfunction\s+main\b(?!\w)|^\s*main\s*=\s*function\b')
RX_DESTRUCTABLE_TYPE = re.compile(
    rb'\b(?:Blz)?Create(?:Dead)?Destructable(?:Z)?(?:WithSkin|Loc(?:BJ)?)?\s*\(\s*'
    rb'(?:FourCC\s*\(\s*)?(\'[^\'\r\n]{4}\'|"[^"\r\n]{4}"|0[xX][0-9A-Fa-f]+|\$[0-9A-Fa-f]+|\d+)'
)
RX_UNIT = re.compile(
    rb'\b(?:CreateUnit|BlzCreateUnitWithSkin|CreateNeutralPassiveBuilding|CreateItem|BlzCreateItemWithSkin)\s*\('
)


def _read(a, fname):
    try:
        return a.read(fname) if a.find(fname) else None
    except Exception:
        return None


def _script(a):
    for fname in SCRIPTS:
        d = _read(a, fname)
        if d:
            return fname, d
    return None, None


def lock_editor_w3i(d, force_flag=False):
    try:
        m = w3i.parse(d)
    except Exception as e:
        try:
            _m, deviations = w3i.parse_tolerant(d)
        except Exception:
            return None, 'the w3i cannot be read (%s)' % str(e)[:60], len(d)
        if 'tail_ff' in deviations:
            return None, 'already locked (the tail is' ' the 0xFF)', 0
        return None, 'the w3i does not close under strict reading (%s)' % ','.join(deviations), len(d)
    if m.get('_tail'):
        return None, 'the w3i has %d byte(s) after the last section: not interpreted' % len(m['_tail']), len(m['_tail'])
    if w3i.write(m) != d:
        return None, 'the w3i does not come back equal (round trip)', len(d)
    lists_out = {'upgrade_list': len(m['upgrades']), 'techniques': len(m['techs']),
                 'random groups': len(m['random_unit_groups']), 'item tables': len(m.get('random_item_tables', []))}
    full_lists = dict((k, v) for k, v in lists_out.items() if v)
    if full_lists and not force_flag:
        return None, ('the game USES these lists (%s): not touched'
                      % ', '.join('%s=%d' % kv for kv in sorted(full_lists.items()))), 0
    v = m['version']
    empty = dict(m)
    empty['upgrades'], empty['techs'], empty['random_unit_groups'] = [], [], []
    if v >= 25:
        empty['random_item_tables'] = []
    base = w3i.write(empty)
    n = 4 * (4 if v >= 25 else 3)
    if base[-n:] != b'\0' * n:
        return None, 'the final counters are not the last %d bytes' % n, 0
    new = base[:-n] + b'\xff'
    begin = len(base) - n
    if not full_lists and d != base:
        return None, 'w3i without lists but the rewrite differs from the original', 0
    if d[:begin] != new[:begin]:
        return None, 'the w3i prefix changes', 0
    m2, deviations = w3i.parse_tolerant(new)
    if 'tail_ff' not in deviations:
        return None, 'the new w3i cannot be read with tail_ff (%s)' % deviations, 0
    for k in m:
        if k in ('upgrades', 'techs', 'random_unit_groups', 'random_item_tables', '_tail'):
            continue
        if m2.get(k) != m[k]:
            return None, 'the field %r changes on re-read' % k, 0
    return (
        new,
        (
            '4 counters -> 0xFF (%d -> %d B)%s'
            % (len(d), len(new), '; DISCARDED ' + str(full_lists) if full_lists else '')
        ),
        0,
    )


def lock_editor_w3r(d, script, force_flag=False):
    import inflated_counts
    if len(d) >= 8 and struct.unpack_from('<I', d, 4)[0] == FUCK_MARK:
        return None, 'already inflated (the count is' ' the FUCK)', 0
    try:
        r = inflated_counts.read_w3r(d)
    except Exception as e:
        return None, 'the war3map.w3r cannot be read (%s)' % str(e)[:60], len(d)
    on_close = r['declared'] == len(r['regs']) and not r['remaining']
    not_interp = 0 if on_close else r['remaining']
    n_files = len(r['regs'])
    if not on_close and not force_flag:
        return (
            None,
            (
                'the w3r does not close (declares %d region(s), reads %d, %d B left over): I do not know how many it has'
                % (r['declared'], len(r['regs']), r['remaining'])
            ),
            not_interp,
        )
    if script is None:
        return None, 'no script in the map: I cannot confirm the game creates the regions', not_interp
    try:
        n_script = len(inflated_counts.script_regions(script.decode('utf-8', 'replace')))
    except Exception as e:
        n_script = -1
        if not force_flag:
            return None, 'I could not read the regions of the script (%s)' % str(e)[:60], not_interp
    if n_script < n_files and not force_flag:
        return None, ('the file has %d region(s) and the script creates %d: the game would lose the ones that are only'
                      " in the file" % (n_files, n_script)), not_interp
    version_num = struct.unpack_from('<I', d, 0)[0] if len(d) >= 4 else 5
    return (
        struct.pack('<II', version_num, FUCK_MARK),
        ('%d region(s) in the file, %d in the script -> FUCK count (%d -> 8 B)' % (n_files, n_script, len(d))),
        not_interp,
    )


def covers(fname, d, script):
    import inflated_counts
    import doodads
    if script is None:
        return False, 'no script in the map: I cannot confirm the game creates what the file has'
    try:
        if fname == 'war3map.w3c':
            r = inflated_counts.read_w3c(d)
            n, c, o = len(r['regs']), len(RX_CAMERA.findall(script)), 'camera(s)'
            on_close = r['declared'] == n and not r['remaining']
        elif fname == 'war3map.w3s':
            r = inflated_counts.read_w3s_records(d)
            n, c, o = len(r['regs']), len(RX_SOUND.findall(script)) + len(RX_MUSIC.findall(script)), 'sound(s)'
            on_close = r['declared'] == n and not r['remaining']
        elif fname == 'war3mapUnits.doo':
            u = inflated_counts.load_units_doo(d)
            sloc = sum(1 for x in u['regs'] if x['ident'] == b'sloc')
            n, c, o = len(u['regs']) - sloc, len(RX_UNIT.findall(script)), 'unit(s)/item(s) except the %d sloc' % sloc
            on_close = bool(u.get('on_close')) and u['declared'] == len(u['regs'])
        elif fname == 'war3map.doo':
            r = doodads.read_data(d)
            if not r.get('on_close'):
                return False, '%s does not close: I do not know how many records it has' % fname
            specials = struct.unpack_from('<i', r['tail'], 4)[0] if len(r['tail']) >= 8 else 0
            if specials:
                return (
                    False,
                    'the file has %d special doodad(s): the game reads them and the script does not create them'
                    % specials,
                )
            needs_work, cria = {}, script_destructables(script)
            for x in r['regs']:
                needs_work[x['id']] = needs_work.get(x['id'], 0) + 1
            missing_items = sorted((i, k - cria.get(i, 0)) for i, k in needs_work.items() if cria.get(i, 0) < k)
            n, c = len(r['regs']), sum(cria.values())
            if missing_items:
                return False, (
                    'the file has %d doodad(s)/destructible(s) (the game reads the file) and the script does not create %d '
                    'of them by type (%s%s)'
                    % (
                        n,
                        sum(k for _i, k in missing_items),
                        ', '.join('%s=%d' % (i.decode('latin-1'), k) for i, k in missing_items[:6]),
                        '...' if len(missing_items) > 6 else '',
                    )
                )
            return (
                True,
                '%d doodad(s)/destructible(s) in the file, all created by type in the script (%d creations)' % (n, c),
            )
        else:
            return False, 'no criterion for %s' % fname
    except Exception as e:
        return False, 'I could not read %s (%s)' % (fname, str(e)[:60])
    if not on_close:
        return False, '%s does not close: I do not know how many records it has' % fname
    if c < n:
        return False, 'the file has %d %s and the script creates %d' % (n, o, c)
    return True, '%d %s in the file, %d creations in the script' % (n, o, c)


def script_destructables(script):
    out = {}
    for m in RX_DESTRUCTABLE_TYPE.finditer(script or b''):
        t = m.group(1)
        if t[:1] in (b"'", b'"'):
            type_name = t[1:-1]
        else:
            v = int(t[1:], 16) if t[:1] == b'$' else int(t, 0) if t[:2].lower() == b'0x' else int(t)
            type_name = struct.pack('>I', v & 0xFFFFFFFF)
        out[type_name] = out.get(type_name, 0) + 1
    return out


FORCE_NAMES = {
    'w3i': ('w3i',),
    'wtg': ('wtg', 'wct'),
    'w3r': ('w3r', 'w3r-inflado', 'w3r_inflated'),
    'w3c': ('w3c', 'extra', 'editor-extra', 'editor_extra'),
    'w3s': ('w3s', 'extra', 'editor-extra', 'editor_extra'),
    'imp': ('imp', 'extra', 'editor-extra', 'editor_extra'),
    'units': ('units', 'units-doo', 'units_doo'),
    'doo': ('doo',),
}


def normalize_force(force_flag):
    if force_flag is True or not force_flag:
        return bool(force_flag)
    if isinstance(force_flag, (str, bytes)):
        force_flag = force_flag.decode() if isinstance(force_flag, bytes) else force_flag
        force_flag = [x for x in force_flag.split(',') if x]
    force_flag = set(x.strip().lower() for x in force_flag)
    valid_ids = set(n for ns in FORCE_NAMES.values() for n in ns)
    if force_flag - valid_ids:
        raise SystemExit(
            'unknown name to force: %s (valid: %s)' % (sorted(force_flag - valid_ids), ', '.join(sorted(valid_ids)))
        )
    return force_flag


def _force(force_flag, fname):
    if force_flag is True:
        return True
    return (
        bool(force_flag)
        and not isinstance(force_flag, bool)
        and any(x in force_flag for x in FORCE_NAMES.get(fname, (fname,)))
    )


def map_names(a):
    import map_formats
    try:
        lst = a.read('(listfile)') or b''
    except Exception:
        lst = b''
    name_list = [n for n in re.split('[\r\n]+', lst.decode('utf-8', 'surrogateescape')) if n.strip()]
    seen = set(n.lower() for n in name_list)
    for n in map_formats.standard_names():
        if n.lower() not in seen and a.find(n):
            name_list.append(n)
            seen.add(n.lower())
    return name_list


def lock_editor(
    entry,
    output,
    w3i_=False,
    wtg=False,
    w3r_inflated=False,
    editor_extra=False,
    units_doo=False,
    doo=False,
    force_flag=False,
    only_count=False,
    trusted_script=None,
    log=print,
    **kw,
):
    w3i_ = kw.pop('w3i', w3i_)
    if kw:
        raise TypeError('unknown argument: %s' % sorted(kw))
    force_flag = normalize_force(force_flag)
    details = {
        'entry': entry,
        'output': output,
        'ok': False,
        'mechanisms': {
            'w3i': w3i_,
            'wtg': wtg,
            'w3r_inflated': w3r_inflated,
            'editor_extra': editor_extra,
            'units_doo': units_doo,
            'doo': doo,
        },
    }
    if not (w3i_ or wtg or w3r_inflated or editor_extra or units_doo or doo):
        raise SystemExit('no mechanism on: choose at least one in --block (w3i, wtg, extra, units, doo, w3r)')
    a = mpqread.Archive(entry)
    name_list = map_names(a)
    _lua = _read(a, 'war3map.lua')
    script_name, script = ('war3map.lua', _lua) if _lua else _script(a)
    if trusted_script is not None:
        script = trusted_script
    matrix, repl, to_delete = {}, [], []

    def registra(fname, action_code, before, after_diag, why, not_interp=0):
        matrix[fname] = {'action_code': action_code, 'bytes_before': before, 'bytes_after': after_diag, 'why': why,
                         'not_interpreted': not_interp}

    if w3i_:
        d = _read(a, 'war3map.w3i')
        if d is None:
            registra('war3map.w3i', 'not touched', 0, 0, 'the map does not have war3map.w3i')
        else:
            new, why, ni = lock_editor_w3i(d, _force(force_flag, 'w3i'))
            if new is None:
                registra('war3map.w3i', 'not touched', len(d), len(d), why, ni)
            else:
                registra('war3map.w3i', 'reworked', len(d), len(new), why, ni)
                repl.append(('war3map.w3i', new))
    if wtg:
        has_main = bool(script) and RX_MAIN.search(script) is not None
        for fname in ('war3map.wtg', 'war3map.wct'):
            d = _read(a, fname)
            if d is None:
                registra(fname, 'not touched', 0, 0, 'the map does not have %s' % fname)
            elif not has_main and not _force(force_flag, 'wtg'):
                registra(
                    fname,
                    'not touched',
                    len(d),
                    len(d),
                    'no script with main in the map: the triggers would be the only copy',
                )
            else:
                registra(fname, 'stripped', len(d), 0, 'editor-only: the game runs %s' % script_name)
                to_delete.append(fname)
    if w3r_inflated:
        d = _read(a, 'war3map.w3r')
        if d is None:
            registra('war3map.w3r', 'not touched', 0, 0, 'the map does not have war3map.w3r')
        else:
            new, why, ni = lock_editor_w3r(d, script, _force(force_flag, 'w3r'))
            if new is None:
                registra('war3map.w3r', 'not touched', len(d), len(d), why, ni)
            else:
                registra('war3map.w3r', 'reworked', len(d), len(new), why, ni)
                repl.append(('war3map.w3r', new))
    def remove(fname, hash_key, gate):
        d = _read(a, fname)
        if d is None:
            registra(fname, 'not touched', 0, 0, 'the map does not have %s' % fname)
            return
        if gate is None:
            ok, why = True, 'editor-only'
        else:
            ok, why = covers(fname, d, script)
            if not ok and _force(force_flag, hash_key):
                ok, why = True, 'FORCED (%s)' % why
        if ok:
            registra(fname, 'stripped', len(d), 0, why)
            to_delete.append(fname)
        else:
            registra(fname, 'not touched', len(d), len(d), why)

    if editor_extra:
        remove('war3map.w3c', 'w3c', True)
        remove('war3map.w3s', 'w3s', True)
        remove('war3map.imp', 'imp', None)
    if units_doo:
        remove('war3mapUnits.doo', 'units', True)
    if doo:
        remove('war3map.doo', 'doo', True)
    modified_names = set(n.lower() for n, x in matrix.items() if x['action_code'] in ('reworked', 'stripped'))
    in_matrix = set(k.lower() for k in matrix)
    for n in name_list:
        low = n.lower()
        if low in in_matrix or low in ('(listfile)', '(attributes)', '(signature)'):
            continue
        if low in UNTOUCHABLE or low.startswith('war3mapskin.') or low.startswith('war3map.w3'):
            type_name = (
                'not touched (the game reads it)'
                if low not in EDITOR_ONLY_NOT_REQUESTED
                else 'not touched (editor-only, outside the request)'
            )
            sz = len(_read(a, n) or b'')
            registra(n, type_name, sz, sz, '')
            in_matrix.add(low)
    details['matrix'] = matrix
    details['not_interpreted'] = sum(x['not_interpreted'] for x in matrix.values() if x['action_code'] != 'not touched')
    for n, x in sorted(matrix.items()):
        if x['action_code'] in ('not touched (the game reads it)',):
            continue
        log(
            '  %-18s %-34s %7s -> %-7s not interpreted=%-5s %s'
            % (n, x['action_code'], x['bytes_before'], x['bytes_after'], x['not_interpreted'], x['why'])
        )
    if only_count:
        details['ok'] = True
        return details
    if os.path.normcase(os.path.abspath(output)) == os.path.normcase(os.path.abspath(entry)):
        raise SystemExit('the output must be a different file (the original does not change)')
    part = os.path.splitext(output)[0] + '.part' + os.path.splitext(output)[1]
    if os.path.normcase(os.path.abspath(part)) == os.path.normcase(os.path.abspath(entry)):
        raise SystemExit('the input is the .part of the output: pick another output name')
    ready = False
    try:
        shutil.copyfile(entry, part)
        if repl or to_delete:
            import mpqadd
            mpqadd.add_files(part, repl, to_delete=to_delete, log=lambda *x: None)
        details = _check_written(details, a, part, output, name_list, repl, to_delete, modified_names, log)
        if details['ok']:
            os.replace(part, output)
            ready = True
    finally:
        if not ready and os.path.isfile(part):
            os.remove(part)
    return details


def _check_written(details, a, part, output, name_list, repl, to_delete, modified_names, log):
    b = mpqread.Archive(part)
    problems = []
    new_ones = dict((k.lower(), v) for k, v in repl)
    to_delete_low = set(k.lower() for k in to_delete)
    verified_count = set()
    for n in name_list:
        low = n.lower()
        if low in ('(listfile)', '(attributes)', '(signature)') or low in verified_count:
            continue
        verified_count.add(low)
        x, y = _read(a, n), _read(b, n)
        if low in to_delete_low:
            if y is not None:
                problems.append('%s should have gone away' % n)
        elif low in new_ones:
            if y != new_ones[low]:
                problems.append('%s is not what was expected' % n)
        elif x != y:
            problems.append('%s changed without being asked' % n)
    names_low = set(k.lower() for k in name_list)
    extras = [n for n in map_names(b) if n.lower() not in names_low and
              n.lower() not in ('(listfile)', '(attributes)', '(signature)')]
    if extras:
        problems.append('new files: %s' % extras)
    details['problems'] = problems
    details['unchanged'] = len(names_low - modified_names - {'(listfile)', '(attributes)', '(signature)'})
    log('written: %s -- %d rewritten, %d removed; %d file(s) equal to the input; problems: %s'
        % (output, len(repl), len(to_delete), details['unchanged'], problems or 'none'))
    details['ok'] = not problems
    return details

