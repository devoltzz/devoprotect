# Writes decoy files into a map: fake triggers, a lying file list, fake imports.
import hashlib
import os
import random
import shutil
import struct
import time
import zlib



DECOY_KINDS = (
    ('gold', {'gui': True, 'vars': ()}),
    ('lumber', {'gui': True, 'vars': ()}),
    ('level', {'gui': True, 'vars': ()}),
    ('method', {'gui': True, 'vars': (('V1', 'integer', False),)}),
    ('rate', {'gui': True, 'vars': (('V1', 'integer', False), ('V2', 'real', False))}),
    ('save', {'gui': False, 'vars': (('V1', 'string', True),)}),
    ('load', {'gui': True, 'vars': (('V1', 'integer', False),)}),
)
_KIND = dict(DECOY_KINDS)
def _markers(k):
    return {
        'T': 'QT%02d' % k,
        'V1': 'QV%02d' % (2 * k - 1),
        'V2': 'QV%02d' % (2 * k),
        'C': 'QC%02d' % k,
        'X': DECOY_KINDS[k - 1][1]['gui'],
        'N1': str(97000 + 10 * k + 1),
        'N2': str(97000 + 10 * k + 2),
        'R1': '%d.25' % (9700 + k),
        'S1': 'QS%02d' % k,
        'S2': 'QR%02d' % k,
        'L1': 'QL%02d' % (3 * k - 2),
        'L2': 'QL%02d' % (3 * k - 1),
        'L3': 'QL%02d' % (3 * k),
    }


_PREFIXES = tuple(
    'Admin Host Dev Debug Test Cheat Bonus Gm Owner Vip Mod Secret Hidden Quick Auto Extra Super Free Fast '
    'Player Red Main Old New'.split()
)
_TRIGGER_WORDS = {
    'gold': tuple('Gold Money Cash Coins Income Bank Rich'.split()),
    'lumber': tuple('Lumber Wood Trees Logs Resources Mats'.split()),
    'level': tuple('Level Lvl Xp Exp LevelUp Rank Hero'.split()),
    'method': tuple('Mode Access Rights Power Status Toggle Unlock'.split()),
    'rate': tuple('Rate Speed Boost Multiplier Bonus Factor Scale'.split()),
    'save': tuple('Save SaveCode Backup Store Record Export Saver'.split()),
    'load': tuple('Load LoadCode Restore Import Loader Code Reload'.split()),
}
_CHAT_COMMANDS = {
    'gold': tuple('gold g money cash give gg addgold coin m'.split()),
    'lumber': tuple('wood lumber lw addwood tree w l'.split()),
    'level': tuple('lvl level lv xp exp up lvlup'.split()),
    'method': tuple('admin gm host dev debug god test owner cheat'.split()),
    'rate': tuple('rate speed xprate fast boost mult x2'.split()),
    'save': tuple('save sv code backup store s'.split()),
    'load': tuple('load ld restore import lc loadcode'.split()),
}
_MESSAGES = {
    'method': tuple('Admin mode on|Debug enabled|Host commands unlocked|GM mode activated|Test mode: ON|Developer mode|'
                    'Owner access granted|Cheats enabled|Commands unlocked'.split('|')),
    'rate': tuple('Rate changed|Speed set|Experience rate updated|Boost applied|Rate is now active|Multiplier set|'
                  'New rate saved'.split('|')),
    'save': tuple('Save slot |Your code |Code for slot |Saved to slot |Backup |Slot |Save code '.split('|')),
    'load': tuple('Loaded level |Code accepted: |Restored: |Welcome back, level |Load ok: |Level '.split('|')),
}
_VARIABLE_NAMES = {
    ('method', 'V1'): tuple('AdminLevel GmLevel HostRank AccessLevel DebugMode CheatLevel PowerLevel'.split()),
    ('rate', 'V1'): tuple('RateLevel BoostLevel SpeedTier RateTier BonusTier'.split()),
    ('rate', 'V2'): tuple('Rate XpRate GoldRate SpeedRate Multiplier BoostFactor'.split()),
    ('save', 'V1'): tuple('SaveCodes Codes PlayerCode SavedCode CodeSlot Backups'.split()),
    ('load', 'V1'): tuple('LoadedLevel LoadValue CodeValue LoadedCode Restored'.split()),
}
_LOCAL_NAMES = (('L1', tuple('txt s str input msg raw chat cmd line data'.split())),
                ('L2', tuple('acc out buf res sum tmp part got'.split())),
                ('L3', tuple('i j k n idx pos c x'.split())))
_CATEGORY_NAMES = tuple(
    'Commands|Chat Commands|Admin|Cheats|Debug|Systems|Save Load|Testing|Host Commands|Misc|Gameplay|'
    'Utility|Dev|Tools|Init|Player Commands'.split('|')
)
_HELPER_NAMES = tuple('Msg Clamp Chance Tell Roll Notify Limit'.split())
_HELPERS = (
    'function {F} takes player p, string s returns nothing\n    call DisplayTextToPlayer( p, 0, 0, s )\nendfunction\n',
    'function {F} takes integer v, integer lo, integer hi returns integer\n    if v < lo then\n        return lo\n'
    '    endif\n    if v > hi then\n        return hi\n    endif\n    return v\nendfunction\n',
    'function {F} takes integer pct returns boolean\n    return GetRandomInt( 1, 100 ) <= pct\nendfunction\n',
)


def _name(rng, words, in_use, prefix=0.6):
    while True:
        fname = (rng.choice(_PREFIXES) if rng.random() < prefix else '') + rng.choice(words)
        if rng.random() < 0.3:
            fname += str(rng.randint(2, 9))
        if fname.lower() not in in_use:
            in_use.add(fname.lower())
            return fname


def _pick_number(rng, type_name, field_id, statement):
    if type_name in ('gold', 'lumber'):
        return str(rng.choice((rng.randint(5, 999) * rng.choice((10, 100)), rng.choice((99999, 50000, 25000, 10000)))))
    if type_name == 'level':
        return str(rng.randint(1, 10))
    if type_name == 'method':
        return str(rng.randint(1, 9))
    if type_name == 'rate':
        return str(rng.randint(0, 5))
    if type_name == 'save':
        return str(rng.randint(3, 12))
    if field_id == 'N1':
        return str(len(statement) + 1)
    return str(rng.choice((2, 7, 10, 16, 31, 36)))


def decoy_plan(rng):
    types = [t for t, _s in DECOY_KINDS]
    n = rng.randint(4, 9)
    picked_kinds = [rng.choice([t for t in types if _KIND[t]['gui']]) for _ in range(2)] + \
        [rng.choice([t for t in types if not _KIND[t]['gui']])] + [rng.choice(types) for _ in range(n - 3)]
    rng.shuffle(picked_kinds)
    in_use, statements, trigger_list = set(), set(), []
    for type_name in picked_kinds:
        v = {'T': _name(rng, _TRIGGER_WORDS[type_name], in_use)}
        while True:
            c = '-' + rng.choice(_CHAT_COMMANDS[type_name]) + (str(rng.randint(1, 9)) if rng.random() < 0.2 else '')
            if c not in statements:
                statements.add(c)
                v['C'] = c
                break
        v['X'] = rng.random() < 0.5 if _KIND[type_name]['gui'] else False
        for field_id, _t, _a in _KIND[type_name]['vars']:
            v[field_id] = _name(rng, _VARIABLE_NAMES[(type_name, field_id)], in_use, prefix=0.3)
        v['N1'] = _pick_number(rng, type_name, 'N1', v['C'])
        v['N2'] = _pick_number(rng, type_name, 'N2', v['C'])
        v['R1'] = rng.choice(
            ('1.50', '2.00', '2.50', '3.00', '5.00', '10.00', '%d.%02d' % (rng.randint(1, 9), rng.randint(1, 99)))
        )
        v['S1'] = rng.choice(_MESSAGES.get(type_name, ('',)))
        v['S2'] = rng.choice((': ', ' - ', ' = ', ' > ', ' | ', ' :: ', ' -> '))
        local_vars = set()
        for field_id, options in _LOCAL_NAMES:
            v[field_id] = _name(rng, options, local_vars, prefix=0)
        trigger_list.append((type_name, v))
    cats = rng.sample(_CATEGORY_NAMES, rng.choice((1, 1, 2)))
    within = [0 if len(cats) == 1 or k < len(trigger_list) // 2 else 1 for k in range(len(trigger_list))]
    aux = ''
    if rng.random() < 0.6:
        aux = rng.choice(_HELPERS).replace('{F}', _name(rng, _HELPER_NAMES, in_use, prefix=0.8))
    return {'trigger_list': trigger_list, 'categories': cats, 'within': within, 'helper': aux}


FAKE_NAMES = (
    'war3map.j', 'war3map.imp', 'war3map.w3s', 'war3map.w3r', 'war3map.w3c', 'war3map.wtg',
    'war3map.wct', 'war3map.doo', 'war3mapUnits.doo', 'war3mapPreview.tga', 'war3mapMap.blp',
    'war3mapMisc.txt', 'war3mapSkin.txt', 'war3mapExtra.txt', 'war3map.shd', 'war3map.mmp',
    'war3map.wpm', 'war3map.w3e', 'war3map.w3i', 'war3map.wts', 'units\\CommandStrings.txt',
    'units\\ItemStrings.txt', 'units\\AbilityStrings.txt', 'units\\UpgradeStrings.txt',
    'units\\CampaignAbilityStrings.txt', 'UI\\MiscData.txt', 'UI\\SkinMetaData.txt',
    'UI\\TipHelp.txt', 'UI\\War3Patch.txt', 'war3mapMap_ingame.blp', 'scripts\\war3map.j',
    'war3map.lua', 'war3map.w3a', 'war3map.w3t', 'war3map.w3u', 'war3map.w3b', 'war3map.w3d',
    'war3map.w3q', 'war3map.w3h', 'war3map.blp', 'war3map.ico', 'war3mapMap.tga',
) + tuple('Import\\%s.blp' % n for n in (
    'logo', 'loading', 'menu', 'button', 'border', 'icon_admin', 'icon_save', 'title',
    'background', 'panel', 'cursor', 'frame', 'logo2', 'loading2')) + tuple(
    'war3map%02d.blp' % i for i in range(8)) + tuple(
    'Sound\\%s.mp3' % n for n in ('theme', 'victory', 'defeat', 'click'))


DECOY_PAIR = tuple(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'decoy_triggers.' + e) for e in ('wtg', 'wct')
)


def _td():
    import id_shuffle
    return id_shuffle._td()


def _mold_read():
    if getattr(_mold_read, 'v', None) is None:
        import wtg
        with open(DECOY_PAIR[0], 'rb') as f:
            mt = wtg.read_wtg(f.read(), _td())
        with open(DECOY_PAIR[1], 'rb') as f:
            ct = wtg.read_wct(f.read())
        _mold_read.v = (mt, ct)
    return _mold_read.v


def _replace_in_model(obj, swap):
    import dataclasses
    for f in dataclasses.fields(obj):
        x = getattr(obj, f.name)
        if isinstance(x, str):
            setattr(obj, f.name, swap(x))
        elif dataclasses.is_dataclass(x):
            _replace_in_model(x, swap)
        elif isinstance(x, list):
            for y in x:
                if dataclasses.is_dataclass(y):
                    _replace_in_model(y, swap)


def _replacer(marks, value_list):
    import re
    map_path = dict((marks[k], value_list[k]) for k in marks if k != 'X' and k in value_list)
    rx = re.compile('|'.join(re.escape(m) for m in sorted(map_path, key=len, reverse=True)))
    exact_match = 'ChatMatchTypeExact' if value_list['X'] else 'ChatMatchTypeSubstring'

    def swap(s):
        s = rx.sub(lambda m: map_path[m.group(0)], s)
        return exact_match if s == 'ChatMatchTypeExact' else s
    return swap


def decoy_model(plain_name):
    import copy
    import wtg
    mt0, ct0 = _mold_read()
    index_ = dict((t, k) for k, (t, _s) in enumerate(DECOY_KINDS))
    marks = dict((t, _markers(k)) for k, (t, _s) in enumerate(DECOY_KINDS, 1))
    vars0 = dict((v.name, v) for v in mt0.variables)
    mt = wtg.MapTriggers(version=mt0.version, game_version=mt0.game_version,
                         categories=[wtg.Category(id=k, name=n) for k, n in enumerate(plain_name['categories'])])
    ct = wtg.CustomText(is_new_format=ct0.is_new_format, comment='',
                        header=plain_name['helper'].replace('\n', '\r\n') or None, version=ct0.version)
    for (type_name, value_list), cat in zip(plain_name['trigger_list'], plain_name['within']):
        swap = _replacer(marks[type_name], value_list)
        for field_id, _tp, _arr in _KIND[type_name]['vars']:
            v = copy.deepcopy(vars0[marks[type_name][field_id]])
            _replace_in_model(v, swap)
            mt.variables.append(v)
        t = copy.deepcopy(mt0.triggers[index_[type_name]])
        _replace_in_model(t, swap)
        t.description, t.category_id = '', cat
        mt.triggers.append(t)
        body_text = ct0.texts[index_[type_name]]
        ct.texts.append(None if body_text is None else swap(body_text))
    return mt, ct


def pair_rng(seed):
    return random.Random('wtg:%d' % seed)


def imp_decoy(rng):
    out = [struct.pack('<II', 1, rng.randint(120, 400))]
    for _ in range(24):
        fname = ''.join(rng.choice('abcdefghijklmnopqrstuvwxyz_0123456789') for _ in range(rng.randint(4, 14)))
        out.append(fname.encode('ascii') + b'\0' + struct.pack('<II', rng.choice((0, 1, 2)), rng.randint(0, 13)))
    return b''.join(out)


def preview_decoy(rng):
    w = h = 1 << rng.randint(7, 10)
    return b'BLP1' + struct.pack('<IIII', 0, 8, w, h) + bytes(rng.randrange(256) for _ in range(2048))


SYLLABLES = ('ban', 'kar', 'vel', 'dor', 'mir', 'tok', 'zel', 'gran', 'fen', 'lor', 'nal', 'thar',
             'vil', 'kor', 'sha', 'run')
FOLDERS_EXT = (
    ('', '.blp'), ('', '.tga'), ('', '.mdx'), ('', '.txt'),
    ('war3mapImported\\', '.blp'), ('war3mapImported\\', '.tga'), ('war3mapImported\\', '.mdx'),
    ('war3mapImported\\', '.wav'), ('war3mapImported\\', '.txt'),
    ('Import\\', '.blp'), ('Import\\', '.tga'), ('Import\\', '.mdx'), ('Import\\', '.txt'),
    ('Sound\\', '.wav'), ('Sound\\', '.mp3'),
    ('Models\\', '.mdx'),
    ('Textures\\', '.blp'), ('Textures\\', '.tga'),
    ('UI\\', '.blp'), ('UI\\', '.txt'),
    ('Units\\', '.txt'),
    ('Scripts\\', '.j'), ('Scripts\\', '.lua'),
    ('war3map\\', '.blp'),
)
FOLDERS_HEX = ('', 'war3mapImported\\', 'Import\\')


def _free(a):
    free_slots = deleted = 0
    for i in range(a.hash_n_read):
        bi = a.ht[i * 4 + 3]
        if bi == 0xFFFFFFFF:
            free_slots += 1
        elif bi == 0xFFFFFFFE:
            deleted += 1
    return free_slots, deleted, a.hash_n


def _fill_name(rng, exists, in_use):
    while True:
        if rng.random() < 0.25:
            ext = '.blp'
            fname = '%s%032x%s' % (rng.choice(FOLDERS_HEX), rng.getrandbits(128), ext)
        else:
            folder, ext = rng.choice(FOLDERS_EXT)
            fname = '%s%s%d%s' % (folder, ''.join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3))),
                                  rng.randint(2, 99), ext)
        if fname not in in_use and fname not in FAKE_NAMES and not exists(fname):
            in_use.add(fname)
            return fname, ext


def _fill_body(rng, ext):
    if ext == '.txt':
        line_list = ['# save codes backup - do not share']
        for _ in range(rng.randint(6, 16)):
            code_part = '-'.join(''.join(rng.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(4))
                                 for _ in range(3))
            line_list.append('slot %d: %s' % (rng.randint(1, 24), code_part))
        return ('\r\n'.join(line_list) + '\r\n').encode('ascii')
    noise = bytes(rng.randrange(256) for _ in range(rng.randint(64, 128)))
    if ext == '.blp':
        return b'BLP1' + struct.pack('<IIII', 0, 8, 1 << rng.randint(7, 10), 1 << rng.randint(7, 10)) + noise
    if ext == '.tga':
        return noise + b'TRUEVISION-XFILE.\x00'
    if ext == '.mdx':
        return b'MDXL' + struct.pack('<II', rng.randint(0, 9), 0) + noise
    if ext == '.mp3':
        return b'ID3\x04\x00\x00\x00\x00\x00' + noise
    return b'RIFF' + struct.pack('<I', 36 + len(noise)) + b'WAVEfmt ' + noise


def _seed_from_file(file_path):
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for block_entry in iter(lambda: f.read(1 << 20), b''):
            h.update(block_entry)
    return int(h.hexdigest()[:16], 16)


def _fill_refusal(details, why, log):
    details.update(action_code='declined', why=why, summary='REFUSED: %s' % why)
    log('[fill] %s' % details['summary'])
    return details


def _spare_last(file_path, bcount0, log=print):
    import mpqread as mr
    import mpqlib as ml
    a = mr.Archive(file_path)
    h = a.h
    tab = bytearray(ml.decrypt_bytes(a.d[h.hash_abs:h.hash_abs + a.hash_n * 16], ml.hashstr('(hash table)', 3)))
    idx = a.hash_n - 1
    bi = struct.unpack_from('<I', tab, idx * 16 + 12)[0]
    if bi in (0xFFFFFFFF, 0xFFFFFFFE):
        return 'free'
    if (bi & 0x0FFFFFFF) < bcount0:
        log(
            '[fill] the LAST entry points at block %d of the real map: the cut afterwards refuses with the reason'
            % (bi & 0x0FFFFFFF)
        )
        return 'of the map'
    struct.pack_into('<I', tab, idx * 16 + 12, 0xFFFFFFFE)
    with open(file_path, 'r+b') as f:
        f.seek(h.hash_abs)
        f.write(ml.encrypt_bytes(bytes(tab), ml.hashstr('(hash table)', 3)))
    log('[fill] the LAST entry (the one the cut removes) was a decoy of this fill: it is now DELETED')
    return 'spared'


def fill(file_path, seed=None, rng=None, log=print, spare_last=False, together=False):
    import mpqadd
    import mpqread
    file_path = os.path.abspath(file_path)
    details = {'file_path': file_path, 'written_count': 0, 'ok': False}
    a = mpqread.Archive(file_path)
    if a.hash_n != a.hash_n_read:
        return _fill_refusal(details, 'the hash table goes past the end of the file (%d entries declared, %d '
                             'in the file: virtual table of the protector) -- fix the map first'
                             % (a.hash_n, a.hash_n_read), log)
    if a.hash_n & (a.hash_n - 1):
        return _fill_refusal(details, 'the hash table is not a power of 2 (%d entries): the writer probes '
                             'with `size - 1` and does not fill' % a.hash_n, log)
    if a.h.hash_pos & 0x80000000 or a.h.block_pos & 0x80000000:
        return _fill_refusal(details, 'bit 31 in the table position (the bit31 variant: the table before the '
                             'header): the writer would move the block table to the end and the mark would be '
                             'lost', log)
    game = dict((n, a.read(n)) for n in ('war3map.w3i', 'war3map.w3e', 'war3map.wpm', 'war3map.doo',
                                         'war3map.shd', 'war3map.mmp') if a.find(n) is not None)
    free0, deleted0, hash_entries = _free(a)
    bcount0 = min(a.block_n, len(a.blocks))
    details['hash_entries'] = hash_entries
    details['free_before'] = free0 + deleted0
    if not details['free_before']:
        details.update(action_code='nothing', free_after=0, ok=True,
                       gate='ok (the hash table is already full: %d entries, 0 free)' % hash_entries,
                       summary='nothing to fill: the hash table is already FULL (%d entries, none free or '
                            'deleted) -- nobody adds a new file' % hash_entries)
        log('[fill] %s' % details['summary'])
        return details
    if rng is None:
        rng = random.Random(seed if seed is not None else _seed_from_file(file_path))
    in_use, written_count = set(), []
    for _run_once in range(5):
        a = mpqread.Archive(file_path)
        free_slots, deleted, _n = _free(a)
        if not free_slots and not deleted:
            break
        batch = []
        for _ in range(free_slots + deleted):
            fname, ext = _fill_name(rng, a.find, in_use)
            batch.append((fname, _fill_body(rng, ext)))
        no_slot = []
        mpqadd.add_files(file_path, batch, no_slot=no_slot, log=lambda *x: None, together=together)
        outside = set(no_slot)
        written_count += [(n, d) for n, d in batch if n not in outside]
    b = mpqread.Archive(file_path)
    bad_ones = []
    for fname, data_bytes in written_count:
        if b.read(fname) != data_bytes:
            bad_ones.append('%s: what was written does not re-read the same' % fname)
    for fname, data_bytes in game.items():
        if b.read(fname) != data_bytes:
            bad_ones.append('%s: what the GAME reads changed!' % fname)
    if spare_last:
        details['last_unit'] = _spare_last(file_path, bcount0, log=log)
        b = mpqread.Archive(file_path)
    free_d, deleted_d, _n = _free(b)
    details['free_after'] = free_d + deleted_d
    last_dead = spare_last and b.ht[4 * (b.hash_n - 1) + 3] in (0xFFFFFFFF, 0xFFFFFFFE)
    if details['free_after'] > (1 if last_dead else 0):
        bad_ones.append('the hash table did not fill up: %d free/deleted entry(ies) left over'
                        % details['free_after'])
    if bad_ones:
        details.update(gate='FAILED: %s' % bad_ones[:5], summary='FAILED: %s' % bad_ones[:5])
        log('[fill] %s' % details['summary'])
        raise SystemExit('ABORT (fill): %s' % bad_ones[:5])
    details.update(action_code='filled', written_count=len(written_count), bytes=sum(len(d) for _n, d in written_count),
                   name_list=[n for n, _d in written_count[:5]], ok=True,
                   gate='ok (%d filler decoy(s), all re-read; the hash table FULL: %d entries, '
                              '0 free; nothing of the game changed)' % (len(written_count), hash_entries),
                   summary='the hash table filled up to the header limit: %d filler decoy(s) '
                              '(%d B), %d entries, 0 free or deleted -- nobody adds a new file'
                              % (len(written_count), sum(len(d) for _n, d in written_count), hash_entries))
    log('[fill] %s' % details['summary'])
    return details


STANDARD = ('wtg', 'listfile', 'imp')


def decoys(entry, output, chosen=STANDARD, seed=None, log=print, spare_last=False):
    import editor_lock
    import mpqadd
    import mpqread
    entry, output = os.path.abspath(entry), os.path.abspath(output)
    if entry == output:
        raise SystemExit('the output must be another file (the input never changes)')
    unknowns = set(chosen) - {'wtg', 'listfile', 'imp', 'preview', 'fill'}
    if unknowns:
        raise SystemExit('unknown decoy in --decoys: %s (valid: wtg,listfile,imp,preview,fill)'
                         % sorted(unknowns))
    shutil.copyfile(entry, output)
    a = mpqread.Archive(entry)
    name_list = list(editor_lock.map_names(a))
    if seed is None:
        seed = _seed_from_file(entry)
    rng = random.Random(seed)
    details = {'entry': entry, 'output': output, 'decoys': list(chosen), 'matrix': {}, 'ok': False}
    write_out = []

    def present(fname):
        return a.find(fname) is not None

    if 'wtg' in chosen:
        if present('war3map.wtg') or present('war3map.wct'):
            details['matrix']['war3map.wtg'] = {'action_code': 'declined',
                                                'why': 'the map still has the REAL wtg/wct: run after editor_lock'}
            log('[decoy] wtg+wct REFUSED: the map still has the real ones')
        else:
            plain_name = decoy_plan(pair_rng(seed))
            mt, ct = decoy_model(plain_name)
            import wtg as _wtg
            wtg, wct = _wtg.write_wtg(mt, _td()), _wtg.write_wct(ct)
            write_out += [('war3map.wtg', wtg), ('war3map.wct', wct)]
            trigger_names = ', '.join(t.name for t in mt.triggers)
            details['matrix']['war3map.wtg'] = {
                'action_code': 'recorded',
                'bytes': len(wtg),
                'trigger_list': trigger_names,
            }
            details['matrix']['war3map.wct'] = {'action_code': 'recorded', 'bytes': len(wct)}
            log(
                '[decoy] wtg+wct: %d + %d B (%d random triggers: %s)'
                % (len(wtg), len(wct), len(mt.triggers), trigger_names)
            )
    if 'listfile' in chosen:
        details['matrix']['(listfile)'] = {'action_code': 'deleted'}
        log('[decoy] (listfile): OUT of the map (the name "mining" has nothing to mine)')
    for fname, type_name, generator_fn in (
        ('war3map.imp', 'imp', imp_decoy),
        ('war3mapPreview.blp', 'preview', preview_decoy),
    ):
        if type_name not in chosen:
            continue
        if present(fname):
            details['matrix'][fname] = {'action_code': 'declined', 'why': 'the map still has the REAL %s' % fname}
            log('[decoy] %s REFUSED: the map still has the real one' % fname)
            continue
        data_bytes = generator_fn(rng)
        write_out.append((fname, data_bytes))
        details['matrix'][fname] = {'action_code': 'recorded', 'bytes': len(data_bytes)}
        log('[decoy] %s: %d B of plausible header + noise' % (fname, len(data_bytes)))
    if write_out:
        mpqadd.add_files(output, write_out, log=lambda *x: None)
    if 'listfile' in chosen:
        mpqadd.add_files(output, [], to_delete=['(listfile)'], log=lambda *x: None)
    filled = None
    if 'fill' in chosen:
        filled = fill(output, rng=rng, log=log, spare_last=spare_last)
        details['fill'] = dict((k, v) for k, v in filled.items()
                               if k in ('action_code', 'why', 'written_count', 'bytes', 'hash_entries', 'free_before',
                                        'free_after', 'gate', 'summary'))
        details['matrix']['(hash table)'] = dict((k, filled[k]) for k in ('action_code', 'why', 'written_count',
                                                                      'hash_entries') if k in filled)
    b = mpqread.Archive(output)
    bad_ones = []
    for fname, data_bytes in write_out:
        if b.read(fname) != data_bytes:
            bad_ones.append('%s: what was written does not re-read the same' % fname)
    if 'listfile' in chosen and b.find('(listfile)') is not None:
        bad_ones.append('the (listfile) stayed in the map (the rule: NO listfile at all)')
    for fname in ('war3map.w3i', 'war3map.w3e', 'war3map.wpm', 'war3map.doo', 'war3map.shd', 'war3map.mmp'):
        if present(fname) and b.read(fname) != a.read(fname):
            bad_ones.append('%s: what the GAME reads changed!' % fname)
    details['gate'] = (
        'ok (%d decoy(s) written, all re-read; nothing of the game changed)' % len(write_out)
        if not bad_ones
        else 'FAILED: %s' % bad_ones
    )
    if not bad_ones and filled is not None:
        if filled['action_code'] == 'filled':
            details['gate'] += '; the hash table FULL: %d filler decoy(s), %d entries, 0 free' % (
                filled['written_count'], filled['hash_entries'])
        elif filled['action_code'] == 'declined':
            details['gate'] += '; fill REFUSED: %s' % filled['why']
    if bad_ones:
        raise SystemExit('ABORT: %s' % bad_ones)
    details['written_count'] = len(write_out)
    details['ok'] = True
    log(
        'DECOYS %s: %d written in %s; %s'
        % ('OK' if details['ok'] else 'FAILED', len(write_out), output, details['gate'])
    )
    return details

def bomb_block(fsize, sector_bytes, rng):
    if not 0 < fsize < 0x80000000:
        raise SystemExit('the bomb: the declared size %d goes over the 2 GiB - 1 ceiling (the `IsValidHashEntry1` in '
                         'malformed MPQ, e.g. the `cut-hash`, refuses a block >= 0x80000000)' % fsize)
    nsec = (fsize + sector_bytes - 1) // sector_bytes
    expected_len = fsize - (nsec - 1) * sector_bytes
    if not 0 < expected_len <= sector_bytes:
        raise SystemExit('the bomb: the final sector (%d) is outside 1..%d for %d B (the nsec computation broke: '
                         'fsize=%d, sector=%d)' % (expected_len, sector_bytes, fsize, fsize, sector_bytes))
    tail = zlib.compress(b'\x00' * (expected_len - 16) + bytes(rng.randrange(256) for _ in range(16)), 9)
    table = struct.pack('<I', 4 * (nsec + 1)) * nsec + struct.pack('<I', 4 * (nsec + 1) + len(tail))
    return table + tail


def bulk_spec(txt):
    spec = {'bombs': 8, 'slices': 2000}
    for t in (x for x in (txt or '').split(',') if x):
        fname, _, field_value = t.partition(':')
        if fname not in spec:
            raise SystemExit('--bulk: unknown token %r (valid: bombs,slices,listing, each with an optional :N)' % t)
        if field_value:
            if not field_value.isdigit() or int(field_value) < 0:
                raise SystemExit('--bulk: the token %s has the value %r, not a number >= 0' % (t, field_value))
            spec[fname] = int(field_value)
    return spec


def _cut_reservation(file_path, bcount0, log=print):
    import mpqread as mr
    import mpqlib as ml
    a = mr.Archive(file_path)
    h = a.h
    tables = bytearray(ml.decrypt_bytes(a.d[h.hash_abs:h.hash_abs + h.hash_n * 16], ml.hashstr('(hash table)', 3)))
    idx = h.hash_n - 1
    if a.hash_n != a.hash_n_read:
        raise SystemExit('bulk: the map table declared more than exists (the cut only works on the full table)')
    n1, n2, loc, plat, bi = struct.unpack_from('<IIHHI', tables, idx * 16)
    if bi in (0xFFFFFFFF, 0xFFFFFFFE):
        return 'free'
    if (bi & 0x0FFFFFFF) < bcount0:
        log('[bulk] the LAST entry points at block %d of the real map: the cut afterwards REFUSES with the reason '
            '(nothing changed here)' % (bi & 0x0FFFFFFF))
        return 'of the map'
    dead_slot = None
    j = (idx + 1) & (a.hash_n - 1)
    while j != idx:
        bij = struct.unpack_from('<I', tables, j * 16 + 12)[0]
        if bij in (0xFFFFFFFF, 0xFFFFFFFE):
            dead_slot = j
            break
        j = (j + 1) & (a.hash_n - 1)
    if dead_slot is None:
        raise SystemExit('bulk: no dead slot in the chain of the last entry (the table filled up): nothing to move, '
                         'the cut afterwards refuses with the reason')
    tables2 = bytearray(tables)
    struct.pack_into('<IIHHI', tables2, idx * 16, n1, n2, loc, plat, 0xFFFFFFFE)
    struct.pack_into('<IIHHI', tables2, dead_slot * 16, n1, n2, loc, plat, bi)
    with open(file_path, 'r+b') as f:
        f.seek(h.hash_abs)
        f.write(ml.encrypt_bytes(bytes(tables2), ml.hashstr('(hash table)', 3)))
    b = mr.Archive(file_path)
    _ht2 = struct.pack('<%dI' % len(b.ht), *b.ht)
    if struct.unpack_from('<I', _ht2, idx * 16 + 12)[0] != 0xFFFFFFFE:
        raise SystemExit('bulk: the cut reservation was not written (the last entry stayed alive)')
    if struct.unpack_from('<IIHHI', _ht2, dead_slot * 16) != (n1, n2, loc, plat, bi):
        raise SystemExit('bulk: the cut reservation corrupted the re-homed entry (slot %d)' % dead_slot)
    log('[bulk] cut reservation: the last entry is OURS (block %d): the slot became DELETED and the entry '
        're-homed to slot %d of the chain (the probing of the name stays valid)' % (bi & 0x0FFFFFFF, dead_slot))
    return 'reservation_done'


def bulk(file_path, bombs=8, byte_size=(1 << 31) - (1 << 21), slices=2000, listing=5000, seed=None, log=print,
         to_verify=True):
    import mpqadd
    import mpqread as mr
    import mpqlib as ml
    t0 = time.time()
    a = mr.Archive(file_path)
    if a.h.hash_pos & 0x80000000 or a.h.block_pos & 0x80000000:
        raise SystemExit('bulk: bit 31 in the table position (the bit31 variant: the table physically before the '
                         'header): the insertion rewrites the tables and the mark is lost (in the recipe, ask for the '
                         'protect WITHOUT bit31 when the bulk and the cut are the goal)')
    if a.hash_n != a.hash_n_read:
        raise SystemExit("bulk: the declared hash table already goes past the end of the file (the cut-hash?): run the "
                         'bulk BEFORE the cut')
    sector_bytes = ml.header_sector(a.h.block_shift)
    bcount0 = min(a.block_n, len(a.blocks))
    in_use = set()
    if seed is None:
        seed = _seed_from_file(file_path)
    rng = random.Random(seed)
    bulk_details = {'bombs': 0, 'slices': 0, 'claimed': 0, 'bytes': 0}
    specs = []
    weight_names = []
    _step382 = max(sector_bytes + 1, byte_size // max(bombs, 1)) if bombs else sector_bytes
    for _k in range(bombs):
        fsize = byte_size - _k * _step382
        if fsize <= sector_bytes:
            break
        fname, _e = _fill_name(rng, a.find, in_use)
        block_entry = bomb_block(fsize, sector_bytes, rng)
        specs.append((fname, ('block_entry', block_entry, fsize, 0x80000000 | 0x00000200)))
        weight_names.append(fname)
        bulk_details['bombs'] += 1
        bulk_details['claimed'] += fsize
        bulk_details['bytes'] += len(block_entry)
        log('[bulk] bomb %d: %s (%s claimed, %d B written: ratio %.0f:1)'
            % (_k + 1, fname, _gib_text(fsize), len(block_entry), fsize / max(1, len(block_entry))))
    data_limit = a.h.hash_abs
    data_base = a.h.offset + 0x20
    for _k in range(slices):
        fname, _e = _fill_name(rng, a.find, in_use)
        size_f = rng.randint(1, 65536)
        if data_limit - data_base < size_f + 16:
            break
        rel_f = 0x20 + rng.randint(0, data_limit - data_base - size_f)
        specs.append((fname, ('band', rel_f, size_f)))
        weight_names.append(fname)
        bulk_details['slices'] += 1
    sz = mpqadd.add_files(file_path, [],
                          to_delete=['(listfile)'] if a.find('(listfile)') is not None else [],
                          grow=(), slack=len(specs) + 100, weight=specs, hero_attributes=False, log=lambda *x: None)
    fallback_fdf = _cut_reservation(file_path, bcount0, log=log)
    b = mr.Archive(file_path)
    bad_ones = []
    if to_verify:
        for fname in ('war3map.w3i', 'war3map.w3e', 'war3map.wpm', 'war3map.doo', 'war3map.shd', 'war3map.mmp'):
            if a.find(fname) is not None and (b.find(fname) is None or b.read(fname) != a.read(fname)):
                bad_ones.append('%s: what the GAME reads changed!' % fname)
        for fname, tgt in specs:
            r = b.find(fname)
            if r is None:
                bad_ones.append('%s: the bulk entry did not get into the hash table (the table has %d entries, %d '
                                'available)' % (fname, b.hash_n, _free(b)[0] + _free(b)[1]))
                continue
            _slot, block_entry = r
            fpos, csize, fsize, flags = b.blocks[block_entry]
            if tgt[0] == 'band':
                _, rel_f, size_f = tgt
                if (fpos, csize, fsize) != (rel_f, size_f, size_f) or flags & 0x000000FF:
                    bad_ones.append(
                        '%s: the written range is different (%d, %d, %d, flags %x)' % (fname, fpos, csize, fsize, flags)
                    )
                    continue
                read_back = b.read(fname)
                if read_back != b.d[b.h.offset + rel_f:b.h.offset + rel_f + size_f]:
                    bad_ones.append('%s: the slice read back is not the bytes of the file in the range' % fname)
            else:
                _, _b_b, fsize_b, _flags_b = tgt
                if fsize != fsize_b or csize != len(tgt[1]) or \
                        (flags & 0x00000200) == 0 or (flags & 0x80000000) == 0:
                    bad_ones.append(
                        '%s: the written bomb is different (%d, %d, %d, flags %x)' % (fname, fsize, csize, flags, flags)
                    )
    if b.find('(listfile)') is not None:
        bad_ones.append('the (listfile) stayed in the map (the rule: NO listfile, in no option)')
    if bad_ones:
        raise SystemExit('ABORT at step bulk: %s' % '; '.join(bad_ones[:4]))
    details = {'ok': True, 'file_path': file_path, 'seconds': round(time.time() - t0, 1),
               'shift': sector_bytes, 'fallback_fdf': fallback_fdf, **bulk_details,
               'gate': ('ok (%d bomb(s) of %s claimed in total, %d slice(s); %s written; the reserve of the '
                        'cut: %s; NO listfile)'
                        % (bulk_details['bombs'], _gib_text(bulk_details['claimed']), bulk_details['slices'],
                           _gib_text(bulk_details['bytes']), fallback_fdf))}
    log('[bulk] %s' % details['gate'])
    return details


def _gib_text(n):
    _n = int(n)
    for f, s in ((1 << 30, 'GiB'), (1 << 20, 'MiB'), (1, 'B')):
        if _n >= f:
            return '%.1f %s' % (_n / f, s)
    return '0 B'

