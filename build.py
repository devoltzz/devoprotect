# Builds DevoProtect with PyInstaller: the window and the command line in one file each.
import os
import re
import sys

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(ROOT, 'engine')
LINUX = sys.platform.startswith('linux')
EXCLUDE = ('tkinter', 'matplotlib', 'pytest', 'setuptools', 'pip', 'unittest', 'pydoc_data', 'notebook', 'IPython',
           'lupa.lua51', 'lupa.lua52', 'lupa.lua54', 'lupa.lua55', 'lupa.luajit20', 'lupa.luajit21')
VERSION_FILE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}), prodvers=({v}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'devoltzz'),
      StringStruct('FileDescription', 'DevoProtect'),
      StringStruct('FileVersion', '{s}'),
      StringStruct('ProductName', 'DevoProtect'),
      StringStruct('ProductVersion', '{s}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def app_version():
    text = open(os.path.join(ROOT, 'DevoProtect.py'), encoding='utf-8').read()
    return re.search(r"^VERSION = '([^']+)'", text, re.M).group(1)


def build(name, console, work):
    icon = os.path.join(ROOT, 'assets', 'devoprotect.ico')
    args = [os.path.join(ROOT, 'DevoProtect.py'), '--name', name, '--onefile', '--noconfirm', '--clean',
            '--workpath', work, '--distpath', os.path.join(ROOT, 'dist'), '--specpath', work,
            '--console' if console else '--windowed', '--paths', ENGINE,
            '--add-data', os.path.join(ROOT, 'ui') + os.pathsep + 'ui',
            '--add-data', icon + os.pathsep + '.']
    for folder, dirs, files in os.walk(ENGINE):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        rel = os.path.relpath(folder, ENGINE)
        for f in sorted(files):
            if f.endswith('.py'):
                args += ['--hidden-import', f[:-3]]
            elif f in ('pjass.exe', 'pjass'):
                if f == ('pjass' if LINUX else 'pjass.exe'):
                    args += ['--add-binary', os.path.join(folder, f) + os.pathsep + rel]
            elif not f.endswith(('.pyc', '.c')):
                args += ['--add-data', os.path.join(folder, f) + os.pathsep + rel]
    pjass = os.environ.get('PJASS')
    if pjass and os.path.isfile(pjass):
        args += ['--add-binary', pjass + os.pathsep + '.']
    elif not os.path.isfile(os.path.join(ENGINE, 'pjass' if LINUX else 'pjass.exe')):
        print('pjass not found (engine/ or PJASS): JASS obfuscation runs without its pjass check')
    args += ['--hidden-import', 'lupa.lua53']
    for module in EXCLUDE:
        args += ['--exclude-module', module]
    if not LINUX:
        import importlib.util
        spec = importlib.util.find_spec('zopfli')
        if spec and spec.origin:
            libs = os.path.join(os.path.dirname(os.path.dirname(spec.origin)), 'zopfli.libs')
            if os.path.isdir(libs):
                for f in sorted(os.listdir(libs)):
                    args += ['--add-binary', os.path.join(libs, f) + os.pathsep + 'zopfli.libs']
    if LINUX:
        from PIL import Image
        png = os.path.join(work, 'devoprotect.png')
        with Image.open(icon) as im:
            im.save(png)
        args += ['--add-data', png + os.pathsep + '.']
    else:
        version = app_version()
        numbers = (re.findall(r'\d+', version) + ['0'] * 4)[:4]
        version_file = os.path.join(work, 'version.txt')
        with open(version_file, 'w', encoding='utf-8') as f:
            f.write(VERSION_FILE.replace('{v}', ', '.join(numbers)).replace('{s}', version))
        args += ['--icon', icon, '--version-file', version_file]
    PyInstaller.__main__.run(args)


def main():
    work = os.path.join(ROOT, 'build', 'linux' if LINUX else 'windows')
    os.makedirs(work, exist_ok=True)
    build('DevoProtect', console=False, work=work)
    if not LINUX:
        build('DevoProtect-cli', console=True, work=work)
    print('built in', os.path.join(ROOT, 'dist'))


if __name__ == '__main__':
    main()
