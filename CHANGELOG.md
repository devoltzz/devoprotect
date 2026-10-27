# Changelog

What each version of DevoProtect brought, the newest first. The downloads are on the
[Releases](https://github.com/devoltzz/devoprotect/releases) page.

## 0.1.13 (2026-10-27)

- A new look for the window and the site. The four modes (Full protection, Script only, Archive only, Custom) are now
  the numbered list on the left, with a short line under each, and the page shares its colors, its frame and its
  buttons with the other devoltz.party sites. The top of the left column has a small line to switch between them; in
  the program they open in your browser. The site has its own icon in the browser tab. Every option, its locks and what the protection does are the same as in 0.1.12; the new texts are in all 16
  languages of the page.

## 0.1.12 (2026-10-24)

- Smaller maps by default, with nothing lost. On the 12 maps I measure size with (unprotected maps made by
  mapmakers, straight from the editor), the protected maps come out 15.7% smaller in total than with 0.1.11
  (1,153.7 MB to 972.8 MB), from 0.4% to 45.5% per map; with Convert to Lua, 13.0% smaller on the six that convert.
  Three things do it, all on by default:
  - The files the game never reads are removed. A file stays when the game reads it by its name (the map's own files
    and anything in a folder of the game, which can replace a game file), when a file the game reads names it (the
    script, the object data, a model naming its texture, an interface file), or when the script builds names that
    start the way it does. What goes is usually a pack of models or effects imported whole, of which the map uses a
    few: 140 MB of those 12 maps, up to 42% of one. The report lists every removed file, and "remove the files the
    game never reads" (`--keep-unused` on the command line) keeps them.
  - The BLP textures are rewritten without loss with either final pack, the same pixels checked one by one, now also
    the ones whose mipmaps have gaps between them: 42 MB over the 12 maps. `--no-blp` keeps them as they are.
  - The JASS script loses the code nothing runs (the minify, now on by default), and the obfuscated names are as
    short as they can be, the most used first: the protected script is 13% to 26% smaller.
  The options that lose quality (MP3, lossy models, smaller textures) stay off. I read every protected map back file
  by file against the 0.1.11 one: besides the removed files, only the BLP textures (the same pixels) and the script
  changed, and the job itself checks the same at each step and stops if anything else changes. It is faster where
  a lot goes out (a 65 MB map: 139 s to 84 s) and slower on a very big map that loses little (a 495 MB map: 590 s
  to 730 s).
- Two new MPQ barriers, added at the very end and off by default (Final pack, "MPQ barriers"; `--mpq-barrier=` on the
  command line). The block bitmap writes a few bytes at the end of the file, and MPQ Editor no longer opens the map
  (its v1 mode still opens it read-only). The archive at 128 MiB moves the whole archive 128 MiB into the file, and
  MPQ Editor does not open it even in v1 mode, but the map grows by about 128 MB. I loaded both in Reforged on a map
  without the sector-512 pack. With that pack MPQ Editor already refuses the map, so these matter most with the None
  pack; I have not tested them together with it in the game yet. Single maps only, not campaigns.
- The page locks an option that has nothing to act on in the map you chose, with the reason next to it: rewriting
  BLP textures in a map with no BLP texture, the model options with no MDX model, MP3 with no MP3 sound, DDS, TGA
  and PNG. The command line warns about the same options. The minify is locked with Convert to Lua (the script is
  Lua by then), and the MP3 rate and texture side lists follow their box.
- Picking Full protection or Archive only, or loading a preset, on a map with an encrypted file that has no name
  turned the sector-512 pack back on, which that map can't use; the pack now stays on None for that map.
- Command line: `--no-optimize`, `--keep-unused`, `--no-minify` and `--no-blp` (`--optimize`, `--minify` and
  `--no-blp-opt` still work).
- The anti-cheat could desync a game. In Reforged's Lua, a game object that the script stops holding is freed by the
  garbage collector at a different moment on each computer, and that can desync the game. The anti-cheat's Lua code
  made some objects every two seconds and let them go, and left a few others (its start timer, its triggers) without a
  reference. It now creates everything once and keeps it; the JASS version keeps its filter and timers in globals too.
  I checked it in the simulated game engine with the collector running: nothing of the anti-cheat is created while the
  game runs, and nothing is left to the collector.

- The protector now knows which game a map was made for (1.23 and older, 1.24 to 1.28, 1.29, or Reforged) and checks
  the script with that game's own scripts, and the page shows it in the map card. What does not fit that game is
  locked, with the reason next to it: converting to Lua (it only runs from 1.31 on: save the map in the Reforged
  editor first), the anti-cheat and the JASS obfuscation on a map of 1.23 or older (both need hashtables, which came
  in 1.24), and the obfuscation and minify of a script that carries a memory hack (it reads the game's memory through
  the exact bytes of its own script). The anti-cheat now writes its code for classic games too.

## 0.1.11 (2026-10-23)

- A warning when a classic map ends up too big to play with other people. Warcraft III 1.24 to 1.27a only send a map of
  up to 8 MB to the other players of a game (1.27b and later, up to 128 MB); played alone or against computers, any size
  opens. The decoys and the sector-512 pack make a map bigger, so a 7.9 MB map could come out above 8 MB and nobody
  could join a game with it, with nothing saying so. Now the report says it, with the size of the original map. It only
  shows for maps in the classic format (not for a map converted to Lua or saved by the Reforged editor). I measured the
  limits in the game itself; where the game checks the size comes from the reverse engineering DooMWhite did in Tinker,
  used with permission (credited in the third-party notices).

## 0.1.10 (2026-10-21)

- New in the anti-cheat, for Lua maps: a global watch (off by default, not proven in the game yet). A friend suggested
  it: watch the map's global table for a variable it should not have. When the map script has finished loading, any
  global created by code pasted after it is reported; while the game runs, a global the map's own code never defines
  is reported; and the names of the public cheat packs are reported wherever they show up. It takes the list of the
  map's globals from the script itself when you protect; a map that builds global names at run time has no reliable
  list, so that one check is skipped and the log says why. It keeps its own copies of the functions it uses, so code pasted later
  cannot blind it by replacing them. Command line: `--anti-cheat=ledger,codes,names,bj,globals`.
- About the other half of that suggestion, counting a script's local variables: the Lua of Warcraft III has no
  `debug` library and cannot read its own text (I tested it in game), so a map cannot count locals or read a cheat
  pack's code while it runs. What a pack leaves where the map can see it is the globals it creates (the new watch),
  the engine functions it replaces (the Lua guard) and the values it changes (the ledger). Reading a pack's code
  directly stays a job for the protector, before the map ships: that is what the decoy names do on JASS maps.
- Remove editor-only files, objects as SLK tables:
  - an object whose ID differs from another only in letter case stays in the object files. The game finds a table row
    and a profile section without looking at case, so the two became one row. The common case is the editor's first
    custom unit `h000`, which the game data already uses as `H000`;
  - the internal name of a unit (what `UnitId2String` returns, used by `GroupEnumUnitsOfType` and by train orders) is
    no longer replaced with the unit's display name. A changed unit keeps the game's internal name and a new one gets
    `custom_` and its ID, as without the conversion;
  - a list with one model per weapon (`Missileart`) was written in quotes, which made it one value: the first weapon
    got both paths and the second none. It is written as the game writes it now.
  These came out of comparing the converter with a set of SLK fixes a friend made on top of W3x2lni Reforged.
- The JASS check uses the `common.j` and `blizzard.j` of the current patch (3.0.1.24371): a map that calls one of its
  4 new natives or uses one of its 110 new ability fields no longer fails the check.

## 0.1.9.2 (2026-10-20)

- A new layout for the program and the site. Every option is on the left in groups that follow the steps: object IDs,
  script, editor files, size, the final pack, decoys, the anti-cheat and an advanced group. A ready mode keeps the
  groups closed; Custom opens them, and changing any option turns the mode into Custom. On the right, the map is
  checked as soon as you choose it (JASS or Lua, campaign or single map, game version, size) and the steps that will
  run are listed in order.
- Options that don't fit together, or don't fit the map, are locked before you start, with the reason next to them:
  the markers and the file encryption without the 512-byte pack, Convert to Lua on a Lua map or on a map that carries
  its own Blizzard.j, the bombs and the hash table cut on a campaign, the cut when the last entry of the map's hash
  table holds a file, the JASS-only and Lua-only pieces of the anti-cheat, and the 512-byte pack on a map with an
  encrypted file that has no name. A map that can't be protected at all says why, and the Protect button stays off.
  What you had chosen comes back when the lock goes away, and the list on the right says what was turned off.
- The three options that came in 0.1.9 (rename imported files, encrypt files, remove the vJass and Wurst error
  messages) were tested in game and lose the "not proven" note. They stay off by default.
- New on the page: the loader layers of a Lua script, removing the regions file (`war3map.w3r`), the decoy preview
  image and the shuffle seed. Before, they were only on the command line. The DDS to BLP option moved to the size
  group and the malformed-MPQ markers to the final pack, where they belong.
- The "block table bit31" variant can't be used together with the extract-all bombs or the hash table cut: both
  rewrite the tables after the pack and the mark is lost. Before, the page let you turn all of them on and the run
  stopped only at the very end, after minutes of work. Now the checkbox is locked off while the bombs or the cut are
  on, and the program and the command line refuse the combination before they start.
- The log of the program and the site names the imported files step and the error messages step, like the others.

## 0.1.9.1 (2026-10-20)

- Shuffle IDs now also changes the object IDs that a Lua script writes as plain numbers. WCSharp (C# to Lua) writes
  them that way, so a WCSharp map protected with Shuffle IDs on no longer found its own units: the War of Races map
  that was reported stayed on its race selection screen. Before, only `FourCC('h000')` was changed in a Lua script.
  An ID used in math keeps its value, as with `FourCC`, and the check after the step now counts these numbers too, so
  a number left with an old ID stops the protection instead of giving you a broken map.
- A Lua script that was already obfuscated with names made of I, l and 1 can be protected again. Before, the run
  stopped with "pop from empty list".

## 0.1.9 (2026-10-20)

- Three new options, off by default until they are tested in game. Turn them on in Custom or on the command line.
  - Rename imported files (`--rename-imports`): the name of every imported file the map uses is replaced by a random
    name of the same length, in the archive and in every reference (object data, models, profiles and the script).
    The original name no longer comes back, even with no file list in the map. Models and portraits, disabled icons
    and numbered variations keep their relation.
  - Encrypt files (`--encrypt-files`, with the 512-byte sector pack): the files of the map whose names are known are
    stored encrypted in the archive. The key comes from the name, the one the game already has when it asks for a
    file; a tool without the name cannot read the content. The report says how many blocks were encrypted, and a
    block with another name pointing at it stays as it is.
  - Remove error messages (`--remove-error-logs`): the compiler error messages that vJass (JassHelper) and Wurst leave
    in the map script are removed. They are diagnostics, and they carry the names of structs, packages and source
    lines that the obfuscator cannot rename inside a string. Your own messages stay.
- Optimize: "models, lossy" (`--models=lossy`) now also rounds the low bits of the numbers in the MDX models. It's the
  idea of the old MDX Squisher, but class by class and with a limit: a vertex moves less than 0.05 units and less than
  1/2000 of the model's size, a rotation less than 0.002 radians. The files keep their size, but the map packs the
  models 15% to 20% smaller. On seven test maps the whole map got 1.4% to 9% smaller; three more gained almost nothing,
  because their models had already been squished. Every model is read back and checked; one that goes past a limit keeps that part as it was. Still off
  by default, and still to be looked at in game.
- The site has a new option in the final pack's extras, "same bytes as the desktop program", off by default. With it
  on, the 512-byte pack runs the same compressors as the program (zopfli and zlib-ng, as WebAssembly), and the
  protected map comes out byte for byte the same as on Windows. It is slower: about 8 times on a big map (164 seconds
  instead of 20 on an 11 MB test map). Off, the site works as before: the same files inside the map, packed a little
  bigger and with other bytes.
- The Windows and Linux programs now carry the native code for the MPQ and the texture rewrite, and pack the 512-byte
  sectors on every core instead of one. On the test maps the program got 3 to 7 times faster, with the same output.
- JASS to Lua: a unary plus (`+5`, `+x`) is now dropped, since Lua has none. Before, it came out as a minus, so
  `+5` became -5. None of the test maps here use it, but a map that does got wrong numbers.
- JASS to Lua: `==` between reals keeps the JASS tolerance of 0.001 (`0.0 == 0.0009` is true in JASS), and `!=`
  stays exact, as in JASS. Before, `==` was exact in Lua.
- JASS to Lua: `null` compared with an integer, real or boolean, or stored into one, counts as that type's zero
  (`0`, `0.0`, `false`), as in JASS. Before, `i == null` was always false in Lua.
- JASS to Lua: `debug` statements no longer run, as in the game's JASS. Before, they ran every time. They become
  `if _DEBUG then ... end`, which is what Blizzard's own converter writes.
- JASS to Lua: the log warns about what only the game can settle, which the conversion leaves as it is: variable
  events (`TriggerRegisterVariableEvent`), a null string or handle passed to a native, `SubString` past the end of
  the text, and `R2I` of real math. An in-game test of each one comes next.
- The 0.1.1 note about waits inside callbacks was wrong about JASS: the wait ends the thread there, it isn't
  skipped. The warning stays.
- A map already protected by another tool that encrypts its files is now protected when the map gives the names of
  those files: each one is decrypted with the key from its name, checked the same way as the MPQ's own files. A map
  with an encrypted file that has no name anywhere in the map is refused at the start, with the same message.
  Before, both were refused only after the other steps had run (19 seconds on one test map).
- `--cut-hash` together with `--decoys=fill` works now. Before, the run stopped at the end with "the cut would eat
  a real file", because the fill took the last entry of the hash table, the one the cut removes.
- `--bombs` together with `--decoys=fill` finishes in seconds. Before, it ran for more than 10 minutes on a small
  map: the hash table filled by the decoys grew 8192 times with no free entry left, and every new name walked the
  whole table. The fill now runs after the bombs, and the writer finds a slot in such a table without walking it.
- A map file that doesn't exist, is empty, is locked by another program or isn't a map at all now says so. Before,
  all of these said the MPQ header was not a normal MPQ v1 header.
- JASS to Lua: a map whose `war3map.w3i` ends early now converts. Some optimizers, and DevoProtect's own editor
  lock, write a single 0xFF where the last four lists go, and one test map was one byte short. The game reads those
  files; the converter refused them.
- Fake triggers (`--decoys=wtg`) are now different in every map: how many triggers, their names, the variable
  names, the chat commands, the numbers and the texts all come from the map's seed. Before, every protected map
  carried the same pair of files, which a simple hash check could spot. The same seed still gives the same files.
- "Convert object data to SLK tables" (`--to-slk`) now works without Warcraft III installed, and the site offers it.
  Without the game, the program and the site download the game's tables once (the tables of Warcraft III 3.0.1.24371,
  1.2 MB), check them and keep them; on Linux `--game` is no longer needed. With the game installed, its own tables
  are used, as before. The report says which tables were used and their version. With the tables of the same version,
  the protected map is the same byte for byte either way.
- Optimize: imported TGA and PNG images can be converted to BLP (`--tga-png`, off by default), with every reference
  updated, as the DDS conversion does. Each image becomes the BLP that takes less room in the map: a palette without
  loss when it has 256 colors or fewer, else JPEG at high quality (39 dB on average on the images measured; the
  game's own table gives 21 to 42). The choice follows the pack: with the 512-byte pack the palette wins far more
  often. Images that stay as they are: the map preview (the game reads it by name), images no file of the map names,
  images whose names start the way the script builds names while the game runs (`"[UI]_Select_" + I2S(n) + ".tga"`
  keeps only the images starting with `[UI]_Select_`; a name built from a variable keeps every image of that type),
  sides that aren't a power of two, and sides above 512 in a map made before 1.31. On the test maps the converted
  images take 22% to 62% less room, but the whole map gains little: most maps here carry only the preview, and in the
  maps with many images most of them stay for one of these reasons.
- Optimize: smaller textures (`--smaller-textures`, off by default, lossy). The textures only models use go to half
  size, never below 128 pixels (64 and 256 can be chosen). A texture that has its mipmaps just drops its biggest level
  and keeps the others byte for byte, so nothing is encoded again. Icons, the interface, the loading screen and the
  minimap stay as they are. On a 50 MB test map the protected map got 23% smaller. Models look the same from afar and
  blurrier up close, so look at the map in game before a release.
- Presets: **Save preset** writes the options on screen to a JSON file and **Load preset** reads it back, in the
  program and on the site. The command line reads the same file with `--preset=<file>` (the options you type win over
  it) and writes one with `--save-preset=<file>`, with or without a map. A preset never stores a file path.
- A whole folder at once: **Protect a folder** in the program, `DevoProtect-cli <folder> [out folder]` on the command
  line, **Protect several maps** on the site. Each map is protected in turn into the out folder under the same name,
  each with its own key next to it; a map that fails doesn't stop the others, and the summary says why it was refused.
  With a folder, the previous key is the keys folder of the previous release.
- The program now opens the command line for every option of the command line. Before, `<map> --anti-cheat` (and a
  few other options) with a single map opened the window instead.

## 0.1.8 (2026-10-19)

- JASS scripts saved with a bare CR at the end of each line (some old tools write them that way) are obfuscated now.
  Before, the run stopped with "expected a globals block and the main function".
- Big Lua scripts need less memory: a 17.9 MB `war3map.lua` went from about 2.1 GB to 1.5 GB at its peak, which
  leaves more room under the website's memory limit. The protected map is the same.
- Two protections running at the same time on Windows no longer fail when they write the same piece of the shared
  cache.
- The anti-cheat has been tested in game, so the window no longer says it's unproven. It's still off by default.
- The MP3 option mentions ffmpeg once instead of twice.

## 0.1.7 (2026-10-19)

- The file list decoy (`listfile`) now removes the map's file list instead of writing a fake one. Any list left in
  the map is something a tool can mine for file names, so now there is none.
- The decoys that fill the hash table are spread across the map's folders (the root, `war3mapImported`, `Import` and
  the usual subfolders), each with a file type that fits its folder, instead of all sitting in `Import`.
- The extract-all bombs no longer come with a big file list. A tool that extracts everything walks the archive's
  block table and finds them anyway.
- A Lua script now loses the map's own global names too: the trigger functions (`Trig_`, `InitTrig_`), the variables
  (`udg_`, `gg_`) and every function the author wrote. Before, only the local names changed, so a Lua map, or a JASS
  map converted with "convert to Lua", kept them readable once the loader layers were peeled off. The engine's names
  stay, and so does a name the map looks up from text while it runs (`ExecuteFunc` with a name built from pieces,
  `_G[name]`); `ExecuteFunc("Name")` and the variable event follow the new name. This change is still to be proven
  in game, so test your map before a release.
- Optimize size has three new parts, all off by default. Shrink models drops the animation keys of MDX models that
  change nothing (lossless), or also thins straight animation tracks (lossy). Re-encode MP3 turns the map's MP3 sounds
  into mono 22 kHz files at the rate you pick; on test maps that carry music the map came out 46% to 79% smaller, but
  the sound loses quality, so listen before a release. It needs ffmpeg (on the PATH, or `--ffmpeg=`) and the site
  can't run it. Minify script takes out the JASS functions nothing calls and the globals nothing reads, and writes
  constants where they are used, before the obfuscator runs; with the obfuscator off it also shortens the names. In
  the command line: `--models[=lossless|lossy]`, `--mp3[=kbps]` and `--minify`, with `--optimize`.

## 0.1.6 (2026-10-18)

- The anti-cheat's script templates and the code that reads them now use English names only. The checks and what
  they do are the same as in 0.1.5; a protected map comes out with different scrambled names, nothing else.

## 0.1.5 (2026-10-18)

- In-game anti-cheat, off by default. In Custom there is a new card, and in the command line it is `--anti-cheat`.
  It adds a ledger that undoes gold, lumber and hero changes no part of the map explains, a detector for the game's
  cheat codes in single player, decoy function names so a cheat pack pasted by hand stops the map from loading, and
  for Lua maps a guard against the packs that replace engine functions. When it finds a cheat it can warn everyone,
  block the cheater's saves, defeat the cheater or end the game. A map can ask what it found by declaring
  `DevoProtect_CheatUsed`.
- I tested it in game in single player: `greedisgood` is undone and reported once, normal play (harvesting, killing
  creeps) reports nothing, and the end action closes the game. Multiplayer games, cheat packs and Lua maps are still
  to be proven in game, so it stays off by default. Test it on your map before a release.
- Maps that already carry a pasted cheat pack can be protected now. Two of its function names that differ only in
  letter case used to stop the JASS step.

## 0.1.4 (2026-10-18)

- Convert object data to SLK tables. In Custom, under "Remove editor-only files", you can turn the map's units, items
  and abilities into the game's own tables (`Units\*.slk` and the profile `.txt` files), the way W3Optimizer and
  w3x2lni do. Fewer objects are built when the map loads, which helps with Reforged disconnects on maps with hundreds
  of abilities, and the World Editor no longer shows the custom objects. In the command line it is `--to-slk`. The map
  grows (it carries the game's tables), and the conversion is still to be proven in game, so it is off by default.
- It needs Warcraft III installed to read the game's tables. On Windows the game is found automatically; on Linux pass
  `--game=<folder>`. In the browser the option is turned off, because the page cannot read your game.

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
  for example inside a group loop or a timer, the map is still converted but the log lists those functions. In JASS
  the wait ends the thread there, and in Lua the callback can't pause, so the wait raises an error. Either way the
  code after the wait doesn't run, so they're worth a look. (Corrected on 2026-10-19: this note used to say JASS
  skips the wait.)
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
