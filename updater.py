# Checks GitHub for a newer release and replaces the executable when the user agrees.
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

REPOSITORY = 'devoltzz/devoprotect'
API = 'https://api.github.com/repos/{}/releases/latest'
TIMEOUT = 6
INDEX = 'names.npz'
PROGRAM = 'DevoProtect-linux-x86_64' if sys.platform.startswith('linux') else 'DevoProtect.exe'
CA_FILES = ('/etc/ssl/certs/ca-certificates.crt', '/etc/pki/tls/certs/ca-bundle.crt', '/etc/ssl/ca-bundle.pem',
            '/etc/ssl/cert.pem', '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem')
HOSTS = ('github.com', 'githubusercontent.com')
_opener = []


class _GitHubOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        import urllib.parse
        address = urllib.parse.urlparse(newurl)
        host = (address.hostname or '').lower()
        if address.scheme != 'https' or not any(host == h or host.endswith('.' + h) for h in HOSTS):
            raise OSError('the download was sent to %s, not to GitHub' % (address.hostname or newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request, timeout):
    if not _opener:
        context = ssl.create_default_context()
        if not context.cert_store_stats().get('x509_ca'):
            for path in CA_FILES:
                if os.path.isfile(path):
                    try:
                        context.load_verify_locations(cafile=path)
                        break
                    except (OSError, ssl.SSLError):
                        continue
        _opener.append(urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), _GitHubOnly))
        urllib.request.install_opener(_opener[0])
    return _opener[0].open(request, timeout=timeout)


def version_tuple(text):
    return tuple(int(n) for n in re.findall(r'\d+', text or '')[:4])


def enabled(argv):
    return '--no-update-check' not in argv and not REPOSITORY.startswith('OWNER/')


def latest_release():
    request = urllib.request.Request(API.format(REPOSITORY), headers={
        'Accept': 'application/vnd.github+json', 'User-Agent': 'DevoProtect'})
    with _open(request, TIMEOUT) as response:
        data = json.load(response)
    assets = data.get('assets', [])
    exe = next((a for a in assets if a.get('name', '').lower() == PROGRAM.lower()), {})
    index = next((a for a in assets if a.get('name', '').lower() == INDEX), {})
    sums = next((a for a in assets if a.get('name', '') == 'SHA256SUMS.txt'), {})
    cli = next((a for a in assets if a.get('name', '') == 'DevoProtect-cli.exe'), {})
    return {'version': data.get('tag_name', ''), 'page': data.get('html_url', ''),
            'exe': exe.get('browser_download_url'), 'size': exe.get('size'), 'digest': exe.get('digest'),
            'index_digest': index.get('digest'),
            'index': index.get('browser_download_url'), 'index_size': index.get('size'),
            'sums': sums.get('browser_download_url'), 'cli': cli.get('browser_download_url'),
            'cli_size': cli.get('size')}


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
    page = release.get('page') or ''
    if not page.startswith('https://github.com/' + REPOSITORY + '/'):
        page = 'https://github.com/' + REPOSITORY + '/releases'
    webbrowser.open(page)


def _download(url, target, size, minimum):
    part, new = target + '.part', target + '.new'
    request = urllib.request.Request(url, headers={'User-Agent': 'DevoProtect'})
    try:
        with _open(request, 60) as response, open(part, 'wb') as out:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)
        got = os.path.getsize(part)
        if got < minimum or got != (size or got):
            raise OSError('the download is incomplete')
        os.replace(part, new)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise
    return new


def _check_digest(path, digest, required=True):
    import hashlib
    if not digest:
        if required:
            os.remove(path)
            raise OSError('the release gives no checksum for this file')
        return
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    if 'sha256:' + h.hexdigest() != digest.lower():
        os.remove(path)
        raise OSError('the download does not match the checksum of the release')


def _index_ready(path):
    import zipfile
    return zipfile.is_zipfile(path)


def _verify(path, name, release):
    if not release.get('sums'):
        return
    request = urllib.request.Request(release['sums'], headers={'User-Agent': 'DevoProtect'})
    with urllib.request.urlopen(request, timeout=60) as response:
        sums = response.read().decode('utf-8', 'replace')
    expected = next((line.split()[0].lower() for line in sums.splitlines()
                     if len(line.split()) == 2 and line.split()[1] == name), None)
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            digest.update(block)
    if digest.hexdigest() != expected:
        os.remove(path)
        raise OSError('the download of %s does not match SHA256SUMS.txt' % name)


def download_index(release):
    part = _download(release['index'], index_path(), release.get('index_size'), 1)
    _check_digest(part, release.get('index_digest'), required=False)
    if not _index_ready(part):
        os.remove(part)
        raise OSError('the downloaded file name index is damaged')
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
    _verify(new, PROGRAM, release)
    _check_digest(new, release.get('digest'))
    old = exe + '.old'
    if os.path.exists(old):
        os.remove(old)
    os.replace(exe, old)
    for attempt in range(5):
        try:
            os.replace(new, exe)
            break
        except OSError:
            if attempt == 4:
                os.replace(old, exe)
                raise
            time.sleep(0.3)
    if not sys.platform.startswith('win'):
        os.chmod(exe, 0o755)
    cli = os.path.join(os.path.dirname(exe), 'DevoProtect-cli.exe')
    if sys.platform.startswith('win') and release.get('cli') and os.path.isfile(cli):
        try:
            part = _download(release['cli'], cli, release.get('cli_size'), 1 << 20)
            _verify(part, 'DevoProtect-cli.exe', release)
            os.replace(part, cli)
        except OSError:
            pass
    subprocess.Popen([exe], close_fds=True, env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
    return True


def cleanup():
    exe = sys.executable if getattr(sys, 'frozen', False) else None
    for leftover in ((exe + '.old', exe + '.new', exe + '.part') if exe else ()) + (index_path() + '.part',):
        try:
            if os.path.exists(leftover):
                os.remove(leftover)
        except OSError:
            pass
    pending = index_path() + '.new'
    if os.path.exists(pending):
        try:
            if _index_ready(pending):
                os.replace(pending, index_path())
            else:
                os.remove(pending)
        except OSError:
            pass
