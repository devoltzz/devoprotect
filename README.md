<div align="center">

<img src="docs/images/icon.png" width="96" alt="">

# DevoProtect

Protect your Warcraft III maps from casual editing.

[![Latest release](https://img.shields.io/github/v/release/devoltzz/devoprotect?label=release)](https://github.com/devoltzz/devoprotect/releases/latest)
[![Downloads](https://img.shields.io/github/downloads/devoltzz/devoprotect/total)](https://github.com/devoltzz/devoprotect/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20Web-informational)](#get-it)

**[Download](https://github.com/devoltzz/devoprotect/releases/latest)** ·
**[Use it in the browser](https://protect.devoltz.party)** ·
**[Report a problem](https://github.com/devoltzz/devoprotect/issues/new)**

</div>

DevoProtect takes a finished map (`.w3x`, `.w3m`) or campaign (`.w3n`) and writes a protected copy next to it. It
closes the easy ways into a map: opening it in the World Editor, opening it in MPQ Editor, reading the script. The
default options also make the map smaller without losing anything. Your original file is left alone. Keep it, because
there is no undo.

## Get it

| | |
|---|---|
| **Browser** | [protect.devoltz.party](https://protect.devoltz.party). Nothing to install. The map is processed inside the page and never leaves your computer. |
| **Windows** | `DevoProtect.exe` from [Releases](https://github.com/devoltzz/devoprotect/releases/latest). `DevoProtect-cli.exe` is the command line. |
| **Linux** | `DevoProtect-linux-x86_64` (x86-64, glibc 2.35 or newer: Ubuntu 22.04+, Debian 12+, Fedora 36+, Mint 21+). `chmod +x` it and run it. The window needs WebKitGTK: `sudo apt install gir1.2-webkit2-4.1` or `sudo dnf install webkit2gtk4.1`. With a map and an output name it runs as the command line. |

It works on maps for the classic game (1.24 to 1.29) and for Reforged, in English and 16 other languages. The program
tells you when a new version is out and checks every download against the release's `SHA256SUMS.txt`.

## Use it

Open a map (or drop it on the window), pick a mode and click **Protect**.

| Mode | What it does |
|---|---|
| **Full protection** | The recommended set: every step that is on by default in the table below. |
| **Script only** | The object IDs and the script. No file is removed and the archive stays a normal one. |
| **Archive only** | Editor-only and unused files removed, the BLP textures rewritten without loss and the MPQ barrier. The script stays readable. |
| **Custom** | Every option on its own. |

As soon as you choose a map, the window checks it (JASS or Lua, single map or campaign, the game it was made for, the
size) and lists the steps that will run. An option that can't work with the rest, or with that map, is locked with
the reason next to it, so a combination that would stop halfway can't be started. When the job ends you get the size
before and after, the time, the warnings and where the key was saved.

- **Protect a folder** (on the site, **Protect several maps**) protects every map of a folder with the same options,
  each with its own key. A map that is refused doesn't stop the others, and the summary says why.
- **Save preset** and **Load preset** keep your options in a small JSON file, so every release goes out with the same
  set. The command line reads it with `--preset=<file>`.

## What each step does

| Step | Default | What it does |
|---|---|---|
| **Shuffle object IDs** | on | Your custom IDs (`h000`, `A00B`...) become meaningless ones, in the object data and in the script, and the ID key is saved next to the output. Optional: non-printable IDs, and imported files renamed to random names of the same length. |
| **Obfuscate the script** | on | JASS or Lua. Your function and variable names are gone for good, and the strings and raw codes are scrambled. A JASS script is checked with pjass before it is saved. A Lua script also gets encrypted strings and loader layers. Optional: convert JASS to Lua first, and remove the error messages vJass and Wurst leave in the script. |
| **Remove editor-only files** | on | Triggers, unit placement and editor counters go out, so the map no longer opens in the World Editor as a normal map. Anything the game reads stays. Optional: the object data as the game's own SLK tables. |
| **Optimize size** | on | By default only what loses nothing: the files the game never reads are removed (the report lists each one), the JASS script loses the code nothing runs, the BLP textures are rewritten with the same pixels and the map is repacked. Optional and lossy: smaller MDX models, MP3 sounds in mono, model textures at half size, textures to DDS (Reforged maps only). |
| **MPQ barrier** | on | A few bytes at the end of the file, and MPQ Editor does not open the map (its v1 mode opens it read-only). Single maps only. Optional: the archive moved 128 MiB into the file, which MPQ Editor does not open even in v1 mode; the map grows by about 128 MB. |
| **Decoys** | off | Fake trigger files and imports, the file list removed, the hash table filled so no file can be added, extract-all bombs (a tool that extracts everything fills gigabytes of disk) and a cut hash table (MPQ tools can list and extract, but not edit). |
| **In-game anti-cheat** | off | Checks that run while the map plays: gold, lumber and hero changes no part of the map explains are undone, the game's cheat codes are caught in single player, and a cheat pack pasted by hand does not compile (JASS) or has the engine functions it replaced restored (Lua). It can warn everyone, block the cheater's saves, defeat the cheater or end the game. |
| **Not allowed to edit** | off | A small file in the archive and a comment in the script. Tools that respect the mark refuse to unprotect or change the map. It is a request, not a lock, and it works in every mode. |

Every step is checked against what it was supposed to write. If anything else changed, the job stops and nothing is
saved.

## The ID key

Shuffling the IDs writes a key, `<map>_ids.tsv`, next to the output (not inside the map). Keep it. For the next
version of the map, give it back as **Previous key** and every object keeps the ID it had, so save codes from the old
version still load. A campaign or a folder takes the folder with the keys. A key from another map gives a warning
instead of going in silently, the summary says how many old IDs were reused, and `devoprotect_keys.json` next to the
output keeps the key of every release.

## What it can't do

It can't stop someone who really wants in. The map runs on the player's computer, so it can always be dumped from
memory and rebuilt by hand, and MPQ Editor's Game Extractor reads the files of a classic game while it runs. Every
layer here works on the file, so that is the limit. DevoProtect closes the easy routes and takes your names out of
the script. It is about publishing and authorship, not secrecy, and the code is open on purpose.

## Questions

**Should I convert my JASS map to Lua?** You don't need to: both lose your names for good. Lua adds the encrypted
strings and the loader layers, which slow down someone who opens the file, though anyone who reads DevoProtect's code
can undo them. The map then needs Warcraft III 1.31 or newer. Maps that use natives of KK, YDWE, DzAPI or other
platforms, or that carry their own `Blizzard.j` or `common.j`, are refused with the reason. A few things work
differently in the game's Lua; the log lists the ones your script has, so test the converted map in game.

**What does converting the object data to SLK do?** Units, items and abilities become the game's own tables, so fewer
objects are built when the map loads. That helps with Reforged disconnects on maps with hundreds of abilities. It is
not protection, the map grows because it carries the tables, and it still has to be proven in game. It uses the tables
of the game the map is for: the installed Warcraft III, or for a Reforged map a 1.2 MB pack downloaded once from
protect.devoltz.party. Without them the step is skipped and the report says why.

**Can my map ask the anti-cheat what it found?** Yes. Declare
`function DevoProtect_CheatUsed takes player p returns boolean` and have it return `false`; the protector fills it in.
It returns `true` for a player who was reported, or for everyone when the map itself was modified (in a Lua map it is
the global function of the same name). Use it to refuse a save code or hold back a reward. Block saves acts on the
map's own calls to `PreloadGenEnd`.

**What does the anti-cheat miss?** A player who edits the game's memory without touching the values it watches. The
defeat action does nothing against `strengthandhonor`; use the end action for that. I tested it in game in single
player only: multiplayer games, cheat packs and Lua maps are still to be proven, so test it on your map before a
release.

**How much smaller does the map get?** With the defaults, which lose nothing, my 12 test maps came out 15.7% smaller
in total than the same protection without them, from 0.4% to 45.5% per map: mostly the files the game never reads,
then the BLP textures and the shorter script. The lossy options depend on what the map carries: MP3 re-encoding made
maps with music 46% to 79% smaller, lossy models 1.4% to 9%, half-size model textures 23% on a 50 MB map. Listen to
the map and look at it in game before you release with them. On a classic map the report warns when the protected
copy passes 8 MB, the most that Warcraft III 1.24 to 1.27a sends to the other players of a game.

**Which files does it remove?** A file stays when the game reads it by its name, when a file the game reads names it
(the script, the object data, a model naming its texture), or when the script builds names that start the way it
does. What goes is usually a pack of models imported whole, of which the map uses a few. The report lists every
removed file. If your map loads a file in a way the protector can't see, like a name a player types, use
`--keep-unused` and play the map before you release it.

**Is my map sent anywhere?** No. Everything runs on your computer, or inside the page on the site. The program only
asks GitHub whether a new version is out, and downloads the SLK tables pack if you ask for that step without the game
installed. On the site, very big maps can run out of the browser's memory (about 2 GB); use the program for those.

**Does the site give the same map as the program?** The same files inside. The site packs them with the browser's
zlib, so the map is a little bigger and its bytes differ. It can't run ffmpeg, so it leaves the MP3 sounds alone.

## Command line

```
DevoProtect-cli <map.w3x|campaign.w3n> [out.w3x] [options]
DevoProtect-cli <folder> [out folder] [options]
DevoProtect-cli --save-preset=<file.json> [options]
```

With no options you get Full protection. A folder protects every `.w3x`, `.w3m` and `.w3n` in it into
`<folder>_protected`, each with its key next to it. On Linux the same options go after `./DevoProtect-linux-x86_64`.
`--help` explains every option in full.

**Protection**

| Option | |
|---|---|
| `--skip=shuffle,obfuscate,block,decoys,dds` | Steps to skip. |
| `--previous-key=<tsv>` | The ID key of your previous release (a campaign or a folder takes the keys folder). |
| `--ids-non-ascii` | Non-printable object IDs. |
| `--rename-imports` | Rename the imported files to random names of the same length, everywhere they are used. |
| `--to-lua` | Convert a JASS script to Lua first (the map then needs 1.31 or newer). |
| `--lua-layers=N` | Loader layers of a Lua script (default: 2 up to a 512 KB script, 1 above). |
| `--remove-error-logs` | Remove the vJass and Wurst error messages from the script. |
| `--block=w3i,wtg,extra,units,doo,w3r` | Which editor files to remove (default: all but `w3r`). |
| `--to-slk` | Convert the object data to the game's SLK tables; `--game=<folder>` says where the game is. |
| `--mpq-barrier=bitmap,header-128mib` | The MPQ barriers (default `bitmap`; `--mpq-barrier=` with nothing turns them off). |
| `--decoys=wtg,listfile,imp,preview,fill` | Decoy files (`listfile` removes the file list, `fill` fills the hash table). |
| `--bombs` | Extract-all bombs. |
| `--cut-hash` | Cut the hash table: MPQ Editor and StormLib open the map read-only. |
| `--no-edit` | Mark the map as not allowed to edit. |
| `--seed=N` | Shuffle seed (default: taken from the map). |

**Size**

| Option | |
|---|---|
| `--no-optimize` | Turn the optimize step off. |
| `--keep-unused` | Keep the files the game never reads. |
| `--no-minify` | Keep the dead code of the JASS script. |
| `--no-blp` | Keep the BLP textures as they are. |
| `--no-recompress`, `--no-dedup` | Turn a part of the repack off. |
| `--models[=lossless\|lossy]` | Drop the MDX animation keys that change nothing; `lossy` also rounds the model numbers. |
| `--mp3[=32\|48\|64\|96\|128]` | Lossy: MP3 sounds in mono, 22 kHz, at that rate (default 64). Needs ffmpeg on the PATH or `--ffmpeg=<path>`. |
| `--smaller-textures[=64\|128\|256]` | Lossy: the textures only models use at half size, never below that side (default 128). |
| `--tga-png` | Convert the imported TGA and PNG images to BLP, each one only when it gets smaller. |
| `--dds` | Convert DDS textures to BLP. |
| `--to-dds[=high\|normal\|small]` | Lossy: BLP, TGA and PNG textures to DDS, each one only when it gets smaller. Reforged maps only; not with `--dds` or `--tga-png`. |
| `--lossy` | Only for a map over the game's 512 MiB limit: half-size textures and mono WAV sounds until it fits. |

**Anti-cheat**

| Option | |
|---|---|
| `--anti-cheat[=ledger,codes,names,bj,globals]` | Add the in-game anti-cheat (the first four pieces without a value; `globals` is not proven in game yet). |
| `--anti-cheat-actions=warn,nosave,defeat,end` | What to do when a cheat is found (default `warn`). |
| `--anti-cheat-gold-jump=N` | The gold or lumber jump with no event that counts as a cheat (default 400). |
| `--anti-cheat-codes-mode=auto\|humans\|reload\|humans+reload` | When the cheat code detector arms (default `auto`). |

**Running it**

| Option | |
|---|---|
| `--preset=<file.json>` | Start from the options of a preset; the options you type win over it. |
| `--save-preset=<file.json>` | Write the options given to a preset file. Without a map, that's all it does. |
| `--inspect` | Print what the window would check on that map, then exit. |
| `--recursive` | With a folder: the maps of the subfolders too, keeping the folder tree. |
| `--json` | Print one JSON object with the result, for a script or CI. |
| `--log=<file>` | Write the report to a file. |
| `--check-update` | Print the newest release and exit. |

Exit codes: 0 protected, 1 the protection failed, 2 bad command line, 3 the map or folder was not found, 4 an option
value is not valid, 5 an unexpected error.

## Changes

What each version brought: [CHANGELOG.md](CHANGELOG.md).

## Building

Python 3.14, then `python -m pip install -r requirements.txt`.

- `python DevoProtect.py` runs the window from source; with `<map> <out> [options]` it runs the command line.
- `python build.py` builds the Windows executables. pjass gets bundled if `engine/pjass.exe` exists or `PJASS` points
  to it.
- `python build_linux.py` builds the Linux binary in Docker, compiling pjass from source.
- The site is built by `web/build_site.py`.

## Thanks

[pjass](https://github.com/lep/pjass) by lep checks every JASS script DevoProtect writes, and ships with it. The
licenses of the other third-party pieces are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT, see [LICENSE](LICENSE).
