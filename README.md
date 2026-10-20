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

DevoProtect takes a finished map (`.w3x`, `.w3m`) or campaign (`.w3n`) and writes a protected copy next to it. Your
original file is left alone. It closes the easy ways into a map: opening it in the World Editor, opening it in MPQ
Editor, reading the script.

## Get it

**In the browser:** [protect.devoltz.party](https://protect.devoltz.party). Nothing to install, and the map is
processed inside the page, so it never leaves your computer.

**Windows:**

1. Download `DevoProtect.exe` from [Releases](https://github.com/devoltzz/devoprotect/releases/latest). Get `DevoProtect-cli.exe` too
   if you want the command line.
2. Open `DevoProtect.exe` and open a map.

**Linux** (x86-64, glibc 2.35 or newer: Ubuntu 22.04+, Debian 12+, Fedora 36+, Mint 21+):

1. Download `DevoProtect-linux-x86_64`.
2. `chmod +x DevoProtect-linux-x86_64`
3. Run it. The window uses the system's WebKitGTK: `sudo apt install gir1.2-webkit2-4.1` (Debian, Ubuntu) or
   `sudo dnf install webkit2gtk4.1` (Fedora). Give it a map and an output name and it runs as the command line instead.

The program tells you when a new version is out, and every download is checked against the release's
`SHA256SUMS.txt` before anything is replaced. The window is in English and 16 other languages.

## Use it

Open a map, pick a mode, click **Protect**. To protect many maps with the same options, use **Protect a folder**
(on the site, **Protect several maps**): each map is protected in turn into another folder under the same name, each
with its own key next to it, and a summary at the end says which ones were refused and why.

**Presets.** **Save preset** writes the options on screen to a small JSON file, and **Load preset** reads it back, so
every release goes out with the same set. A preset never stores a file path (the previous key, ffmpeg, the game
folder). The command line reads the same file with `--preset=<file>`.

| Mode | What it does |
|---|---|
| **Full protection** | Every step below. It's what I use for a release. |
| **Script only** | Changes the object IDs and the script, and leaves the archive as a normal MPQ. |
| **Archive only** | Removes the editor files and repacks the archive; the script stays as it is. |
| **Custom** | Each step on its own, plus the extra options. |

What the steps do:

| Step | What it does |
|---|---|
| **Shuffle IDs** | Renames your custom object IDs (`h000`, `A00B`...) to meaningless ones, in the object data and in the script. Optionally non-printable: the last three characters become control characters, which object editors show as garbage. |
| **Obfuscate** | Scrambles the names, strings and raw codes of a JASS or Lua script. Your function and variable names (`Trig_`, `udg_`, `gg_` and the rest) are gone for good in both. JASS output goes through pjass before it's saved. A JASS map can be converted to Lua first; a Lua script also gets its strings encrypted where they are used and the whole file wrapped in loader layers. |
| **Remove editor files** | Strips what only the World Editor uses (triggers, unit placement, editor counters), so the map won't open there as a normal map. Anything the game still reads stays. Optionally the object data becomes the game's own SLK tables. |
| **Decoys and markers** | Fake trigger files that are different in every map, the file list removed so there are no file names to mine, fake imports, a hash table filled with fake files spread across the map's folders so no file can be added later, extract-all bombs, a cut hash table, and malformed-header markers. |
| **Optimize size** | Lossless texture recompression, identical files stored once, DDS textures to BLP. Optionally, all off by default: smaller MDX models (the animation keys that change nothing), MP3 sounds re-encoded in mono (lossy, desktop only, needs ffmpeg), a minified JASS script, imported TGA and PNG images converted to BLP (a palette without loss when the image has 256 colors or fewer, else JPEG at high quality, and only when it gets smaller), and smaller textures (lossy: the textures only models use, at half size). |
| **Anti-cheat** | Off by default; tested in game in single player, multiplayer still to prove. Adds checks that run while the map plays: a ledger that undoes gold, lumber and hero changes no part of the map explains, a detector for the game's own cheat codes in single player, decoy function names so a cheat pack pasted by hand does not compile, and for Lua maps a guard that restores the engine functions a cheat pack replaces. When it finds something it can warn everyone, block the cheater's saves, defeat the cheater or end the game. |
| **Pack** | Repacks the archive with 512-byte sectors. The game loads it fine; MPQ Editor and other StormLib tools refuse to open it. |

Three more options are off by default until they are tested in game. You turn them on in Custom or on the command
line. **Rename imported files** (`--rename-imports`): the name of every imported file the map uses is replaced by a
random name of the same length, in the archive and in every reference, so the original name no longer comes back.
**Encrypt files** (`--encrypt-files`, with the 512-byte sector pack): the files whose names are known are stored
encrypted in the archive, with the key taken from the name. **Remove error messages** (`--remove-error-logs`): the
compiler error messages that vJass (JassHelper) and Wurst leave in the script are removed.

After each step the map is read back and every file is compared with what that step was supposed to write. If
anything else changed, the job stops and nothing is saved.

**The ID key.** Shuffling the IDs writes a key, `<map>_ids.tsv`, next to the output (not inside the map). Keep it.
When you release the next version, give it back as **Previous key** and every object gets the same ID it had before,
so save codes from the old version still load. For a campaign, give it the folder with the keys.

## Questions

**Can someone still get into my map?** Someone who really wants to, yes. The map runs on the player's computer, so it
can always be dumped from memory and rebuilt by hand. DevoProtect closes the easy routes. Keep your unprotected map,
because there is no undo.

**What are the extract-all bombs?** A few decoy files with a huge declared size. A tool that extracts everything in the
map has to write that size out in zeros, so a full extract fills gigabytes of disk. The game never reads them, and the
real files are untouched.

**MPQ Editor opens my protected map read-only.** That's the cut hash table: MPQ Editor and StormLib can list and
extract, but they can't edit, add or delete a file. The game plays the map unchanged. With the 512-byte sector pack
they don't open the map at all.

**Should I convert my JASS map to Lua?** You don't need to for the names: a JASS script and a Lua script both lose your
function and variable names for good. A Lua script also comes wrapped in loader layers, which slows down someone who
opens the file, but anyone who reads DevoProtect's code can undo them, the same as the string encryption. The map then
needs Warcraft III 1.31 or newer. In a Lua script, a name the map looks up from text while it runs (`ExecuteFunc`
with a name built from pieces, `_G[name]`) keeps its name, so the map still finds it. Maps that use natives of KK, YDWE, DzAPI or other
platforms, or that carry their own `Blizzard.j` or `common.j`, are refused with a message that says why. A few things
work differently in the game's Lua and are left as they are (variable events, a null string or handle passed to a
native, `SubString` past the end of the text, the rounding of real math): the log lists the ones your script has, so
test the converted map in game before a release.

**What does converting the object data to SLK do?** The map's units, items and abilities become the game's own tables,
so fewer objects are built when the map loads, which helps with Reforged disconnects on maps with hundreds of
abilities. The map grows, because it carries the game's tables, and it still has to be proven in game, so it's off by
default. It reads the tables of your installed Warcraft III, found automatically on Windows. Without the game (the
site, Linux, or a PC without Warcraft III) it downloads the tables of Warcraft III 3.0.1.24371 from
protect.devoltz.party once, 1.2 MB, checks them and keeps them.

**What does the anti-cheat need from my map?** Nothing, but a map can ask what it found. Declare `function DevoProtect_CheatUsed takes player p returns boolean` and have it return `false`; the protector fills it in, and it returns `true` for a player who was reported, or for everyone when the map itself was modified (in a Lua map it is the global function of the same name). Use it to refuse a save code or hold back a reward. Block saves works on the map's own calls to `PreloadGenEnd`, the native that writes a Preload file.

**Does the anti-cheat stop cheaters?** It stops the easy ones. A cheat that changes the map's own values is undone and reported, a cheat pack pasted by hand is refused by the decoy names, and the game's cheat codes are reported in single player. A player who edits the game's memory with no effect on those values is not seen. The defeat action does nothing against the strengthandhonor code, because that code stops the game from defeating anyone; use the end action for that. I tested it in game in single player (the game's `greedisgood` is undone and reported, normal play reports nothing); multiplayer games, cheat packs and Lua maps are still to be proven in game, so test it on your map before a release.

**How much smaller does Optimize make my map?** It depends on what the map carries. On six test maps, re-encoding
the MP3 sounds made the maps with music 46% to 79% smaller (64 and 32 kbps), and did nothing on the maps without
music. Lossy models round the low bits of the numbers in the MDX files, so the map packs the models 15% to 20% smaller:
on seven test maps that made the whole map 1.4% to 9% smaller, and almost nothing on three more whose models had
already been through a "squisher". The minified script gave less than 0.5% with the script obfuscated; with the obfuscator off it
gave up to 10% on a map with a big script. Mono 22 kHz is a real loss for music, so listen to the map before you
release it, and look at the models in game too. The site can't run ffmpeg, so it leaves the MP3 sounds as they are.
Smaller textures made a 50 MB test map 23% smaller with the 512-byte pack: half of its textures belong to models
only, and each of those dropped its biggest mipmap. Converting TGA and PNG images saves room only in maps that carry
big ones; most maps carry just the preview, which stays a TGA because the game reads it by that name.

**What do smaller textures cost?** The textures that only models use go to half size, the size the game already
shows from a distance, so far away models look the same and close ones look blurrier. Icons, the interface, the
loading screen and the minimap are never touched, and nothing goes below the side you choose (128 pixels by default).
A texture the map uses in a way the protector can't see, like a model that the script shows as part of the
interface, gets blurrier too, so look at the map in game before you release it.

**Is my map sent anywhere?** No. Everything runs on your computer, or inside the page on the site. The program only asks
GitHub whether a new version is out. On the site, very big maps with every option on can run out of the browser's
memory (about 2 GB); use the program for those.

**Does the site give the same map as the program?** The same files inside, yes. The site packs them with the
browser's own zlib, so the map comes out a little bigger and its bytes differ. Turn on "same bytes as the desktop
program" in the final pack's extras to pack with the program's compressors: the map is then byte for byte the same
as on Windows, about 8 times slower on a big map.

## Command line

```
DevoProtect-cli <map.w3x|campaign.w3n> [out.w3x] [options]
DevoProtect-cli <folder> [out folder] [options]
DevoProtect-cli --save-preset=<file.json> [options]
```

A folder: every `.w3x`, `.w3m` and `.w3n` in it (not in its subfolders) is protected into the out folder (default
`<folder>_protected`) under the same name, one at a time, each with its key next to it. A map that fails doesn't stop
the others; the summary at the end says why it was refused, and the exit code is 1. With a folder, `--previous-key`
is the keys folder of the previous release (its out folder).

| Option | |
|---|---|
| `--skip=shuffle,obfuscate,block,decoys,pack,dds` | Steps to skip. |
| `--rename-imports` | Rename the imported files to random names of the same length, everywhere they are used (off by default, not tested in game yet). |
| `--encrypt-files` | Store the files whose names the map gives encrypted, with the key taken from the name (512-byte sector pack only; off by default, not tested in game yet). |
| `--remove-error-logs` | Remove the vJass and Wurst compiler error messages from the script (off by default, not tested in game yet). |
| `--block=w3i,wtg,extra,units,doo,w3r` | Which editor files to remove (default: `w3i,wtg,extra,units,doo`). |
| `--to-slk` | Convert the object data to the game's SLK tables (the installed game's, or a 1.2 MB download once). |
| `--game=<folder>` | The Warcraft III folder, or a tables pack folder, for `--to-slk`. |
| `--decoys=wtg,listfile,imp,preview,fill` | Decoy files (`listfile` removes the file list; `preview` only when you name it: the game may show that image). |
| `--bombs` | Extract-all bombs. |
| `--cut-hash` | Cut the hash table: MPQ Editor and StormLib open the map read-only. |
| `--variant=header,high-sector,bit31` | Malformed-header markers (only with the 512-sector pack; `bit31` doesn't combine with `--bombs` or `--cut-hash`). |
| `--ids-non-ascii` | Non-printable object IDs (control characters). |
| `--to-lua` | Convert a JASS script to Lua before obfuscating it (the map then needs 1.31 or newer). |
| `--lua-layers=N` | Loader layers for an obfuscated Lua script (default 2). |
| `--previous-key=<tsv>` | The ID key of your previous release (a campaign takes the keys folder). |
| `--seed=N` | Shuffle seed (default: taken from the map). |
| `--optimize` | Lossless recompression and dedup (`--no-recompress`, `--no-dedup`, `--no-blp-opt` turn a part off; `--lossy` is only for maps over the game's 512 MiB limit). |
| `--models[=lossless\|lossy]` | With `--optimize`: drop the MDX animation keys that change nothing; `lossy` also thins straight animation tracks and rounds the low bits of the model numbers (the models pack 15% to 20% smaller; off by less than 0.05 units). |
| `--mp3[=32\|48\|64\|96\|128]` | With `--optimize`: re-encode the MP3 sounds in mono, 22 kHz, at that rate (default 64). Lossy; needs ffmpeg on the PATH or `--ffmpeg=<path>`. |
| `--minify` | With `--optimize`: minify the JASS script before the obfuscator (unused functions and globals out, constants written in; with `--skip=obfuscate` the names get shorter too). |
| `--tga-png` | With `--optimize`: convert the imported TGA and PNG images to BLP and update the references (a palette without loss when the image has 256 colors or fewer, else JPEG at high quality, only when it gets smaller). The map preview, images nothing in the map names, images whose names start the way the script builds names while the game runs, sides that aren't a power of two and sides above 512 in a map older than 1.31 stay as they are. |
| `--smaller-textures[=64\|128\|256]` | With `--optimize`: the textures only models use at half size, never below that side (default 128). Lossy; icons, the interface, the loading screen and the minimap stay as they are. |
| `--preset=<file.json>` | Start from the options of a preset; the options you type win over it. |
| `--save-preset=<file.json>` | Write the options given (and the preset's) to a preset file. Without a map, that's all it does. |
| `--dds` | Convert DDS textures to BLP and update the references. |
| `--anti-cheat[=ledger,codes,names,bj]` | Add the in-game anti-cheat (all four pieces without a value). |
| `--anti-cheat-actions=warn,nosave,defeat,end` | What to do when a cheat is found (default: `warn`). |
| `--anti-cheat-gold-jump=N` | The gold or lumber jump with no event that counts as a cheat (default 400). |
| `--anti-cheat-codes-mode=auto\|humans\|reload\|humans+reload` | When the cheat code detector arms (default `auto`). |
| `--blp` | Lossless BLP re-optimization inside the 512-sector pack. |

`--help` shows everything. On Linux the program takes the same options after it:
`./DevoProtect-linux-x86_64 <map> <out> [options]`.

## Changes

What each version brought: [CHANGELOG.md](CHANGELOG.md).

## Building

Python 3.14, then `python -m pip install -r requirements.txt`.

- `python DevoProtect.py` runs the window from source; `python DevoProtect.py <map> <out> [options]` runs the command
  line.
- `python build.py` builds the Windows executables. pjass gets bundled if `engine/pjass.exe` exists or `PJASS` points
  to it.
- `python build_linux.py` builds the Linux binary in Docker, compiling pjass from source.
- The site is built by `web/build_site.py`.

## Thanks

[pjass](https://github.com/lep/pjass) by lep checks every JASS script DevoProtect writes, and ships with it. The
licenses of the other third-party pieces are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

MIT, see [LICENSE](LICENSE).
