# Writes decoy files into a map: fake triggers, a lying file list, fake imports.
import hashlib
import os
import random
import shutil
import struct



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


def decoy_pair(log=print):
    out = []
    for p in DECOY_PAIR:
        with open(p, 'rb') as f:
            out.append(f.read())
    return tuple(out)


def fake_listing(map_names, rng, exists=None):
    real_blocks = set(n.lower().replace('/', '\\') for n in map_names)
    fake_list = [n for n in FAKE_NAMES if n.lower() not in real_blocks and n not in ('(listfile)', '(attributes)')
                 and not (exists and exists(n))]
    rng.shuffle(fake_list)
    return ('\r\n'.join(fake_list) + '\r\n').encode('utf-8')


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
EXT_FILL = ('.blp', '.tga', '.mdx', '.txt', '.mp3', '.wav')


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
            fname = 'Import\\%032x%s' % (rng.getrandbits(128), ext)
        else:
            ext = rng.choice(EXT_FILL)
            fname = 'Import\\%s%d%s' % (''.join(rng.choice(SYLLABLES) for _ in range(rng.randint(2, 3))),
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


def fill(file_path, seed=None, rng=None, log=print):
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
        mpqadd.add_files(file_path, batch, no_slot=no_slot, log=lambda *x: None)
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
    free_d, deleted_d, _n = _free(b)
    details['free_after'] = free_d + deleted_d
    if details['free_after']:
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


def decoys(entry, output, chosen=STANDARD, seed=None, log=print):
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
            wtg, wct = decoy_pair(log=log)
            write_out += [('war3map.wtg', wtg), ('war3map.wct', wct)]
            details['matrix']['war3map.wtg'] = {
                'action_code': 'recorded',
                'bytes': len(wtg),
                'trigger_list': 'AdminGold, SaveSystem, LevelUp',
            }
            details['matrix']['war3map.wct'] = {'action_code': 'recorded', 'bytes': len(wct)}
            log('[decoy] wtg+wct: %d + %d B (AdminGold/SaveSystem/LevelUp)' % (len(wtg), len(wct)))
    if 'listfile' in chosen:
        listing = fake_listing(name_list, rng, exists=present)
        write_out.append(('(listfile)', listing))
        details['matrix']['(listfile)'] = {'action_code': 'substituted', 'bytes': len(listing),
                                           'name_list': listing.decode('utf-8').count('\r\n')}
        log(
            '[decoy] lying (listfile): %d plausible names that are not in the map'
            % listing.decode('utf-8').count('\r\n')
        )
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
    filled = None
    if 'fill' in chosen:
        filled = fill(output, rng=rng, log=log)
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

