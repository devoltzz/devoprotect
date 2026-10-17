# The command line: the same protection recipe the window runs, driven by flags.
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))


USAGE = r"""DevoProtect: protect a Warcraft III map from casual editing.

    DevoProtect-cli <map.w3x|campaign.w3n> [out.w3x] [options]
    DevoProtect-cli --help | --version
  (on Linux, the same options after the program: ./DevoProtect-linux-x86_64 <map> <out> [options])

Options (each toggle of each step; default: full protection, ASCII IDs, no decoys, no MPQ variants):
    --skip=shuffle,obfuscate,block,decoys,pack,dds   steps to skip
    --block=w3i,wtg,extra,units,doo,w3r        the editor-file mechanisms (default: w3i,wtg,extra,units,doo)
    --decoys=wtg,listfile,imp[,preview][,fill]   write decoy files (off by default; preview only if
                                                named; fill fills the hash table to the header limit:
                                                no new file can be added to the map)
    --variant=header,high-sector,bit31         malformed-MPQ header markers. No extra barrier:
                                               they ride on the sector-512 pack, which MPQ Editor already refuses
                                               to open; ignored with --skip=pack
    --ids-non-ascii                            non-printable object IDs (control characters)
    --to-lua                                   convert a JASS script to Lua first (the map then needs 1.31+)
    --lua-layers=N                             loader layers for Lua maps (default 2)
    --blp                                      lossless BLP re-optimization in the protect pack (sector 512)
    --seed=N                                   shuffle seed (default: from the map's sha256)
    --previous-key=<tsv>                       the ID key of the PREVIOUS release of this map: every object that
                                               exists in both keeps the same shuffled ID (save codes keep working);
                                               only new objects are drawn. Campaign: the previous keys folder

  Optimize size (a step before the final pack; the final pack is the sector-512 protect, or none with --skip=pack):
    --optimize                                 turn the step on. With the sector-512 pack it rewrites the BLP
                                               textures without loss (that pack already recompresses every sector
                                               and stores identical files once); with --skip=pack it repacks the
                                               map with 64 KB sectors, the smallest it gets
    --no-recompress / --no-dedup / --no-blp-opt   turn off a part of the optimize step (all on by default;
                                               the sector-512 pack always recompresses and dedups)
    --lossy                                    only for a map above the game's 512 MiB limit: textures at half size
                                               and WAV sounds mono 22 kHz, until it fits
    --dds                                      convert .dds textures to BLP (smaller, native) and repoint references
"""


def _opt(argv, name, default=None):
    for a in argv:
        if a.startswith('--%s=' % name):
            return a.split('=', 1)[1]
    return default


VALUE_FLAGS = ('skip', 'block', 'decoys', 'variant', 'lua-layers', 'seed', 'previous-key')
BARE_FLAGS = (
    'ids-non-ascii',
    'to-lua',
    'blp',
    'optimize',
    'no-recompress',
    'no-dedup',
    'no-blp-opt',
    'lossy',
    'dds',
    'cli',
    'help',
    'version',
)


def positional(argv):
    return [a for a in argv if not a.startswith('-')]


def parse_options(argv, extra_value=(), extra_bare=()):
    import protect_app
    value_flags, bare_ok = VALUE_FLAGS + tuple(extra_value), BARE_FLAGS + tuple(extra_bare)
    for a in argv:
        if a == '-h' or not a.startswith('-'):
            continue
        name, has_value = a[2:].split('=', 1)[0], '=' in a
        if not a.startswith('--') or name not in value_flags + bare_ok:
            raise ValueError('unknown option %s (see --help)' % a)
        if name in value_flags and not has_value:
            raise ValueError('--%s needs a value: --%s=...' % (name, name))
        if name in bare_ok and has_value:
            raise ValueError('--%s takes no value' % name)
    o = protect_app.default_options()
    warnings = []

    def names_of(name, valid):
        items = [x for x in (_opt(argv, name, '') or '').split(',') if x]
        bad = [x for x in items if x not in valid]
        if bad:
            raise ValueError('--%s: unknown %s (valid: %s)' % (name, ', '.join(bad), ', '.join(valid)))
        return items
    skip = names_of('skip', tuple(protect_app.STEP_KEYS) + ('dds',))
    block = names_of('block', protect_app.BLOCKS)
    decoys = names_of('decoys', tuple(protect_app.DECOYS))
    variant = names_of('variant', tuple(k.replace('_', '-') for k in protect_app.VARIANTS))
    if _opt(argv, 'lua-layers'):
        o['lua_layers'] = int(_opt(argv, 'lua-layers'))
    if _opt(argv, 'seed'):
        o['seed'] = int(_opt(argv, 'seed'))
    if _opt(argv, 'previous-key') is not None:
        key_path = _opt(argv, 'previous-key')
        if not key_path or not os.path.exists(key_path):
            raise ValueError('--previous-key: not found: %s' % key_path)
        o['previous_key'] = key_path
        if 'shuffle' in skip:
            warnings.append('--previous-key ignored: the ID shuffle is skipped')
    if _opt(argv, 'block') is not None:
        for k in protect_app.BLOCKS:
            o['block_' + k] = False
        for k in block:
            o['block_' + k] = True
    for k in decoys:
        o['decoy_' + k] = True
    for k in variant:
        o['variant_' + k.replace('-', '_')] = True
    bare = [f for f in ('--lossy', '--no-recompress', '--no-dedup', '--no-blp-opt') if f in argv]
    if bare and '--optimize' not in argv:
        warnings.append('%s only work with --optimize: ignored' % ' '.join(bare))
    o['non_ascii_ids'] = '--ids-non-ascii' in argv
    o['to_lua'] = '--to-lua' in argv
    o['blp'] = '--blp' in argv
    o['dds'] = '--dds' in argv
    if '--optimize' in argv:
        o['optimize'] = True
        o['opt_recompress'] = '--no-recompress' not in argv
        o['opt_dedup'] = '--no-dedup' not in argv
        o['opt_blp'] = '--no-blp-opt' not in argv
        o['opt_lossy'] = '--lossy' in argv
    for p in skip:
        o[p] = False
    no_512 = [f for f in ('--variant', '--blp') if any(a == f or a.startswith(f + '=') for a in argv)]
    if no_512 and 'pack' in skip:
        warnings.append('%s ignored: they only apply to the sector-512 repack, which is skipped' % ' '.join(no_512))
    only_64k = [f for f in ('--no-recompress', '--no-dedup') if f in argv]
    if only_64k and o.get('optimize') and 'pack' not in skip:
        warnings.append('%s ignored: the sector-512 pack always recompresses every sector and stores identical files '
                      'once (they only apply with --skip=pack)' % ' '.join(only_64k))
    return o, warnings


def main(argv=None, version='0.1.1'):
    import protect_app
    argv = sys.argv[1:] if argv is None else list(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    if '--version' in argv:
        print('DevoProtect %s' % version)
        return 0
    args = positional(argv)
    if '--help' in argv or '-h' in argv or not args:
        print(USAGE)
        return 0 if ('--help' in argv or '-h' in argv) else 2
    try:
        o, warnings = parse_options(argv)
        if len(args) > 2:
            raise ValueError('too many arguments: %s (expected <map> [out])' % ' '.join(args))
    except ValueError as e:
        print('ERROR: %s' % e)
        return 2
    map_path = args[0]
    if not os.path.isfile(map_path):
        print('map not found: %s' % map_path)
        return 2
    out_path = args[1] if len(args) > 1 else None
    for w in warnings:
        print('WARNING: %s' % w)
    job = {'task': 'protect', 'map': map_path, 'out': out_path, 'options': o}
    state = {'ok': False}

    def emit(ev):
        t = ev.get('type')
        if t == 'progress' and ev.get('text'):
            print('  [%s] %s' % (ev.get('step') or '-', ev['text']))
        elif t == 'error':
            print('ERROR: %s' % ev.get('message'))
        elif t == 'result':
            state.update(ev)
    res = protect_app.run_job(job, emit)
    if res.get('lines'):
        print()
        for st, tx in res.get('lines', []):
            print(('  ! ' if st == 'bad' else '  ') + tx)
        print('\n%s' % res.get('summary'))
        if res.get('ok') and res.get('bytes_out'):
            print('  %d -> %d bytes (%.1fs)' % (res['bytes_in'], res['bytes_out'], res.get('seconds', 0)))
        if res.get('ok') and res.get('key'):
            print('  key (keep it, not in the map): %s' % res['key'])
    return 0 if res.get('ok') else 1


def install_launcher():
    return None


if __name__ == '__main__':
    sys.exit(main())
