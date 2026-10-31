# DevoProtect: the window, the command line and the text mode.
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(getattr(sys, '_MEIPASS', HERE), 'engine')
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

VERSION = '0.1.19'


def _no_console():
    for name in ('stdout', 'stderr'):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))


def icon_path():
    base = getattr(sys, '_MEIPASS', os.path.join(HERE, 'assets'))
    p = os.path.join(base, 'devoprotect.png' if sys.platform.startswith('linux') else 'devoprotect.ico')
    return p if os.path.isfile(p) else None


def main(argv=None):
    import multiprocessing
    multiprocessing.freeze_support()
    argv = sys.argv[1:] if argv is None else list(argv)
    _no_console()
    import protect_cli
    exe_cli = 'cli' in os.path.basename(sys.argv[0]).lower()
    args = [a for a in argv if not a.startswith('--')]
    cli_options = tuple(f for f in protect_cli.VALUE_FLAGS + protect_cli.BARE_FLAGS + protect_cli.OPTIONAL_VALUE_FLAGS
                        if f not in ('cli', 'help', 'version'))
    flags_cli = any(a.startswith('--') and a[2:].split('=', 1)[0] in cli_options for a in argv)
    wants_cli = ('--text' not in argv and
                (exe_cli or '--cli' in argv or '--help' in argv or '-h' in argv or '--version' in argv or flags_cli
                 or len(args) >= 2 or (args and not os.path.isfile(args[0]))))
    if wants_cli:
        return protect_cli.main([a for a in argv if a not in ('--cli', '--text')], VERSION)
    if '--text' in argv:
        return protect_cli.main([a for a in argv if a != '--text'], VERSION)
    import protect_app
    protect_cli.install_launcher()
    protect_app.run(VERSION, os.path.normpath(args[0]) if args and os.path.isfile(args[0]) else None, icon_path())
    return 0


if __name__ == '__main__':
    sys.exit(main())
