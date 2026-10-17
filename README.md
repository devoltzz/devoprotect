# DevoProtect

A map protector for Warcraft III. It takes a finished map (`.w3x`, `.w3m`) or campaign (`.w3n`) and writes a
protected copy next to it. Your original file is left alone.

Get it from [Releases](https://github.com/devoltzz/devoprotect/releases/latest), or use it in the browser at
[protect.devoltz.party](https://protect.devoltz.party). The browser version processes the map inside the page, so
nothing gets uploaded.

## What it does

- Renames your custom object IDs (`h000`, `A00B`...) to meaningless ones, in the object data and in the script.
- Obfuscates the JASS or Lua script. JASS output goes through pjass before it's saved.
- Strips the files only the World Editor uses (triggers, unit placement, editor counters), so the map won't open there
  as a normal map. Anything the game still reads stays.
- Repacks the archive with 512-byte sectors. The game loads it fine; MPQ Editor and other StormLib tools won't open it.
- Optionally: lossless texture recompression, DDS to BLP, decoy files and malformed-header markers.

After each step the map is read back and compared with what that step was supposed to write. If anything else
changed, it stops and doesn't save the output.

About the limits: this won't stop someone who really wants your map. It runs on the player's PC, so it can always be
dumped from memory and rebuilt by hand. What it does is close the easy routes (World Editor, MPQ tools, reading the
script). Keep your unprotected map, because there is no undo.

## Using it

Open a map, pick a mode, click **Protect**.

- **Full protection** does everything above. It's what I use for a release.
- **Script only** changes the IDs and the script and leaves the archive as a normal MPQ.
- **Archive only** removes the editor files and repacks with 512-byte sectors; the script stays as it is.
- **Custom** lets you pick each step.

### The ID key

Shuffling the IDs writes a key, `<map>_ids.tsv`, next to the output (not inside the map). Keep it. When you release
the next version, give it back as **Previous key** and every object gets the same ID it had before, so save codes
from the old version still load. For a campaign, give it the folder with the keys.

### Extra options (Custom mode)

Under Shuffle > Advanced, **non-printable IDs** keeps the first letter of each new ID and makes the other three
characters control characters, which object editors and text tools show as garbage. The script gets them as plain
numbers.

Under Obfuscate > Advanced, **convert a JASS script to Lua first** turns the map's JASS script into Lua before it
is obfuscated, so it gets the Lua protection: encrypted strings behind loader layers. The map then needs Warcraft III
1.31 or newer.

The **Decoys and markers** card adds fake trigger files, a lying file list, decoy imports, or fills the hash table so
no file can be added to the map later. It also has the malformed-header markers for the 512-sector archive.

## Linux

x86-64 with glibc 2.35 or newer (Ubuntu 22.04+, Debian 12+, Fedora 36+, Mint 21+). Download
`DevoProtect-linux-x86_64`, `chmod +x` it and run it. The window needs WebKitGTK:

```
sudo apt install gir1.2-webkit2-4.1    # Debian, Ubuntu
sudo dnf install webkit2gtk4.1         # Fedora
```

Give it a map and an output name and it runs as the command line instead. On Windows the command line is
`DevoProtect-cli.exe`. The window checks for a new version when it opens, and when you update it, it also replaces
`DevoProtect-cli.exe` if that sits in the same folder. Every download is checked against the release's SHA256SUMS.txt.

## Command line

```
DevoProtect-cli <map.w3x|campaign.w3n> [out.w3x] [options]
```

| Option | |
|---|---|
| `--skip=shuffle,obfuscate,block,decoys,pack,dds` | Steps to skip. |
| `--block=w3i,wtg,extra,units,doo,w3r` | Which editor files to remove (default: `w3i,wtg,extra,units,doo`). |
| `--optimize` | Lossless recompression and dedup (`--no-recompress`, `--no-dedup`, `--no-blp-opt` turn a part off; `--lossy` is only for maps over the game's 512 MiB limit). |
| `--dds` | Convert DDS textures to BLP and update the references. |
| `--blp` | Lossless BLP re-optimization inside the 512-sector pack. |
| `--previous-key=<tsv>` | The ID key of your previous release (a campaign takes the keys folder). |
| `--seed=N` | Shuffle seed (default: taken from the map). |
| `--lua-layers=N` | Loader layers for an obfuscated Lua script (default 2). |
| `--decoys=wtg,listfile,imp,preview,fill` | Decoy files (`preview` only when you name it: the game may show that image). |
| `--variant=header,high-sector,bit31` | Malformed-header markers (only with the 512-sector pack). |
| `--ids-non-ascii` | Non-printable object IDs (control characters). |
| `--to-lua` | Convert a JASS script to Lua before obfuscating it (the map then needs 1.31 or newer). |

`--help` shows everything.

## Building

Python 3.14, then `python -m pip install -r requirements.txt`.

- `python DevoProtect.py` runs the window from source; `python DevoProtect.py <map> <out> [options]` runs the command
  line.
- `python build.py` builds the Windows executables. pjass gets bundled if `engine/pjass.exe` exists or `PJASS` points
  to it.
- `python build_linux.py` builds the Linux binary in Docker, compiling pjass from source.

## License

MIT. Third-party licenses are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Found a bug or a map that breaks? [Open an issue](https://github.com/devoltzz/devoprotect/issues/new).
