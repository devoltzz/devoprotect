# Builds the Linux binary in a Docker container: pjass from its source, then build.py.
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
IMAGE = 'devoprotect-linux'
PJASS_COMMIT = '378a1ca'
STEPS = "\n".join([
    'set -e',
    'rm -rf /tmp/pjass && git clone -q https://github.com/lep/pjass.git /tmp/pjass',
    'git -C /tmp/pjass checkout -q ' + PJASS_COMMIT,
    'python web/build_pjass.py --src=/tmp/pjass --out=/tmp/pjass-out --native',
    'PJASS=/tmp/pjass-out/pjass python build.py',
    'cp dist/DevoProtect dist/DevoProtect-linux-x86_64',
    'chmod 755 dist/DevoProtect-linux-x86_64',
    'if [ -n "$HOST_UID" ]; then chown -R "$HOST_UID:$HOST_GID" dist build; fi',
    ''])


def main():
    subprocess.run(['docker', 'build', '-q', '-t', IMAGE, os.path.join(ROOT, 'linux')], check=True)
    env = []
    if hasattr(os, 'getuid'):
        env = ['-e', 'HOST_UID=%d' % os.getuid(), '-e', 'HOST_GID=%d' % os.getgid()]
    r = subprocess.run(
        ['docker', 'run', '--rm', '-v', ROOT + ':/src', '-w', '/src'] + env + [IMAGE, 'bash', '-c', STEPS]
    )
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
