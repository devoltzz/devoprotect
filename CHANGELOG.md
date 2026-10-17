# Changelog

What each version of DevoProtect brought, the newest first. The downloads are on the
[Releases](https://github.com/devoltzz/devoprotect/releases) page.

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
