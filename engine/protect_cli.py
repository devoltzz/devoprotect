# The command line: the same protection recipe the window runs, driven by flags.
import os
import sys


HERE = os.path.dirname(os.path.abspath(__file__))


USAGE = r"""DevoProtect: protect a Warcraft III map from casual editing.

    DevoProtect-cli <map.w3x|campaign.w3n> [out.w3x] [options]
    DevoProtect-cli <folder> [out folder] [options]      every map of the folder, one at a time
    DevoProtect-cli --save-preset=<file.json> [options]  write the options to a preset, no map needed
    DevoProtect-cli --help | --version
  (on Linux, the same options after the program: ./DevoProtect-linux-x86_64 <map> <out> [options])

  A folder: each .w3x, .w3m and .w3n in it (not its subfolders) is protected into the out folder (default:
  <folder>_protected) under the same name, each with its own key next to it; a map that fails does not stop the
  others, and a summary at the end says why. With a folder, --previous-key is the keys folder of the previous
  release (its out folder).

    --preset=<file.json>                       start from the options of a preset (saved by the window, the site or
                                               --save-preset); the options on the command line win over it
    --save-preset=<file.json>                  write a preset with the options given (and the preset's, if any)

Options (each toggle of each step; default: full protection, ASCII IDs, no decoys, no MPQ variants):
    --skip=shuffle,obfuscate,block,decoys,pack,dds   steps to skip
    --rename-imports                           rename the imported files to meaningless names of the same length,
                                               in the archive and in every reference (object data, models and
                                               script). Off by default
    --encrypt-files                            store the files whose names the map gives encrypted in the sector-512
                                               pack (the key comes from the name). Off by default
    --remove-error-logs                        remove the compiler error messages vJass and Wurst leave in the
                                               script. Off by default
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
    --mpq-barrier=bitmap,header-128mib         MPQ barriers added at the very end (off by default; single maps,
                                               not campaigns). bitmap: a block bitmap at the end of the file;
                                               MPQ Editor does not open the map (its v1 mode opens it read-only),
                                               a few bytes. header-128mib: the archive moved to 128 MiB into the
                                               file; MPQ Editor does not open it even in v1 mode, and the map
                                               grows by about 128 MB. Both load in Reforged. With the sector-512
                                               pack MPQ Editor already refuses the map: they matter most with
                                               --skip=pack
    --ids-non-ascii                            non-printable object IDs (control characters)
    --to-lua                                   convert a JASS script to Lua first (the map then needs 1.31+)
    --to-slk                                   convert the object data to the game's SLK tables (fewer objects are
                                               built on load, which helps Reforged; the editor no longer shows the
                                               custom objects). Uses the tables of the installed Warcraft III (found
                                               on Windows); without it, the Warcraft III tables pack is downloaded
                                               from protect.devoltz.party once (1.2 MB, checked) and kept
    --game=<folder>                            the Warcraft III folder (or a tables pack folder) for --to-slk
    --lua-layers=N                             loader layers for Lua maps (default 2)
    --no-blp                                   keep the BLP textures as they are. By default the BLP JPEG textures are
                                               rewritten without loss (the same pixels, a smaller map), with either
                                               final pack (--no-blp-opt still works and means the same)
    --seed=N                                   shuffle seed (default: from the map's sha256)
    --previous-key=<tsv>                       the ID key of the PREVIOUS release of this map: every object that
                                               exists in both keeps the same shuffled ID (save codes keep working);
                                               only new objects are drawn. Campaign: the previous keys folder

  Optimize size (a step before the final pack; the final pack is the sector-512 protect, or none with --skip=pack):
    --no-optimize                              turn the step off. It is on by default with its lossless parts: the
                                               files the game never reads are removed and the JASS script loses the
                                               code nothing runs; with --skip=pack it also repacks the map with 64 KB
                                               sectors, the smallest it gets (--optimize is still accepted)
    --keep-unused                              keep the files the game never reads (imported files that nothing in
                                               the map uses; removed by default, each one listed in the report)
    --no-minify                                keep the JASS script's dead code (removed by default)
    --no-recompress / --no-dedup               turn off a part of the optimize step (both on by default;
                                               the sector-512 pack always recompresses and dedups)
    --lossy                                    only for a map above the game's 512 MiB limit: textures at half size
                                               and WAV sounds mono 22 kHz, until it fits
    --models[=lossless|lossy]                  drop the animation keys of the MDX models that change nothing
                                               (lossless, the default); lossy also thins straight animation tracks
                                               and rounds the low bits of the model numbers, so the map packs the
                                               models 15% to 20% smaller, within 0.05 units and 0.002 radians
    --mp3[=32|48|64|96|128]                    re-encode the MP3 sounds in mono, 22 kHz, at that rate in kbps (64 by
                                               default). The big gain in a map with music, but it loses quality.
                                               Needs ffmpeg on the PATH, or --ffmpeg=<path to ffmpeg>
    --minify                                   (on by default) minify the JASS script before the obfuscator:
                                               unreachable functions and unused globals out, constants written in;
                                               with --skip=obfuscate it also shortens the names
    --tga-png                                  convert the imported .tga and .png images to BLP and repoint every
                                               reference: the palette without loss when the image has 256 colors or
                                               fewer, else JPEG at high quality, and only when it is smaller in the
                                               map. Kept as they are: the map preview, what no file of the map cites,
                                               names the script builds while the game runs, sides that are not a power
                                               of two, and sides above 512 in a map older than 1.31
    --smaller-textures[=64|128|256]            lossy: the textures that only models use at half size (from their own
                                               mipmaps when the file has them), never below that side (128 by
                                               default). Icons, the interface, the loading screen and the minimap
                                               stay as they are. Far away models look the same; up close they are
                                               blurrier
    --dds                                      convert .dds textures to BLP (smaller, native) and repoint references

  In-game anti-cheat (off by default):
    --anti-cheat[=ledger,codes,names,bj,globals]
                                               add it. Pieces (default: the first four): ledger = gold, lumber, hero
                                               level, attributes, skill points, XP handicap and research that no call
                                               of the map explains are undone and reported; codes = the game's own
                                               cheat codes, in single player; names = decoy names of the public cheat
                                               packs, so a pack pasted by hand does not compile (JASS); bj = Lua
                                               guard: the engine functions a Lua cheat pack replaces are restored and a
                                               replaced main is reported (Lua); globals = Lua global watch: a global
                                               created by code pasted after the map script, a global the map does not
                                               define, or a public cheat pack's name is reported (Lua; not proven in
                                               the game yet, only when named)
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


VALUE_FLAGS = ('skip', 'block', 'decoys', 'variant', 'mpq-barrier', 'lua-layers', 'seed', 'previous-key', 'game',
               'anti-cheat-actions', 'anti-cheat-gold-jump', 'anti-cheat-codes-mode', 'ffmpeg', 'preset', 'save-preset')
OPTIONAL_VALUE_FLAGS = ('anti-cheat', 'models', 'mp3', 'smaller-textures')
BARE_FLAGS = (
    'ids-non-ascii',
    'to-lua',
    'to-slk',
    'blp',
    'no-blp',
    'optimize',
    'no-optimize',
    'keep-unused',
    'no-minify',
    'no-recompress',
    'no-dedup',
    'no-blp-opt',
    'lossy',
    'dds',
    'bombs',
    'cut-hash',
    'minify',
    'tga-png',
    'rename-imports',
    'remove-error-logs',
    'encrypt-files',
    'cli',
    'help',
    'version',
)
ON_FLAGS = (('ids-non-ascii', 'non_ascii_ids'), ('to-lua', 'to_lua'), ('blp', 'blp'), ('dds', 'dds'),
            ('bombs', 'bombs'), ('cut-hash', 'cut_hash'), ('to-slk', 'to_slk'), ('rename-imports', 'imports'),
            ('remove-error-logs', 'error_logs'), ('encrypt-files', 'encrypt'))


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
    preset = _opt(argv, 'preset')
    if preset is not None:
        if not preset or not os.path.isfile(preset):
            raise ValueError('--preset: not found: %s' % preset)
        try:
            with open(preset, encoding='utf-8') as f:
                o, preset_warnings = protect_app.read_preset(f.read())
        except (OSError, ValueError) as e:
            raise ValueError('--preset: %s' % e)
        warnings.extend('--preset: %s' % w for w in preset_warnings)

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
    barrier = names_of('mpq-barrier', tuple(k.replace('_', '-') for k in protect_app.BARRIERS))
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
            o['ac_' + k] = (k in parts) if parts else (k not in protect_app.AC_OFF)
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
    if _opt(argv, 'decoys') is not None:
        for k in protect_app.DECOYS:
            o.pop('decoy_' + k, None)
    for k in decoys:
        o['decoy_' + k] = True
    if _opt(argv, 'variant') is not None:
        for k in protect_app.VARIANTS:
            o.pop('variant_' + k, None)
    for k in variant:
        o['variant_' + k.replace('-', '_')] = True
    if _opt(argv, 'mpq-barrier') is not None:
        for k in protect_app.BARRIERS:
            o['barrier_' + k] = False
    for k in barrier:
        o['barrier_' + k.replace('-', '_')] = True
    bare = [f for f in ('--lossy', '--no-recompress', '--no-dedup', '--minify', '--tga-png', '--keep-unused',
                        '--no-minify') if f in argv]
    content = [f for f in ('--models', '--mp3', '--ffmpeg', '--smaller-textures')
               if any(a == f or a.startswith(f + '=') for a in argv)]
    if '--optimize' in argv and '--no-optimize' in argv:
        raise ValueError('--optimize and --no-optimize contradict each other: give one of them')
    optimize = '--optimize' in argv or (bool(o.get('optimize')) and '--no-optimize' not in argv)
    if '--minify' in argv and '--no-minify' in argv:
        raise ValueError('--minify and --no-minify contradict each other: give one of them')
    if (bare or content) and not optimize:
        warnings.append('%s only work with --optimize: ignored' % ' '.join(bare + content))
    models = _opt(argv, 'models', 'lossless' if '--models' in argv else None)
    if models is not None and models not in protect_app.MODELS:
        raise ValueError('--models: %s is not one of %s' % (models, ', '.join(protect_app.MODELS)))
    mp3 = _opt(argv, 'mp3', '64' if '--mp3' in argv else None)
    if mp3 is not None and (not mp3.isdigit() or int(mp3) not in protect_app.MP3_KBPS):
        raise ValueError('--mp3: %s is not one of %s (kbps)' % (mp3, ', '.join(str(k) for k in protect_app.MP3_KBPS)))
    sides = protect_app.TEXTURE_MIN_SIDES
    small = _opt(argv, 'smaller-textures', str(sides[1]) if '--smaller-textures' in argv else None)
    if small is not None and (not small.isdigit() or int(small) not in sides):
        raise ValueError('--smaller-textures: %s is not one of %s (pixels)' % (small, ', '.join(str(k) for k in sides)))
    for flag, key in ON_FLAGS:
        o[key] = '--' + flag in argv or bool(o.get(key))
    no_blp_flags = [f for f in ('--no-blp', '--no-blp-opt') if f in argv]
    if no_blp_flags and '--blp' in argv:
        raise ValueError('--blp and %s contradict each other: give one of them' % no_blp_flags[0])
    if no_blp_flags:
        o['blp'] = False
    if '--encrypt-files' in argv and 'pack' in skip:
        warnings.append('--encrypt-files only works with the sector-512 pack: ignored with --skip=pack')
    if _opt(argv, 'game') is not None:
        o['game'] = _opt(argv, 'game')
    if not optimize:
        o['optimize'] = False
    if optimize:
        o['optimize'] = True
        if '--keep-unused' in argv:
            o['opt_unused'] = False
        if '--no-minify' in argv:
            o['opt_minify'] = False
        if '--no-recompress' in argv:
            o['opt_recompress'] = False
        if '--no-dedup' in argv:
            o['opt_dedup'] = False
        if '--lossy' in argv:
            o['opt_lossy'] = True
        if models is not None:
            o['opt_models'] = True
            o['opt_models_lossy'] = models == 'lossy'
        if mp3 is not None:
            o['opt_mp3'] = True
            o['opt_mp3_kbps'] = int(mp3)
        if '--minify' in argv:
            o['opt_minify'] = True
        if '--tga-png' in argv:
            o['opt_tga_png'] = True
        if small is not None:
            o['opt_small_textures'] = True
            o['opt_texture_min_side'] = int(small)
        if _opt(argv, 'ffmpeg'):
            o['ffmpeg'] = _opt(argv, 'ffmpeg')
    for p in skip:
        o[p] = False
    no_512 = [f for f in ('--variant',) if any(a == f or a.startswith(f + '=') for a in argv)]
    if no_512 and 'pack' in skip:
        warnings.append('%s ignored: it only applies to the sector-512 repack, which is skipped' % ' '.join(no_512))
    only_64k = [f for f in ('--no-recompress', '--no-dedup') if f in argv]
    if only_64k and o.get('optimize') and 'pack' not in skip:
        warnings.append('%s ignored: the sector-512 pack always recompresses every sector and stores identical files '
                      'once (they only apply with --skip=pack)' % ' '.join(only_64k))
    return o, warnings


def main(argv=None, version='0.1.10'):
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
    save = _opt(argv, 'save-preset')
    if '--help' in argv or '-h' in argv or not (args or save):
        print(USAGE)
        return 0 if ('--help' in argv or '-h' in argv) else 2
    try:
        o, warnings = parse_options(argv)
        if len(args) > 2:
            raise ValueError('too many arguments: %s (expected <map> [out])' % ' '.join(args))
    except ValueError as e:
        print('ERROR: %s' % e)
        return 2
    for w in warnings:
        print('WARNING: %s' % w)
    if save is not None:
        if not save:
            print('ERROR: --save-preset needs a file name')
            return 2
        try:
            with open(save, 'w', encoding='utf-8', newline='\n') as f:
                f.write(protect_app.preset_text(o))
        except OSError as e:
            print('ERROR: --save-preset: %s' % e)
            return 2
        print('preset saved: %s' % save)
        if not args:
            return 0
    map_path = args[0]
    if os.path.isdir(map_path):
        return _folder(map_path, args[1] if len(args) > 1 else None, o)
    if not os.path.isfile(map_path):
        print('map not found: %s' % map_path)
        return 2
    out_path = args[1] if len(args) > 1 else None
    if any(o.get(k) for k in ('opt_models', 'opt_mp3', 'dds', 'opt_tga_png', 'opt_small_textures')):
        for w in protect_app.option_warnings(o, protect_app.inspect_map(map_path)):
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


def _folder(folder, out, o):
    import protect_app

    def emit(ev):
        t = ev.get('type')
        if t == 'progress' and ev.get('text') and ev.get('step') == 'map':
            print(ev['text'])
        elif t == 'progress' and ev.get('text'):
            print('  [%s] %s' % (ev.get('step') or '-', ev['text']))
        elif t == 'error':
            print('ERROR: %s' % ev.get('message'))
    res = protect_app.run_folder({'task': 'protect', 'folder': folder, 'out': out, 'options': o}, emit)
    if not res.get('maps'):
        return 2
    print()
    for st, tx in res.get('lines', []):
        print(('  ! ' if st == 'bad' else '  ') + tx)
    print('\n%s' % res.get('summary'))
    print('  keys (keep them, not in the maps): next to each map in %s' % res['out'])
    return 0 if res.get('ok') else 1


def install_launcher():
    return None


if __name__ == '__main__':
    sys.exit(main())
