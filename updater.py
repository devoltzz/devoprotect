# Checks GitHub for a newer release and replaces the executable when the user agrees.
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
import webbrowser

REPOSITORY = 'devoltzz/devoprotect'
API = 'https://api.github.com/repos/{}/releases/latest'
TIMEOUT = 6
INDEX = 'names.npz'
PROGRAM = 'DevoProtect-linux-x86_64' if sys.platform.startswith('linux') else 'DevoProtect.exe'


def version_tuple(text):
    return tuple(int(n) for n in re.findall(r'\d+', text or '')[:4])


def enabled(argv):
    return '--no-update-check' not in argv and not REPOSITORY.startswith('OWNER/')


def latest_release():
    request = urllib.request.Request(API.format(REPOSITORY), headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'DevoProtect'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.load(response)
    assets = data.get('assets', [])
    exe = next((a for a in assets if a.get('name', '').lower() == PROGRAM.lower()), {})
    index = next((a for a in assets if a.get('name', '').lower() == INDEX), {})
    return {'version': data.get('tag_name', ''), 'page': data.get('html_url', ''),
            'exe': exe.get('browser_download_url'), 'size': exe.get('size'),
            'index': index.get('browser_download_url'), 'index_size': index.get('size')}


def index_path():
    base = (
        os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(base, INDEX)


def index_outdated(release):
    local = index_path()
    return bool(release.get('index')) and (
        not os.path.isfile(local) or os.path.getsize(local) != release.get('index_size')
    )


def check(current, found, index_needed=None):
    def work():
        try:
            release = latest_release()
        except Exception:
            return
        if version_tuple(release['version']) > version_tuple(current):
            found(release)
        elif index_needed and index_outdated(release):
            index_needed(release)
    threading.Thread(target=work, daemon=True).start()


def open_page(release):
    webbrowser.open(release.get('page') or 'https://github.com/' + REPOSITORY + '/releases')


def _download(url, target, size, minimum):
    part = target + '.new'
    request = urllib.request.Request(url, headers={'User-Agent': 'DevoProtect'})
    with urllib.request.urlopen(request, timeout=60) as response, open(part, 'wb') as out:
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
    got = os.path.getsize(part)
    if got < minimum or got != (size or got):
        os.remove(part)
        raise OSError('the download is incomplete')
    return part


def download_index(release):
    part = _download(release['index'], index_path(), release.get('index_size'), 1)
    try:
        os.replace(part, index_path())
    except OSError:
        pass


def install(release):
    exe = sys.executable if getattr(sys, 'frozen', False) else None
    if not exe or not release.get('exe'):
        open_page(release)
        return False
    new = _download(release['exe'], exe, release.get('size'), 1 << 20)
    old = exe + '.old'
    if os.path.exists(old):
        os.remove(old)
    os.replace(exe, old)
    os.replace(new, exe)
    if not sys.platform.startswith('win'):
        os.chmod(exe, 0o755)
    subprocess.Popen([exe], close_fds=True)
    return True


def cleanup():
    exe = sys.executable if getattr(sys, 'frozen', False) else None
    for leftover in ((exe + '.old', exe + '.new') if exe else ()):
        try:
            if os.path.exists(leftover):
                os.remove(leftover)
        except OSError:
            pass
    pending = index_path() + '.new'
    if os.path.exists(pending):
        try:
            os.replace(pending, index_path())
        except OSError:
            pass
