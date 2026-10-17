# Builds pjass, the JASS checker, from its source (natively for Linux, or as WebAssembly).
import hashlib
import json
import os
import shutil
import subprocess
import sys

UNITS = ('misc.c', 'hashtable.c', 'paramlist.c', 'funcdecl.c', 'typeandname.c', 'blocks.c', 'tree.c', 'sstrhash.c',
         'main.c', 'token.yy.c', 'grammar.tab.c')
STACK = 8 << 20
ANCHOR = '#elif defined(__linux__) || defined(__CYGWIN__)'
WASI_MALLOC = ('#elif defined(__wasi__)\n    void * _aligned_malloc(size_t size, size_t alignment){\n'
               '        return aligned_alloc(alignment, size);\n    }\n')


def run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors='replace')
    if r.returncode:
        raise SystemExit('build_pjass: %s failed (%d)\n%s%s' % (' '.join(cmd), r.returncode, r.stdout, r.stderr))
    return r.stdout + r.stderr


def source_commit(src):
    r = subprocess.run(['git', '-c', 'safe.directory=*', 'rev-parse', '--short', 'HEAD'], cwd=src, capture_output=True,
                       text=True)
    return r.stdout.strip() or 'unknown'


def build(src, out, flex='flex', bison='bison', native=False):
    if not os.path.isfile(os.path.join(src, 'grammar.y')):
        raise SystemExit('build_pjass: no pjass source in %s (git clone https://github.com/lep/pjass)' % src)
    work = os.path.join(out, '_build')
    if os.path.isdir(work):
        shutil.rmtree(work)
    shutil.copytree(src, work, ignore=shutil.ignore_patterns('.git', 'tests', 'msvc'))
    p = os.path.join(work, 'typeandname.c')
    with open(p, encoding='utf-8', newline='') as f:
        text = f.read()
    if text.count(ANCHOR) != 1:
        raise SystemExit('build_pjass: typeandname.c changed (no %r)' % ANCHOR)
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(text.replace(ANCHOR, WASI_MALLOC + ANCHOR))
    run([bison, '-d', 'grammar.y'], work)
    run([flex, 'token.l'], work)
    commit = source_commit(src)
    with open(os.path.join(work, 'amalgamation.c'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(''.join('#include "%s"\n' % u for u in UNITS))
    os.makedirs(out, exist_ok=True)
    wasm = os.path.join(out, 'pjass.wasm')
    run([sys.executable, '-m', 'ziglang', 'cc', '-target', 'wasm32-wasi', '-O2', '-s', '-w', '-DPJASS_AMALGATION',
         '-DVERSIONSTR="git-%s-wasm"' % commit, '-Wl,-z,stack-size=%d' % STACK, '-o', wasm, 'amalgamation.c'], work)
    if native:
        run([sys.executable, '-m', 'ziglang', 'cc', '-target', 'x86_64-linux-musl', '-static', '-O2', '-s', '-w',
             '-DPJASS_AMALGATION', '-DVERSIONSTR="git-%s-linux"' % commit, '-o', os.path.join(out, 'pjass'),
             'amalgamation.c'], work)
    with open(wasm, 'rb') as f:
        data = f.read()
    info = {'commit': commit, 'zig': run([sys.executable, '-m', 'ziglang', 'version'], work).strip(),
            'flex': run([flex, '--version'], work).strip().split()[-1],
            'bison': run([bison, '--version'], work).splitlines()[0].split()[-1],
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    with open(os.path.join(out, 'pjass.json'), 'w', encoding='utf-8', newline='\n') as f:
        json.dump(info, f, indent=1)
    shutil.rmtree(work, ignore_errors=True)
    return info


USAGE = ('usage: python web/build_pjass.py --src=<pjass source> --out=<folder> [--flex=flex] [--bison=bison] '
         '[--native]')


def main(argv):
    op = dict((a[2:].split('=', 1) + [''])[:2] for a in argv if a.startswith('--'))
    if not op.get('src') or not op.get('out'):
        print(USAGE)
        return 2
    info = build(os.path.abspath(op['src']), os.path.abspath(op['out']), op.get('flex') or 'flex',
                 op.get('bison') or 'bison', 'native' in op)
    print('pjass %s -> %s (%d bytes, zig %s, flex %s, bison %s)' % (info['commit'], op['out'], info['bytes'],
                                                                    info['zig'], info['flex'], info['bison']))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
