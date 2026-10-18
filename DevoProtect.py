# DevoProtect: the window, the command line and the text mode.
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(getattr(sys, '_MEIPASS', HERE), 'engine')
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

VERSION = '0.1.5'


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
    flags_cli = any(a.startswith(('--skip', '--block', '--decoys', '--variant', '--ids-non-ascii', '--optimize',
                                  '--lossy', '--no-recompress', '--no-dedup', '--no-blp-opt', '--dds', '--blp',
                                  '--lua-layers', '--seed', '--previous-key')) for a in argv)
    wants_cli = ('--text' not in argv and
                (exe_cli or '--cli' in argv or '--help' in argv or '-h' in argv or '--version' in argv or flags_cli
                 or len(args) >= 2 or (args and not os.path.isfile(args[0]))))
    if wants_cli:
        return protect_cli.main([a for a in argv if a != '--cli'], VERSION)
    if '--text' in argv:
        log = next((a.split('=', 1)[1] for a in argv if a.startswith('--log=')), None)
        out = open(log, 'w', encoding='utf-8') if log else sys.stdout
        try:
            out.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
        import protect_app
        args = protect_cli.positional(argv)
        if not args or not os.path.isfile(args[0]):
            print('usage: --text <map> [out] [options of the command line] [--log=<file>]', file=out)
            return 2
        try:
            opts, warnings = protect_cli.parse_options(argv, extra_value=('log',), extra_bare=('text',))
            if len(args) > 2:
                raise ValueError('too many arguments: %s (expected <map> [out])' % ' '.join(args))
        except ValueError as e:
            print('ERROR: %s' % e, file=out)
            return 2
        for w in warnings:
            print('WARNING: %s' % w, file=out)
        job ={'task': 'protect', 'map': args[0], 'out': args[1] if len(args) > 1 else None, 'options': opts}

        def emit(ev):
            if ev.get('type') == 'progress' and ev.get('text'):
                print('   [%s] %s' % (ev.get('step') or '-', ev['text']), file=out)
            elif ev.get('type') == 'error':
                print('ERROR: %s' % ev.get('message'), file=out)
            elif ev.get('type') == 'result':
                print('', file=out)
                for _st, tx in ev.get('lines', []):
                    print('   ' + tx, file=out)
                print('\n%s' % ev.get('summary'), file=out)
        res = protect_app.run_job(job, emit)
        if log:
            out.close()
        return 0 if res.get('ok') else 1
    import protect_app
    protect_cli.install_launcher()
    protect_app.run(VERSION, os.path.normpath(args[0]) if args and os.path.isfile(args[0]) else None, icon_path())
    return 0


def _text_options(argv, protect_app):
    import protect_cli
    return protect_cli.parse_options(argv, extra_value=('log',), extra_bare=('text',))[0]


if __name__ == '__main__':
    sys.exit(main())
