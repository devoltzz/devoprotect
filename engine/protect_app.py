# Runs one protection job from the window or the command line and reports each step.
import os
import sys
import threading
import time


HERE = os.path.dirname(os.path.abspath(__file__))

APP = 'DevoProtect'

STEPS = {
    'anticheat': 'Adding the anti-cheat...',
    'shuffle': 'Shuffling the object IDs...',
    'lua': 'Converting the script to Lua...',
    'obfuscate': 'Obfuscating the script...',
    'lock_editor': 'Removing the editor-only files...',
    'decoy': 'Writing the decoy files...',
    'protect': 'Repacking the archive...',
    'optimize': 'Optimizing the size...',
    'dds': 'Converting DDS textures to BLP...',
    'content': 'Shrinking the models, sounds and script...',
    'slk': 'Converting object data to SLK tables...',
    'bulk': 'Writing the extract-all bombs...',
    'cut_step': 'Cutting the hash table...',
    'clean': 'Dropping the old copies the steps replaced...',
}
DONE = {
    'anticheat': 'Anti-cheat added.',
    'shuffle': 'Object IDs shuffled.',
    'imported': 'Imported files renamed.',
    'error_list': 'Compiler error messages removed.',
    'lua': 'Script converted to Lua.',
    'obfuscate': 'Script obfuscated.',
    'lock_editor': 'Editor-only files removed.',
    'decoy': 'Decoy files written.',
    'protect': 'Archive repacked.',
    'optimize': 'Size optimized.',
    'dds': 'DDS textures converted to BLP.',
    'content': 'Models, sounds and script shrunk.',
    'slk': 'Object data converted to SLK tables.',
    'bulk': 'Extract-all bombs written.',
    'cut_step': 'Hash table cut.',
    'clean': 'Old copies dropped.',
}


STEP_KEYS = {
    'shuffle': 'shuffle',
    'obfuscate': 'obfuscate',
    'block': 'lock_editor',
    'decoys': 'decoy',
    'pack': 'protect',
}
BLOCKS = ('w3i', 'wtg', 'extra', 'units', 'doo', 'w3r')
DECOYS = {'wtg': 'wtg', 'listfile': 'listfile', 'imp': 'imp', 'preview': 'preview', 'fill': 'fill'}
VARIANTS = {'header': 'header_text', 'high_sector': 'high-sector', 'bit31': 'bit31'}
AC_PARTS = {'ledger': 'ledger', 'codes': 'codes', 'names': 'decoys', 'bj': 'bj', 'globals': 'globals'}
AC_OFF = ('globals',)
AC_ACTIONS = ('warn', 'nosave', 'defeat', 'end')
AC_CODES_MODES = {'auto': 'auto', 'humans': 'humans', 'reload': 'reload', 'humans+reload': 'humans+reload'}
MODELS = {'lossless': 'lossless_keys', 'lossy': 'lossy_keys'}
MP3_KBPS = (32, 48, 64, 96, 128)
TEXTURE_MIN_SIDES = (64, 128, 256)
TABLES = {'version': '3.0.1.24371', 'bytes': 1200765,
          'sha256': '0fd822bcb873d78fca04c492e632c126e779e1d9f261492b67e72327067b0396',
          'url': 'https://protect.devoltz.party/data/slk_tables.zip'}


def tables_cache():
    if os.name == 'nt' and os.environ.get('LOCALAPPDATA'):
        return os.path.join(os.environ['LOCALAPPDATA'], APP, 'tables')
    return os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.join(os.path.expanduser('~'), '.cache'),
                        APP.lower(), 'tables')


def fetch_tables():
    import obj2slk
    return obj2slk.fetch_pack(TABLES['url'], TABLES['sha256'], tables_cache(), agent=APP)


def _bulk_default():
    import decoy_files
    return ','.join('%s:%d' % (field_id, field_value) for field_id, field_value in decoy_files.bulk_spec('').items())


def recipe_kwargs(options):
    o = dict(options or {})
    skip = [internal for public, internal in STEP_KEYS.items() if not o.get(public, True)]
    decoys = [internal for public, internal in DECOYS.items() if o.get('decoy_' + public)]
    if not decoys and 'decoy' not in skip:
        skip.append('decoy')
    blocks = [k for k in BLOCKS if o.get('block_' + k, k != 'w3r')]
    variants = [internal for public, internal in VARIANTS.items() if o.get('variant_' + public)]
    if o.get('variant_bit31') and 'protect' not in skip and (o.get('bombs') or o.get('cut_hash')):
        raise ValueError('the bit31 variant does not combine with the extract-all bombs or the hash table cut: '
                         'turn one of them off')
    optimize = None
    if o.get('optimize'):
        optimize = {'recompress': o.get('opt_recompress', True), 'blp': o.get('opt_blp', True),
                    'dedup': o.get('opt_dedup', True), 'lossy': bool(o.get('opt_lossy'))}
    content = None
    if o.get('optimize'):
        models = 'lossy' if o.get('opt_models_lossy') else ('lossless' if o.get('opt_models') else None)
        content = {'models': MODELS[models] if models else None,
                   'sounds': int(o.get('opt_mp3_kbps') or 64) if o.get('opt_mp3') else None,
                   'script': bool(o.get('opt_minify')),
                   'ffmpeg': (str(o['ffmpeg']).strip() or None) if o.get('ffmpeg') else None}
        if o.get('opt_small_textures'):
            content['textures'] = int(o.get('opt_texture_min_side') or TEXTURE_MIN_SIDES[1])
        if not (content['models'] or content['sounds'] or content['script'] or content.get('textures')):
            content = None
    anti_cheat = None
    if o.get('anti_cheat'):
        anti_cheat = {
            'pieces': [
                internal for public, internal in AC_PARTS.items() if o.get('ac_' + public, public not in AC_OFF)
            ],
            'action_codes': [a for a in AC_ACTIONS if o.get('ac_' + a, a == 'warn')],
            'gold_jump': o.get('ac_gold_jump') or 400,
            'codes_mode': AC_CODES_MODES.get(o.get('ac_codes_mode') or 'auto', 'auto'),
        }
    return {
        'anticheat': anti_cheat,
        'skip': skip,
        'lock_editor': blocks,
        'decoys': tuple(decoys),
        'variant': tuple(variants),
        'non_ascii_ids': bool(o.get('non_ascii_ids')),
        'lua_layers': int(o.get('lua_layers', 2)),
        'blp': bool(o.get('blp')),
        'imported': bool(o.get('imports')),
        'error_list': bool(o.get('error_logs')),
        'cipher': bool(o.get('encrypt')),
        'convert_dds': bool(o.get('dds')),
        'convert_tga_png': bool(o.get('optimize') and o.get('opt_tga_png')),
        'convert_slk': bool(o.get('to_slk')),
        'slk_game': (str(o['game']).strip() or None) if o.get('game') else None,
        'slk_pack': ((str(o['tables']).strip() or None) if o.get('tables') else fetch_tables)
                       if o.get('to_slk') else None,
        'convert_lua': bool(o.get('to_lua')),
        'optimization': optimize,
        'content': content,
        'bulk': _bulk_default() if o.get('bombs') else None,
        'cut_step': bool(o.get('cut_hash')),
        'seed': None if o.get('seed') is None or str(o['seed']).strip() == '' else int(o['seed']),
        'previous': (str(o['previous_key']).strip() or None) if o.get('previous_key') else None,
    }


def default_options():
    return {'shuffle': True, 'obfuscate': True, 'block': True, 'pack': True,
            'imports': False, 'error_logs': False, 'encrypt': False,
            'block_w3i': True, 'block_wtg': True, 'block_extra': True, 'block_units': True, 'block_doo': True,
            'block_w3r': False, 'lua_layers': 2,
            'optimize': False, 'opt_recompress': True, 'opt_blp': True, 'opt_dedup': True, 'opt_lossy': False,
            'opt_models': False, 'opt_models_lossy': False, 'opt_mp3': False, 'opt_mp3_kbps': 64, 'opt_minify': False,
            'opt_tga_png': False, 'opt_small_textures': False, 'opt_texture_min_side': TEXTURE_MIN_SIDES[1],
            'dds': False, 'bombs': False, 'cut_hash': False, 'to_slk': False,
            'anti_cheat': False, 'ac_ledger': True, 'ac_codes': True, 'ac_names': True, 'ac_bj': True,
            'ac_globals': False,
            'ac_warn': True, 'ac_nosave': False, 'ac_defeat': False, 'ac_end': False, 'ac_gold_jump': 400,
            'ac_codes_mode': 'auto'}


def inspect_map(path):
    import protect_recipe
    try:
        r = protect_recipe.inspect_archive(path)
    except Exception as e:
        return {'refused': 'the map does not read: %s' % e}
    return {'campaign': r['campaign'], 'bytes': r['bytes'], 'refused': r['refusal'], 'script': r['lang'],
            'w3i': r['w3i'], 'unnamed_block': r['unnamed'], 'own_blizzard': r['map_blizzard'],
            'last_file': r['last_unit']}


def tables_info():
    return {'version': TABLES['version'], 'bytes': TABLES['bytes'], 'sha256': TABLES['sha256']}


def run_job(job, emit):
    import protect_recipe
    task = job.get('task', 'protect')
    map_path = job.get('map')
    if task != 'protect':
        emit({'type': 'error', 'message': 'unknown task: %s' % task})
        return {'ok': False}
    if not map_path or not os.path.isfile(map_path):
        emit({'type': 'error', 'message': 'map not found: %s' % map_path})
        return {'ok': False}
    out_path = job.get('out') or _default_out(map_path)
    if out_path.endswith(('/', '\\')) or os.path.isdir(out_path):
        out_path = os.path.join(out_path, os.path.basename(_default_out(map_path)))
    options = dict(job.get('options') or {})
    if options.get('previous_key') and os.path.isdir(options['previous_key']) and not map_path.lower().endswith('.w3n'):
        found = resolve_previous(map_path, options['previous_key'])
        if found:
            options['previous_key'] = found
        else:
            options.pop('previous_key')
    try:
        kwargs = recipe_kwargs(options)
    except (ValueError, TypeError) as e:
        emit({'type': 'error', 'message': 'invalid option: %s' % e})
        return {'ok': False}
    is_campaign = map_path.lower().endswith('.w3n')
    emit({'type': 'progress', 'step': 'open', 'text': 'Reading %s...' % os.path.basename(map_path)})

    def log(*a):
        msg = ' '.join(str(x) for x in a)
        if msg.startswith('['):
            code = msg[1:msg.index(']')] if ']' in msg else ''
            rest = msg[msg.index(']') + 1:].strip() if ']' in msg else ''
            if rest.startswith('skipped'):
                text = '%s: skipped' % code
            elif rest.startswith('ok') and code in DONE:
                text = DONE[code]
            elif rest.endswith('...') and code in STEPS:
                text = STEPS[code]
            else:
                text = msg
            emit({'type': 'progress', 'step': code, 'text': text})
        else:
            emit({'type': 'progress', 'step': '', 'text': msg})

    t0 = time.time()
    try:
        fn = protect_recipe.campaign if is_campaign else protect_recipe.recipe
        report = fn(map_path, out_path, log=log, **kwargs)
    except SystemExit as e:
        emit({'type': 'error', 'message': str(e.code) if e.code else 'aborted'})
        return {'ok': False}
    except BaseException as e:
        import traceback
        emit({'type': 'error', 'message': '%s: %s' % (type(e).__name__, e), 'trace': traceback.format_exc(limit=6)})
        return {'ok': False}
    resultado = {
        'ok': bool(report.get('ok')),
        'out': out_path,
        'seconds': round(time.time() - t0, 1),
        'lines': report_lines(report),
        'summary': report_summary(report, out_path),
        'key': report_key(report),
        'bytes_in': os.path.getsize(map_path),
        'bytes_out': os.path.getsize(out_path) if os.path.isfile(out_path) else None,
    }
    emit(dict(resultado, type='result'))
    return resultado


def _default_out(map_path):
    base, ext = os.path.splitext(map_path)
    return base + '_protected' + ext


PRESET_FORMAT = 'devoprotect_preset'
PRESET_PATHS = ('previous_key', 'ffmpeg', 'game', 'tables')


def preset_keys():
    keys = dict((k, type(v)) for k, v in default_options().items())
    keys.update(('decoy_' + k, bool) for k in DECOYS)
    keys.update(('variant_' + k, bool) for k in VARIANTS)
    keys.update({'non_ascii_ids': bool, 'to_lua': bool, 'blp': bool, 'same_bytes': bool, 'seed': int})
    return keys


def preset_text(options):
    import json
    keys = preset_keys()
    o = dict((k, v) for k, v in dict(options or {}).items()
             if k in keys and k not in PRESET_PATHS and v is not None and v != '')
    for k, v in o.items():
        if keys[k] is int and isinstance(v, str) and v.strip().lstrip('-').isdigit():
            o[k] = int(v)
    return json.dumps({PRESET_FORMAT: 1, 'options': dict(sorted(o.items()))}, indent=1) + '\n'


def read_preset(text):
    import json
    try:
        data = json.loads(text)
    except ValueError as e:
        raise ValueError('the preset is not JSON (%s)' % e)
    if not isinstance(data, dict) or data.get(PRESET_FORMAT) != 1 or not isinstance(data.get('options'), dict):
        raise ValueError('not a DevoProtect preset: it needs "%s": 1 and "options"' % PRESET_FORMAT)
    keys = preset_keys()
    o, warnings = default_options(), []
    for k, v in data['options'].items():
        if k in PRESET_PATHS:
            warnings.append('%s ignored: a preset carries no file paths' % k)
            continue
        if k not in keys:
            warnings.append('%s ignored: not an option of this version' % k)
            continue
        want = keys[k]
        if (want is bool) != isinstance(v, bool) or not isinstance(v, want):
            raise ValueError('%s: %r is not a %s' % (k, v, {bool: 'true or false', int: 'whole number',
                                                             str: 'text'}.get(want, want.__name__)))
        o[k] = v
    for k, valid in (('opt_mp3_kbps', MP3_KBPS), ('opt_texture_min_side', TEXTURE_MIN_SIDES),
                     ('ac_codes_mode', tuple(AC_CODES_MODES))):
        if o[k] not in valid:
            raise ValueError('%s: %r is not one of %s' % (k, o[k], ', '.join(str(x) for x in valid)))
    for k in ('lua_layers', 'ac_gold_jump'):
        if o[k] < 1:
            raise ValueError('%s: %r is below 1' % (k, o[k]))
    return o, warnings


MAP_EXTS = ('.w3x', '.w3m', '.w3n')


def maps_in(folder):
    return sorted((n for n in os.listdir(folder) if n.lower().endswith(MAP_EXTS)
                   and os.path.isfile(os.path.join(folder, n))), key=lambda n: n.lower())


def default_folder_out(folder):
    return os.path.normpath(folder).rstrip('\\/') + '_protected'


def resolve_previous(map_path, previous):
    if not previous or not os.path.isdir(previous):
        return previous or None
    stem = os.path.splitext(os.path.basename(map_path))[0]
    is_campaign = map_path.lower().endswith('.w3n')
    for name in (stem + '_ids', stem + '_protected_ids'):
        p = os.path.join(previous, name if is_campaign else name + '.tsv')
        if os.path.isdir(p) if is_campaign else os.path.isfile(p):
            return p
    return previous if is_campaign else None


def run_folder(job, emit, run_one=None):
    run_one = run_one or run_job
    folder = job.get('folder')
    if not folder or not os.path.isdir(folder):
        emit({'type': 'error', 'message': 'folder not found: %s' % folder})
        return {'ok': False}
    out = job.get('out') or default_folder_out(folder)
    if os.path.normcase(os.path.abspath(out)) == os.path.normcase(os.path.abspath(folder)):
        emit({'type': 'error', 'message': 'the output folder must be another folder (the maps are never overwritten)'})
        return {'ok': False}
    names = maps_in(folder)
    if not names:
        emit({'type': 'error', 'message': 'no map in %s (.w3x, .w3m, .w3n)' % folder})
        return {'ok': False}
    options = dict(job.get('options') or {})
    previous = options.pop('previous_key', None)
    if previous and not os.path.isdir(previous):
        emit({'type': 'error', 'message': 'with a folder, the previous key is the keys folder of the previous release: '
                                          '%s is not a folder' % previous})
        return {'ok': False}
    os.makedirs(out, exist_ok=True)
    t0 = time.time()
    maps = []
    for i, name in enumerate(names):
        src, dst = os.path.join(folder, name), os.path.join(out, name)
        emit({'type': 'progress', 'step': 'map', 'text': 'Map %d of %d: %s' % (i + 1, len(names), name)})
        opts = dict(options)
        prev_key = resolve_previous(src, previous) if previous else None
        if prev_key:
            opts['previous_key'] = prev_key
        failed = []

        def sub(ev):
            if ev.get('type') == 'error':
                failed.append(ev.get('message') or 'aborted')
            elif ev.get('type') == 'progress':
                emit(ev)
        res = run_one({'task': 'protect', 'map': src, 'out': dst, 'options': opts}, sub) or {}
        maps.append({'name': name, 'ok': bool(res.get('ok')), 'out': dst if res.get('ok') else None,
                     'key': res.get('key'), 'seconds': res.get('seconds'), 'bytes_in': os.path.getsize(src),
                     'bytes_out': res.get('bytes_out'),
                     'reason': None if res.get('ok') else (failed[-1] if failed else res.get('summary') or 'failed')})
    result = folder_report(maps, out)
    result.update(folder=folder, seconds=round(time.time() - t0, 1))
    emit(dict(result, type='result'))
    return result


def folder_report(maps, out):
    lines = [('title', 'Folder: %d map(s)' % len(maps))]
    for m in maps:
        if m['ok']:
            lines.append(('info', 'ok  %s: %s -> %s bytes (%ss)%s' % (
                m['name'], m['bytes_in'], m.get('bytes_out'), m.get('seconds'),
                '; key: %s' % os.path.basename(m['key']) if m.get('key') else '')))
        else:
            lines.append(('bad', 'refused  %s: %s' % (m['name'], m.get('reason'))))
    done = sum(1 for m in maps if m['ok'])
    return {
        'ok': done == len(maps),
        'maps': maps,
        'out': out,
        'lines': lines,
        'summary': 'Protected %d of %d map(s). Saved to %s' % (done, len(maps), os.path.basename(out.rstrip('\\/'))),
    }


def report_lines(report):
    out = []
    if report.get('type_name') == 'campaign':
        out.append(('title', 'Campaign: %d map(s)' % len(report.get('map_list', []))))
        for m in report.get('map_list', []):
            st = 'ok' if m.get('ok') else (m.get('status') or 'failed')
            out.append(('info' if m.get('ok') else 'bad', '  %s: %s' % (m.get('fname'), st)))
        p = report.get('protect') or {}
        out.append(('info', 'Archive: %s' % (p.get('summary') or p.get('status') or '')))
        return out
    for p in report.get('steps', []):
        name, status = p.get('step'), p.get('status') or ''
        style = 'info' if status == 'ok' or status.startswith('skipped') else 'bad'
        txt = '%s: %s' % (name, status)
        if p.get('summary'):
            txt += ' - ' + p['summary']
        out.append((style, txt))
    for a in report.get('warnings') or []:
        out.append(('warn', 'WARNING: %s' % a))
    return out


def report_key(report):
    if report.get('type_name') == 'campaign':
        return report.get('keys')
    return next(
        (p.get('hash_key') for p in report.get('steps', []) if p.get('step') == 'shuffle' and p.get('status') == 'ok'),
        None,
    )


def report_summary(report, out_path):
    if not report.get('ok'):
        return 'Protection failed - see the report.'
    n = len(report.get('map_list', [])) if report.get('type_name') == 'campaign' else 1
    return 'Protected %d file(s). Saved to %s' % (n, os.path.basename(out_path))


def ui_folder():
    base = getattr(sys, '_MEIPASS', HERE)
    for p in (os.path.join(base, 'ui'), os.path.join(HERE, '..', 'ui')):
        if os.path.isdir(p):
            return p
    raise OSError('ui not found')


class Api:
    def __init__(self, version, initial_map=None):
        self._window = None
        self._version = version
        self._initial = initial_map
        self._jobs = {}
        self._n = 0
        self._release = None

    def hello(self):
        return {'version': self._version, 'app': APP, 'map': self._initial, 'options': default_options(),
                'tables': tables_info()}

    def check_update(self):
        try:
            import updater
        except ImportError:
            return None
        if not updater.enabled(sys.argv):
            return None
        try:
            release = updater.latest_release()
        except Exception:
            return None
        if updater.version_tuple(release['version']) <= updater.version_tuple(self._version):
            return None
        self._release = release
        return {'version': release['version'].lstrip('v')}

    def update(self):
        import updater
        if not self._release:
            return False
        try:
            installed = updater.install(self._release)
        except OSError:
            return False
        if installed:
            self._window.destroy()
            return True
        return False

    def _dialog(self, kind, **kw):
        r = self._window.create_file_dialog(kind, **kw)
        return None if not r else os.path.normpath(r if isinstance(r, str) else r[0])

    def pick_map(self):
        import webview
        return self._dialog(webview.FileDialog.OPEN,
                            file_types=('Warcraft III maps (*.w3x;*.w3m;*.w3n)', 'All files (*.*)'))

    def pick_save(self, suggested):
        import webview
        return self._dialog(webview.FileDialog.SAVE, save_filename=suggested or '',
                            file_types=('Warcraft III maps (*.w3x;*.w3m;*.w3n)', 'All files (*.*)'))

    def pick_key(self, folder=False):
        import webview
        if folder:
            return self._dialog(webview.FileDialog.FOLDER)
        return self._dialog(webview.FileDialog.OPEN, file_types=('ID keys (*.tsv)', 'All files (*.*)'))

    def inspect_map(self, path):
        return inspect_map(path)

    def pick_folder(self):
        import webview
        p = self._dialog(webview.FileDialog.FOLDER)
        if not p:
            return None
        return {'folder': p, 'maps': maps_in(p), 'out': default_folder_out(p)}

    def pick_out_folder(self):
        import webview
        return self._dialog(webview.FileDialog.FOLDER)

    def save_preset(self, options):
        import webview
        p = self._dialog(webview.FileDialog.SAVE, save_filename='devoprotect_preset.json',
                         file_types=('DevoProtect presets (*.json)', 'All files (*.*)'))
        if not p:
            return None
        with open(p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(preset_text(options))
        return p

    def load_preset(self):
        import webview
        p = self._dialog(webview.FileDialog.OPEN, file_types=('DevoProtect presets (*.json)', 'All files (*.*)'))
        if not p:
            return None
        try:
            with open(p, encoding='utf-8') as f:
                o, warnings = read_preset(f.read())
        except (OSError, ValueError) as e:
            return {'error': str(e)}
        return {'options': o, 'warnings': warnings, 'name': os.path.basename(p)}

    def start(self, params=None):
        if any(t.is_alive() for t in self._jobs.values()):
            return None
        self._n += 1
        ident = 'job%d' % self._n
        job = dict(params or {}, task='protect')

        def emit(event):
            self._push(ident, event)

        def work():
            try:
                (run_folder if job.get('folder') else run_job)(job, emit)
            except BaseException as e:
                self._push(ident, {'type': 'error', 'message': str(e)})
        t = threading.Thread(target=work, daemon=True)
        self._jobs[ident] = t
        t.start()
        return ident

    def _push(self, ident, event):
        import json
        if self._window is None:
            return
        payload = json.dumps(dict(event, job=ident))
        try:
            self._window.evaluate_js('window.onJob(%s)' % json.dumps(payload))
        except Exception:
            pass


def run(version, initial_map=None, icon=None):
    import webview
    try:
        import updater
        updater.cleanup()
    except ImportError:
        pass
    api = Api(version, initial_map)
    window = webview.create_window(APP, url=os.path.join(ui_folder(), 'index.html'), js_api=api,
                                   width=1100, height=760, min_size=(820, 600))
    api._window = window
    if sys.platform.startswith('linux'):
        webview.start(gui='gtk', icon=icon)
    else:
        webview.start(gui='edgechromium', icon=icon)
