# Builds the site (the program in the browser) from a release: the page, Pyodide, the engine.
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_FILES = ('ponte.js', 'fila.js', 'worker.js', 'worker.py', 'wasi_mini.js', 'fs_windows.js', 'mpqcrypt.js',
             'about.html', 'about.js')
PACKAGES = ('numpy', 'pillow')
CORE = ('pyodide.js', 'pyodide.mjs', 'pyodide.asm.mjs', 'pyodide.asm.wasm', 'python_stdlib.zip', 'pyodide-lock.json')
SIZE_LIMIT = 450 * 1024 * 1024
THEME = '#121418'
SHARED_CSS = 'devoltz.css'
SHARED_CSS_LINK = re.compile(r'<link rel="stylesheet" href="[^"]*?devoltz\.css">')
OPTIONAL = ('data/game_data.zip',)
NOT_CACHED = ('sw.js', 'names.npz')
DEFAULT = {
    'entry': 'DevoProtect.py',
    'engine_dir': 'engine',
    'icon': 'assets/devoprotect.ico',
    'config_var': 'DEVOPROTECT_WEB',
    'inject_before': '<script src="i18n_data.js"></script>',
    'inject': ['config.js', 'ponte.js'],
    'head_anchor': '</head>',
    'web_files': ['ponte.js', 'worker.js', 'worker.py', 'wasi_mini.js', 'fs_windows.js', 'mpqcrypt.js', 'setor512.js'],
    'manifest': {
        'name': 'DevoProtect',
        'short_name': 'DevoProtect',
        'description': 'Protect Warcraft III maps from casual editing, in the browser.',
    },
    'favicon': 'protect.svg',
    'cache_prefix': 'devoprotect',
    'size_limit_mb': 250,
    'mpqcrypt_c': 'engine/mpqcrypt.c',
    'setor512_wasm': 'engine/setor512.wasm',
    'inline_script': 'page.js',
    'after': [],
}


def product(site=None):
    site = site or os.path.join(HERE, 'site.json')
    out = dict(DEFAULT, web_dir=HERE)
    if os.path.isfile(site):
        with open(site, encoding='utf-8') as f:
            out.update(json.load(f))
        out['web_dir'] = os.path.dirname(os.path.abspath(site))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def engine_version(engine, prod=None):
    entry = (prod or DEFAULT)['entry']
    with open(os.path.join(engine, entry), encoding='utf-8') as f:
        m = re.search(r"^VERSION = '([^']+)'", f.read(), re.M)
    if not m:
        raise SystemExit('build_site: no VERSION in %s' % os.path.join(engine, entry))
    return m.group(1)


def engine_zip(engine, target, prod=None):
    prod = prod or DEFAULT
    n = 0
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(engine, prod['entry']), prod['entry'])
        for root, dirs, files in os.walk(os.path.join(engine, prod['engine_dir'])):
            dirs[:] = sorted(d for d in dirs if d not in ('__pycache__', 'cache'))
            for f in sorted(files):
                if f.endswith(('.exe', '.pyc', '.dll', '.so', '.lib', '.wasm')):
                    continue
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, engine).replace(os.sep, '/'))
                n += 1
    return n + 1


def pyodide(source, target, wheels):
    if not os.path.isfile(os.path.join(source, 'pyodide-lock.json')):
        raise SystemExit('build_site: no Pyodide in %s (npm install in web/)' % source)
    with open(os.path.join(source, 'package.json'), encoding='utf-8') as f:
        version = json.load(f)['version']
    with open(os.path.join(source, 'pyodide-lock.json'), encoding='utf-8') as f:
        lock = json.load(f)['packages']
    os.makedirs(target, exist_ok=True)
    for n in CORE:
        shutil.copyfile(os.path.join(source, n), os.path.join(target, n))
    os.makedirs(wheels, exist_ok=True)
    todo, done = list(PACKAGES), set()
    while todo:
        name = todo.pop()
        if name in done:
            continue
        done.add(name)
        p = lock[name]
        todo += p.get('depends', [])
        local = os.path.join(wheels, p['file_name'])
        if not os.path.isfile(local) or sha256(local) != p['sha256']:
            url = 'https://cdn.jsdelivr.net/pyodide/v%s/full/%s' % (version, p['file_name'])
            print('downloading %s' % url)
            with urllib.request.urlopen(url, timeout=120) as r, open(local + '.part', 'wb') as f:
                shutil.copyfileobj(r, f)
            if sha256(local + '.part') != p['sha256']:
                os.remove(local + '.part')
                raise SystemExit('build_site: %s does not match the sha256 of the lock' % p['file_name'])
            os.replace(local + '.part', local)
        shutil.copyfile(local, os.path.join(target, p['file_name']))
    return version


def icons(engine, out, prod=None):
    from PIL import Image
    ico = os.path.join(engine, *(prod or DEFAULT)['icon'].split('/'))
    if not os.path.isfile(ico):
        raise SystemExit('build_site: no %s' % ico)
    img = Image.open(ico)
    img.size = max(img.info.get('sizes') or [img.size])
    img = img.convert('RGBA')
    img.save(os.path.join(out, 'icon-256.png'))
    img.resize((192, 192), Image.LANCZOS).save(os.path.join(out, 'icon-192.png'))


def page(ui, out, config, prod=None):
    prod = prod or DEFAULT
    for n in os.listdir(ui):
        p = os.path.join(ui, n)
        if os.path.isfile(p) and n != 'index.html':
            shutil.copyfile(p, os.path.join(out, n))
        elif os.path.isdir(p):
            shutil.copytree(p, os.path.join(out, n), dirs_exist_ok=True)
    with open(os.path.join(ui, 'index.html'), encoding='utf-8') as f:
        html = f.read()
    html = shared_css(html, out)
    if prod.get('inline_script'):
        m = re.search(r'(?s)\n<script>\n(.*?)</script>\n', html)
        if not m:
            raise SystemExit('build_site: the page has no inline <script> to move to %s' % prod['inline_script'])
        with open(os.path.join(out, prod['inline_script']), 'w', encoding='utf-8', newline='\n') as f:
            f.write(m.group(1))
        html = html[:m.start()] + '\n<script src="%s"></script>\n' % prod['inline_script'] + html[m.end():]
    script, css = prod['inject_before'], prod['head_anchor']
    if html.count(script) != 1 or html.count(css) != 1:
        raise SystemExit('build_site: the page changed (no single %s or %s)' % (script, css))
    html = html.replace(script, ''.join('<script src="%s"></script>\n' % n for n in prod['inject']) + script +
                        ''.join('\n<script src="%s"></script>' % n for n in prod['after']))
    head = ('<link rel="manifest" href="manifest.webmanifest">\n<link rel="icon" href="icon-192.png">\n'
            '<meta name="theme-color" content="%s">' % THEME)
    if favicon(out, prod):
        head += '\n<link rel="icon" href="favicon.svg" type="image/svg+xml">'
    html = html.replace(css, head + '\n' + css if css.startswith('</') else css + '\n' + head)
    with open(os.path.join(out, 'index.html'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)
    with open(os.path.join(out, 'config.js'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('window.%s = %s;\n' % (prod['config_var'], json.dumps(config, indent=1)))
    for n in prod['web_files']:
        src = os.path.join(prod.get('web_dir', HERE), n)
        shutil.copyfile(src if os.path.isfile(src) else os.path.join(HERE, n), os.path.join(out, n))
    manifest = {'name': prod['manifest']['name'], 'short_name': prod['manifest']['short_name'], 'start_url': './',
                'scope': './', 'display': 'standalone', 'background_color': THEME, 'theme_color': THEME,
                'description': prod['manifest']['description'],
                'icons': [{'src': 'icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                          {'src': 'icon-256.png', 'sizes': '256x256', 'type': 'image/png'}]}
    with open(os.path.join(out, 'manifest.webmanifest'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(manifest, f, indent=1)


def favicon(out, prod):
    name = prod.get('favicon')
    for base in (prod.get('web_dir', HERE), HERE):
        src = os.path.join(base, 'icones', name) if name else ''
        if src and os.path.isfile(src):
            shutil.copyfile(src, os.path.join(out, 'favicon.svg'))
            return True
    return False


def shared_css(html, out):
    n = len(SHARED_CSS_LINK.findall(html))
    if not n:
        return html
    if n > 1:
        raise SystemExit('build_site: the page links %s %d times' % (SHARED_CSS, n))
    if os.path.isfile(os.path.join(HERE, SHARED_CSS)):
        shutil.copyfile(os.path.join(HERE, SHARED_CSS), os.path.join(out, SHARED_CSS))
    if not os.path.isfile(os.path.join(out, SHARED_CSS)):
        raise SystemExit('build_site: %s is missing (next to build_site.py or in the page folder)' % SHARED_CSS)
    return SHARED_CSS_LINK.sub('<link rel="stylesheet" href="%s">' % SHARED_CSS, html)


def service_worker(out, version, prod=None):
    files = []
    h = hashlib.sha256()
    for root, dirs, names in os.walk(out):
        dirs.sort()
        for n in sorted(names):
            rel = os.path.relpath(os.path.join(root, n), out).replace(os.sep, '/')
            if rel in NOT_CACHED or rel in OPTIONAL:
                continue
            files.append(rel)
            h.update(rel.encode() + b'\0' + sha256(os.path.join(root, n)).encode())
    with open(os.path.join(HERE, 'sw.js'), encoding='utf-8') as f:
        text = f.read()
    tag = '%s-%s' % (version, h.hexdigest()[:10])
    text = text.replace("'devoprotect-__VERSION__'", "'%s-__VERSION__'" % (prod or DEFAULT)['cache_prefix'])
    text = text.replace('__VERSION__', tag).replace('__ASSETS__', json.dumps(['./'] + files))
    text = text.replace('__OPTIONAL__', json.dumps(list(OPTIONAL)))
    with open(os.path.join(out, 'sw.js'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return tag


def site_zip(out, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, names in os.walk(out):
            dirs[:] = sorted(d for d in dirs if os.path.relpath(os.path.join(root, d), out) != 'data')
            for n in sorted(names):
                p = os.path.join(root, n)
                z.write(p, os.path.relpath(p, out).replace(os.sep, '/'))
    with open(target + '.sha256', 'w', encoding='utf-8', newline='\n') as f:
        f.write('%s  %s\n' % (sha256(target), os.path.basename(target)))


def native_decryption(engine, out, wasm=None, prod=None):
    target = os.path.join(out, 'mpqcrypt.wasm')
    if wasm:
        shutil.copyfile(wasm, target)
        return
    rel = (prod or DEFAULT)['mpqcrypt_c']
    source = os.path.join(engine, *rel.split('/'))
    if not os.path.isfile(source):
        print('build_site: no %s: the site decrypts maps in Python (slow on encrypted maps)' % rel)
        return
    r = subprocess.run([sys.executable, '-m', 'ziglang', 'cc', '-target', 'wasm32-freestanding', '-nostdlib',
                        '-Wl,--no-entry', '-O2', '-s', '-o', target, source], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('build_site: zig could not build mpqcrypt.wasm\n%s%s' % (r.stdout, r.stderr))


def sector_codec(engine, out, wasm=None, prod=None):
    rel = (prod or {}).get('setor512_wasm')
    source = wasm or (os.path.join(engine, *rel.split('/')) if rel else None)
    if not source or not os.path.isfile(source):
        if rel:
            print('build_site: no %s: the site packs maps with the browser\'s zlib' % (wasm or rel))
        return
    shutil.copyfile(source, os.path.join(out, 'setor512.wasm'))


def build(engine, out, ui=None, pjass=None, data=None, index=None, pyodide_dir=None, wheels=None, repository=None,
          zip_path=None, mpqcrypt=None, site=None, setor512=None):
    prod = product(site)
    engine = os.path.abspath(engine)
    if not os.path.isfile(os.path.join(engine, prod['entry'])):
        raise SystemExit('build_site: %s is not a release (no %s)' % (engine, prod['entry']))
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    version = engine_version(engine, prod)
    config = {'version': version, 'repository': repository, 'sizeLimit': prod['size_limit_mb'] * 1024 * 1024}
    page(ui or os.path.join(engine, 'ui'), out, config, prod)
    icons(engine, out, prod)
    n_engine = engine_zip(engine, os.path.join(out, 'engine.zip'), prod)
    if not pjass or not os.path.isfile(pjass):
        raise SystemExit('build_site: no pjass.wasm (build_pjass.py): the port, the GUI triggers and the cheat packs '
                         'need it')
    shutil.copyfile(pjass, os.path.join(out, 'pjass.wasm'))
    native_decryption(engine, out, mpqcrypt, prod)
    sector_codec(engine, out, setor512, prod)
    py_version = pyodide(pyodide_dir or os.path.join(HERE, 'node_modules', 'pyodide'), os.path.join(out, 'pyodide'),
                         wheels or os.path.join(HERE, 'wheels'))
    if data:
        if not os.path.isfile(os.path.join(data, 'game_data.json')):
            raise SystemExit('build_site: %s is not a game data pack' % data)
        os.makedirs(os.path.join(out, 'data'), exist_ok=True)
        with zipfile.ZipFile(os.path.join(out, 'data', 'game_data.zip'), 'w', zipfile.ZIP_DEFLATED) as z:
            for root, dirs, names in os.walk(data):
                dirs.sort()
                for n in sorted(names):
                    p = os.path.join(root, n)
                    z.write(p, os.path.relpath(p, data).replace(os.sep, '/'))
    if index:
        shutil.copyfile(index, os.path.join(out, 'names.npz'))
    tag = service_worker(out, version, prod)
    if zip_path:
        site_zip(out, zip_path)
    return {'version': version, 'cache': tag, 'engine_files': n_engine, 'pyodide': py_version}


USAGE = ('usage: python web/build_site.py --engine=<release folder> --out=<folder> [--ui=<page folder>] '
         '[--pjass=<pjass.wasm>] [--data=<game data pack>] [--index=<names.npz>] [--pyodide=<node_modules/pyodide>] '
         '[--wheels=<cache folder>] [--repository=owner/name] [--zip=<site zip>] [--mpqcrypt=<mpqcrypt.wasm>] '
         '[--site=<site.json>] [--setor512=<setor512.wasm>]')


def main(argv):
    op = dict((a[2:].split('=', 1) + [''])[:2] for a in argv if a.startswith('--'))
    if not op.get('engine') or not op.get('out'):
        print(USAGE)
        return 2
    r = build(op['engine'], os.path.abspath(op['out']), op.get('ui'), op.get('pjass'), op.get('data'), op.get('index'),
              op.get('pyodide'), op.get('wheels'), op.get('repository'), op.get('zip'), op.get('mpqcrypt'),
              op.get('site') or None, op.get('setor512') or None)
    print('site %s (cache %s, Pyodide %s, %d engine files) -> %s' % (r['version'], r['cache'], r['pyodide'],
                                                                    r['engine_files'], op['out']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
