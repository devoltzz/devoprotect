# Runs one protection job from the window or the command line and reports each step.
import os
import sys
import threading
import time


HERE = os.path.dirname(os.path.abspath(__file__))

APP = 'DevoProtect'

STEPS = {
    'shuffle': 'Shuffling the object IDs...',
    'obfuscate': 'Obfuscating the script...',
    'lock_editor': 'Removing the editor-only files...',
    'decoy': 'Writing the decoy files...',
    'protect': 'Repacking the archive...',
    'optimize': 'Optimizing the size...',
    'dds': 'Converting DDS textures to BLP...',
    'clean': 'Dropping the old copies the steps replaced...',
}
DONE = {
    'shuffle': 'Object IDs shuffled.',
    'obfuscate': 'Script obfuscated.',
    'lock_editor': 'Editor-only files removed.',
    'decoy': 'Decoy files written.',
    'protect': 'Archive repacked.',
    'optimize': 'Size optimized.',
    'dds': 'DDS textures converted to BLP.',
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


def recipe_kwargs(options):
    o = dict(options or {})
    skip = [internal for public, internal in STEP_KEYS.items() if not o.get(public, True)]
    decoys = [internal for public, internal in DECOYS.items() if o.get('decoy_' + public)]
    if not decoys and 'decoy' not in skip:
        skip.append('decoy')
    blocks = [k for k in BLOCKS if o.get('block_' + k, k != 'w3r')]
    variants = [internal for public, internal in VARIANTS.items() if o.get('variant_' + public)]
    optimize = None
    if o.get('optimize'):
        optimize = {'recompress': o.get('opt_recompress', True), 'blp': o.get('opt_blp', True),
                    'dedup': o.get('opt_dedup', True), 'lossy': bool(o.get('opt_lossy'))}
    return {
        'skip': skip,
        'lock_editor': blocks,
        'decoys': tuple(decoys),
        'variant': tuple(variants),
        'non_ascii_ids': bool(o.get('non_ascii_ids')),
        'lua_layers': int(o.get('lua_layers', 2)),
        'blp': bool(o.get('blp')),
        'convert_dds': bool(o.get('dds')),
        'convert_lua': bool(o.get('to_lua')),
        'optimization': optimize,
        'seed': None if o.get('seed') is None or str(o['seed']).strip() == '' else int(o['seed']),
        'previous': (str(o['previous_key']).strip() or None) if o.get('previous_key') else None,
    }


def default_options():
    return {'shuffle': True, 'obfuscate': True, 'block': True, 'pack': True,
            'block_w3i': True, 'block_wtg': True, 'block_extra': True, 'block_units': True, 'block_doo': True,
            'block_w3r': False, 'lua_layers': 2,
            'optimize': False, 'opt_recompress': True, 'opt_blp': True, 'opt_dedup': True, 'opt_lossy': False,
            'dds': False}


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
    try:
        kwargs = recipe_kwargs(job.get('options'))
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
        return {'version': self._version, 'app': APP, 'map': self._initial, 'options': default_options()}

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
        if updater.install(self._release):
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
                run_job(job, emit)
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
