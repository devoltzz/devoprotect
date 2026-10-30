# The Python side of the Web Worker: the page's jobs through the same code as the program.
import json
import os
import subprocess
import sys
import traceback

APP = '/home/pyodide/app'
ENGINE = os.path.join(APP, 'engine')
FOLDERS = ('/maps', '/out')
PJASS = os.path.join(ENGINE, 'pjass.exe')


def run_pjass(cmd, kw):
    import js
    from pyodide.ffi import to_js
    cwd = kw.get('cwd') or os.getcwd()
    args = [str(a) for a in cmd[1:]]
    files = {}
    for a in args:
        p = a if os.path.isabs(a) else os.path.join(cwd, a)
        if os.path.isfile(p):
            with open(p, 'rb') as f:
                files[a.lstrip('/')] = f.read()
    r = js.runPjass(to_js(args), to_js(files, dict_converter=js.Object.fromEntries))
    out, err = str(r.stdout), str(r.stderr)
    if not (kw.get('text') or kw.get('encoding') or kw.get('errors') or kw.get('universal_newlines')):
        out, err = out.encode('utf-8'), err.encode('utf-8')
    return subprocess.CompletedProcess(list(cmd), int(r.code), out, err)


_subprocess_run = subprocess.run


def subprocess_run(cmd, *args, **kw):
    if isinstance(cmd, (list, tuple)) and cmd and os.path.basename(str(cmd[0])).lower() in ('pjass.exe', 'pjass'):
        return run_pjass(cmd, kw)
    return _subprocess_run(cmd, *args, **kw)


subprocess.run = subprocess_run


def windows_paths():
    import ntpath
    import posixpath
    import types
    p = types.ModuleType('os.path')
    p.__dict__.update(posixpath.__dict__)
    p.basename, p.dirname, p.split, p.splitext = ntpath.basename, ntpath.dirname, ntpath.split, ntpath.splitext

    def join(a, *parts):
        allp = [os.fspath(a)] + [os.fspath(x) for x in parts]
        if any(isinstance(x, bytes) for x in allp):
            return posixpath.join(*allp)
        start = max((i for i, x in enumerate(allp) if x.startswith('/')), default=None)
        if start is not None:
            return posixpath.join(*allp[start:])
        return ntpath.join(*allp)
    p.join = join
    os.path = p
    sys.modules['os.path'] = p


windows_paths()
if not os.path.isfile(PJASS):
    open(PJASS, 'wb').close()
sys.path.insert(0, ENGINE)
os.chdir(APP)
sys.argv = [os.path.join(APP, 'DevoProtect.py')]

import protect_app


def hello():
    return json.dumps({'app': protect_app.APP, 'options': protect_app.default_options(),
                       'tables': protect_app.tables_info()})


def call(fn, arg):
    data = json.loads(arg)
    if fn == 'preset_text':
        return protect_app.preset_text(data)
    if fn == 'preset_read':
        try:
            options, warnings = protect_app.read_preset(data)
        except ValueError as e:
            return json.dumps({'error': str(e)})
        return json.dumps({'options': options, 'warnings': warnings})
    if fn == 'folder_report':
        return json.dumps(protect_app.folder_report(data['maps'], data['out']))
    if fn == 'inspect_map':
        return json.dumps(protect_app.inspect_map(data))
    raise ValueError('unknown call: %s' % fn)


def files_now():
    seen = {}
    for top in FOLDERS:
        for root, _dirs, names in os.walk(top):
            for n in names:
                p = os.path.join(root, n)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                seen[p] = (st.st_size, st.st_mtime)
    return seen


def run(job_json, emit_js):
    job = json.loads(job_json)
    ident = job.pop('id')
    before = files_now()
    held = []

    def emit(event):
        event = dict(event, job=ident)
        if event.get('type') in ('result', 'error'):
            held.append(event)
        else:
            emit_js(json.dumps(event))

    try:
        protect_app.run_job(dict(job, task='protect', vault=False), emit)
    except BaseException as e:
        held.append({'type': 'error', 'job': ident, 'trace': traceback.format_exc(limit=8),
                     'message': str(e) or type(e).__name__})
    final = held[-1] if held else {'type': 'error', 'job': ident, 'message': 'the job ended without a result'}
    after = files_now()
    final['written'] = sorted(p for p, st in after.items() if before.get(p) != st)
    if final.get('type') != 'result' or not final.get('ok'):
        for p in final['written']:
            try:
                py_fs_remove(p)
            except Exception:
                pass
        final['written'] = []
    emit_js(json.dumps(final))


def py_fs_remove(path):
    if os.path.isdir(path):
        import shutil
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.isfile(path):
        os.remove(path)


def zip_folder(folder, target):
    import zipfile
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, names in os.walk(folder):
            for n in sorted(names):
                p = os.path.join(root, n)
                z.write(p, os.path.relpath(p, folder))
    return target
