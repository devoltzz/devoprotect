# Changelog

What each version of DevoProtect brought, the newest first. The downloads are on the
[Releases](https://github.com/devoltzz/devoprotect/releases) page.

## 0.1.3 (2026-10-17)

Two new layers against the tools that unpack maps, both in the command line and in Custom under "Decoys and markers".

- Extract-all bombs: a few decoy files are written with a huge declared size. A tool that extracts everything in the
  map has to write that size out in zeros, so a full extract balloons to gigabytes on disk, while the real files and
  the game are untouched (the game never reads the decoys). In the CLI it is `--bombs`.
- Cut the hash table: the map's file index is trimmed so MPQ Editor and other StormLib tools open it read-only. They
  can still list and extract, but they cannot edit, add or delete a file. The game plays the map unchanged. In the CLI
  it is `--cut-hash`. Proven in game on Lost Temple.
- Neither combines with the "block table bit31" variant (the repack that places those layers would move the tables and
  lose the mark); the run stops and says so.

## 0.1.2 (2026-10-17)

- Big maps no longer break the site. To check each step, DevoProtect kept a full copy of the map's files after every
  step, and on a large map with many options on, the browser ran out of memory during the final pack ("RangeError:
  invalid or out-of-range index"). Now only the last two steps are kept in full and the older ones as a checksum per
  file, so the check is the same and the memory use is much lower: a 157 MB map with everything on went from 2.2 GB
  to 1.7 GB. The Windows and Linux programs use less memory too.
- The site still has a limit of about 2 GB of memory. For very large maps with every option on, use the program.

## 0.1.1 (2026-10-17)

Fixes after a review of the JASS to Lua option and of the updater.

- JASS to Lua now refuses two kinds of map it can't convert: a script that declares natives the game doesn't have
  (the ones from KK, YDWE, DzAPI and other platforms), and a map that carries its own `Blizzard.j` or `common.j`.
  The job stops with a message that says why, instead of giving you a map that won't load.
- If a function with a wait (`TriggerSleepAction`, `PolledWait`) runs as a callback outside the trigger's own thread,
  for example inside a group loop or a timer, the map is still converted but the log lists those functions. JASS
  skips the wait there, Lua can stop the function with an error, so they're worth a look.
- A map whose archive header isn't MPQ version 1 is refused at the start, with a clear message. Before, it failed
  halfway through.
- Updates are checked: every download has to match the release's `SHA256SUMS.txt` before anything is replaced. The
  window now also updates `DevoProtect-cli.exe` when it sits in the same folder, and if an update fails, the program
  you have stays as it was.
- The progress list shows the JASS to Lua step, in all the page's languages.

## 0.1.0 (2026-10-17)

First public release.

- Four modes (Full protection, Script only, Archive only, Custom). In Custom every step can be turned on or off:
  shuffle object IDs, obfuscate the script (JASS or Lua), remove editor-only files, optimize size, and the final pack
  (512-byte sectors, or none). The command line has the same options.
- Previous key: give it the ID key of your last release and every object keeps its ID, so save codes keep working
  between versions.
- Campaigns (`.w3n`) are protected map by map, plus the campaign archive itself.
- After each step every file is read back and compared with what the step should have written. If anything else
  changed, the job stops.
- Optimize size: lossless texture rewrite, identical files stored once, DDS textures to BLP. Without the final pack
  this gives the smallest archive.
- Decoy files (fake triggers, a lying file list, fake imports, a hash table filled to the limit) and malformed-header
  markers for the 512-sector archive.
- JASS to Lua: a JASS map can be converted to Lua before it's obfuscated (Custom > Obfuscate > Advanced, or
  `--to-lua`). The map then needs Warcraft III 1.31 or newer.
- Non-printable IDs: the shuffle can give objects IDs whose last three characters are control characters. The JASS
  script gets them as numbers, so pjass still checks it.
- Runs on Windows, Linux and in the browser ([protect.devoltz.party](https://protect.devoltz.party)).
