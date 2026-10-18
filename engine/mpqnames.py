# Recovers file names from their hashes and from what the map itself mentions.

WARCRAFT_EXTS = frozenset(e.encode() for e in (
    'mdx mdl blp tga dds jpg jpeg png gif bmp psd ico tif tiff webp '
    'wav mp3 flac ogg mid midi dls aif aiff avi ttf otf fnt woff '
    'j ai lua txt slk fdf toc pld wts wai ini html htm xml json csv js css md cfg log lst '
    'w3a w3b w3c w3d w3e w3f w3g w3h w3i w3l w3m w3n w3o w3q w3r w3s w3t w3u w3x w3z w3grp '
    'wct wtg wpm doo mmp shd imp mpq frag vert material mrf ifl flt m3d '
    'exe dll asi mix bin dat db jc key sign gid ccd ax b00 bak cmd clh exp jx lnk pkg was xlsx 3ds xxx iniconfig '
    'manifest zip rar 7z').split())
EXT_EQUIV = [
    ('.w3m', '.w3x', '.mpq', '.pud'),
    ('.txt', '.ini'),
    ('.j', '.lua'),
    ('.wav', '.mp3', '.ogg', '.flac', '.aif', '.aiff'),
    ('.mdl', '.mdx'),
    ('.blp', '.tga', '.jpg', '.dds', '.gif', '.png'),
    ('.ttf', '.otf', '.woff'),
]
_EXT_EQUIV_OF = {}
for _g in EXT_EQUIV:
    for _e in _g:
        _EXT_EQUIV_OF.setdefault(_e, tuple(x for _g2 in EXT_EQUIV if _e in _g2 for x in _g2 if x != _e))


BASE_NAMES = (
    'war3map.j', 'war3map.lua', 'war3map.w3i', 'war3map.wts', 'war3map.wtg',
    'war3map.wct', 'war3map.w3e', 'war3map.w3a', 'war3map.w3b', 'war3map.w3d',
    'war3map.w3h', 'war3map.w3q', 'war3map.w3t', 'war3map.w3u', 'war3map.w3c',
    'war3map.w3s', 'war3map.w3r', 'war3map.wpm', 'war3map.doo', 'war3map.shd',
    'war3map.mmp', 'war3map.imp', 'war3mapMisc.txt', 'war3mapSkin.txt',
    'war3mapExtra.txt', 'war3MapUnits.doo', 'war3mapMap.blp', 'war3mapPreview.tga',
    'war3mapSkin.w3u', 'war3mapSkin.w3t', 'war3mapSkin.w3a', 'war3mapSkin.w3b', 'war3mapSkin.w3d', 'war3mapSkin.w3h',
    'war3mapSkin.w3q',
    'conversation.json', 'war3map.w3l', 'war3mapPostProcessing.txt', 'war3map.w3grp', 'war3map.soundasset',
)
