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
    --decoys=wtg,listfile,imp[,preview][,fill]   write decoy files (off by default; listfile removes the
                                                file list; preview only if named; fill fills the hash
                                                table to the header limit: no new file can be added)
    --variant=header,high-sector,bit31         malformed-MPQ header markers. No extra barrier:
                                               they ride on the sector-512 pack, which MPQ Editor already refuses
                                               to open; ignored with --skip=pack
    --bombs                                    extract-all defense: decoy files with a huge declared size, so a
                                               tool that extracts everything balloons on disk; the game never
                                               reads them. Not with --variant=bit31
    --cut-hash                                 cut the hash table: MPQ Editor and StormLib open the map read-only
                                               (they list and extract, but cannot edit it); the game plays it
                                               unchanged. Not with --variant=bit31
    --ids-non-ascii                            non-printable object IDs (control characters)
    --to-lua                                   convert a JASS script to Lua first (the map then needs 1.31+)
    --to-slk                                   convert the object data to the game's SLK tables (fewer objects are
                                               built on load, which helps Reforged; the editor no longer shows the
                                               custom objects). Needs Warcraft III installed; on Windows it is found
                                               automatically, on Linux pass --game
    --game=<folder>                            the Warcraft III folder, for --to-slk on Linux (Windows finds it)
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
    --models[=lossless|lossy]                  drop the animation keys of the MDX models that change nothing
                                               (lossless, the default); lossy also thins straight animation tracks,
                                               within 0.05 units and 0.002 radians
    --mp3[=32|48|64|96|128]                    re-encode the MP3 sounds in mono, 22 kHz, at that rate in kbps (64 by
                                               default). The big gain in a map with music, but it loses quality.
                                               Needs ffmpeg on the PATH, or --ffmpeg=<path to ffmpeg>
    --minify                                   minify the JASS script before the obfuscator: unreachable functions and
                                               unused globals out, constants written in; with --skip=obfuscate it
                                               also shortens the names
    --dds                                      convert .dds textures to BLP (smaller, native) and repoint references

  In-game anti-cheat (off by default; NOT yet proven in the game: a probe map has to be played first):
    --anti-cheat[=ledger,codes,names,bj]       add it. Pieces (default: all four): ledger = gold, lumber, hero
                                               level, attributes, skill points, XP handicap and research that no call
                                               of the map explains are undone and reported; codes = the game's own
                                               cheat codes, in single player; names = decoy names of the public cheat
                                               packs, so a pack pasted by hand does not compile (JASS); bj = Lua
                                               guard: the engine functions a Lua cheat pack replaces are restored and a
                                               replaced main is reported (Lua)
    --anti-cheat-actions=warn,nosave,defeat,end   what to do when a cheat is found (default: warn). warn = tell
                                               everyone; nosave = the map's PreloadGenEnd calls write nothing for the
                                               cheater; defeat = defeat the cheater; end = end the game. When the map
                                               itself was modified nobody can be singled out: nosave blocks every
                                               save and defeat defeats every human player
    --anti-cheat-gold-jump=N                   the gold or lumber jump with no event that counts as a cheat (400)
    --anti-cheat-codes-mode=auto|humans|reload|humans+reload   when the cheat-code detector arms (auto)
  A map can ask the result: declare `function DevoProtect_CheatUsed takes player p returns boolean` (a stub that
  returns false); the protector fills it in (true once that player, or the map, was reported).
"""


def _opt(argv, name, default=None):
    for a in argv:
        if a.startswith('--%s=' % name):
            return a.split('=', 1)[1]
    return default


VALUE_FLAGS = ('skip', 'block', 'decoys', 'variant', 'lua-layers', 'seed', 'previous-key', 'game',
               'anti-cheat-actions', 'anti-cheat-gold-jump', 'anti-cheat-codes-mode', 'ffmpeg')
OPTIONAL_VALUE_FLAGS = ('anti-cheat', 'models', 'mp3')
BARE_FLAGS = (
    'ids-non-ascii',
    'to-lua',
    'to-slk',
    'blp',
    'optimize',
    'no-recompress',
    'no-dedup',
    'no-blp-opt',
    'lossy',
    'dds',
    'bombs',
    'cut-hash',
    'minify',
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
        if not a.startswith('--') or name not in value_flags + bare_ok + OPTIONAL_VALUE_FLAGS:
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
    ac_flags = [a for a in argv if a.startswith('--anti-cheat-')]
    anti_cheat = any(a == '--anti-cheat' or a.startswith('--anti-cheat=') for a in argv)
    if ac_flags and not anti_cheat:
        raise ValueError('%s only works with --anti-cheat' % ac_flags[0].split('=')[0])
    if anti_cheat:
        parts = [x for x in (_opt(argv, 'anti-cheat', '') or '').split(',') if x]
        bad = [x for x in parts if x not in protect_app.AC_PARTS]
        if bad:
            raise ValueError('--anti-cheat: unknown %s (valid: %s)' % (', '.join(bad), ', '.join(protect_app.AC_PARTS)))
        actions = [x for x in (_opt(argv, 'anti-cheat-actions', 'warn') or '').split(',') if x]
        bad = [x for x in actions if x not in protect_app.AC_ACTIONS]
        if bad:
            raise ValueError('--anti-cheat-actions: unknown %s (valid: %s)' % (', '.join(bad),
                                                                              ', '.join(protect_app.AC_ACTIONS)))
        mode = _opt(argv, 'anti-cheat-codes-mode', 'auto')
        if mode not in protect_app.AC_CODES_MODES:
            raise ValueError(
                '--anti-cheat-codes-mode: %s is not one of %s' % (mode, ', '.join(protect_app.AC_CODES_MODES))
            )
        jump = _opt(argv, 'anti-cheat-gold-jump', '400')
        if not jump.isdigit() or int(jump) < 1:
            raise ValueError('--anti-cheat-gold-jump needs a whole number of 1 or more, not %r' % jump)
        o['anti_cheat'] = True
        for k in protect_app.AC_PARTS:
            o['ac_' + k] = not parts or k in parts
        for k in protect_app.AC_ACTIONS:
            o['ac_' + k] = k in actions
        o['ac_gold_jump'] = int(jump)
        o['ac_codes_mode'] = mode
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
    bare = [f for f in ('--lossy', '--no-recompress', '--no-dedup', '--no-blp-opt', '--minify') if f in argv]
    content = [f for f in ('--models', '--mp3', '--ffmpeg') if any(a == f or a.startswith(f + '=') for a in argv)]
    if (bare or content) and '--optimize' not in argv:
        warnings.append('%s only work with --optimize: ignored' % ' '.join(bare + content))
    models = _opt(argv, 'models', 'lossless' if '--models' in argv else None)
    if models is not None and models not in protect_app.MODELS:
        raise ValueError('--models: %s is not one of %s' % (models, ', '.join(protect_app.MODELS)))
    mp3 = _opt(argv, 'mp3', '64' if '--mp3' in argv else None)
    if mp3 is not None and (not mp3.isdigit() or int(mp3) not in protect_app.MP3_KBPS):
        raise ValueError('--mp3: %s is not one of %s (kbps)' % (mp3, ', '.join(str(k) for k in protect_app.MP3_KBPS)))
    o['non_ascii_ids'] = '--ids-non-ascii' in argv
    o['to_lua'] = '--to-lua' in argv
    o['blp'] = '--blp' in argv
    o['dds'] = '--dds' in argv
    o['bombs'] = '--bombs' in argv
    o['cut_hash'] = '--cut-hash' in argv
    o['to_slk'] = '--to-slk' in argv
    if _opt(argv, 'game') is not None:
        o['game'] = _opt(argv, 'game')
    if '--optimize' in argv:
        o['optimize'] = True
        o['opt_recompress'] = '--no-recompress' not in argv
        o['opt_dedup'] = '--no-dedup' not in argv
        o['opt_blp'] = '--no-blp-opt' not in argv
        o['opt_lossy'] = '--lossy' in argv
        o['opt_models'] = models is not None
        o['opt_models_lossy'] = models == 'lossy'
        o['opt_mp3'] = mp3 is not None
        if mp3 is not None:
            o['opt_mp3_kbps'] = int(mp3)
        o['opt_minify'] = '--minify' in argv
        if _opt(argv, 'ffmpeg'):
            o['ffmpeg'] = _opt(argv, 'ffmpeg')
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


def main(argv=None, version='0.1.7'):
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
