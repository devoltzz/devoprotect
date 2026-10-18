# Reads files from the local Warcraft III (Reforged) CASC storage.
import fnmatch
import hashlib
import os
import struct
import sys
import zlib


def _default_game_dir():
    folder = os.environ.get('WC3_GAME')
    if folder:
        return folder
    try:
        import winreg
        for key in (r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Warcraft III',
                    r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Warcraft III'):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    value = winreg.QueryValueEx(k, 'InstallLocation')[0]
                if value and os.path.isdir(value):
                    return value
            except OSError:
                pass
    except ImportError:
        pass
    return r'C:\Program Files (x86)\Warcraft III'


DEFAULT_GAME = _default_game_dir()


class CascError(Exception):
    pass


def _lz4_block(src, output_size):
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        if off == 0 or off > len(out):
            raise CascError('LZ4: invalid offset (%d)' % off)
        begin = len(out) - off
        for k in range(ml):
            out.append(out[begin + k])
    if output_size is not None and len(out) != output_size:
        raise CascError('LZ4: produced %d bytes, expected %d' % (len(out), output_size))
    return bytes(out)


def _blte_block(block_entry, expected_size=None):
    if not block_entry:
        return b''
    method = block_entry[0:1]
    block_body = block_entry[1:]
    if method == b'N':
        return block_body
    if method == b'Z':
        return zlib.decompress(block_body)
    if method == b'4':
        if len(block_body) < 10 or block_body[0] != 1:
            raise CascError('BLTE mode 4: unknown LZ4 header')
        sz = struct.unpack('>Q', block_body[1:9])[0]
        return _lz4_block(block_body[10:], sz)
    if method == b'F':
        return blte_decode(block_body)
    if method == b'E':
        nk = block_body[0]
        fname = block_body[1:1 + nk][::-1].hex()
        raise CascError('BLTE mode E (encrypted, key %s): cannot be opened without the TACT key' % fname)
    raise CascError('BLTE: unknown block mode %r' % method)


def blte_decode(data_bytes, check_md5=True):
    if data_bytes[:4] != b'BLTE':
        raise CascError('BLTE: missing signature (%r)' % data_bytes[:4])
    header_len = struct.unpack('>I', data_bytes[4:8])[0]
    if header_len == 0:
        return _blte_block(data_bytes[8:])
    flags = data_bytes[8]
    nblocks = int.from_bytes(data_bytes[9:12], 'big')
    if flags != 0x0F:
        raise CascError('BLTE: block table with flags 0x%02x not supported (only 0x0F)' % flags)
    width = 24
    p = 12
    infos = []
    for _ in range(nblocks):
        comp, decomp = struct.unpack('>II', data_bytes[p:p + 8])
        md5 = data_bytes[p + 8:p + 24]
        infos.append((comp, decomp, md5))
        p += width
    if p != header_len:
        raise CascError('BLTE: block table ends at %d, the header says %d' % (p, header_len))
    output = []
    for comp, decomp, md5 in infos:
        block_entry = data_bytes[p:p + comp]
        if len(block_entry) != comp:
            raise CascError('BLTE: truncated block')
        if check_md5 and hashlib.md5(block_entry).digest() != md5:
            raise CascError('BLTE: block MD5 does not match')
        dec = _blte_block(block_entry)
        if len(dec) != decomp:
            raise CascError('BLTE: block decompressed to %d bytes, expected %d' % (len(dec), decomp))
        output.append(dec)
        p += comp
    return b''.join(output)


def read_build_info(game):
    file_path = os.path.join(game, '.build.info')
    with open(file_path, 'r', encoding='utf-8') as f:
        line_list = [lx.rstrip('\r\n') for lx in f if lx.strip() and not lx.startswith('#')]
    head_line = [c.split('!')[0] for c in line_list[0].split('|')]
    line_dicts = [dict(zip(head_line, lx.split('|'))) for lx in line_list[1:]]
    active_rows = [d for d in line_dicts if d.get('Active') == '1'] or line_dicts
    return active_rows[0]


def _config_path(game, hash_key):
    return os.path.join(game, 'Data', 'config', hash_key[0:2], hash_key[2:4], hash_key)


def read_config(game, hash_key):
    cfg = {}
    with open(_config_path(game, hash_key), 'r', encoding='utf-8') as f:
        for lx in f:
            lx = lx.strip()
            if not lx or lx.startswith('#') or '=' not in lx:
                continue
            k, v = lx.split('=', 1)
            cfg[k.strip()] = v.strip()
    return cfg


_TREES = {}


def _memo():
    try:
        import memo
        return memo
    except ImportError:
        mod = sys.modules.get('_casc_memo')
        if mod is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                '_casc_memo', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'memo.py'))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.modules['_casc_memo'] = mod
        return mod


PACK_MANIFEST = 'doctor_game_data.json'
PACK_LIST = 'paths.txt'
def pack_file_path(game, file_path):
    return os.path.join(game, 'files', *file_path.replace(':', '\\').split('\\'))


class CascWC3(object):
    def __init__(self, game=DEFAULT_GAME, load_tvfs=True):
        self.game = os.path.abspath(game)
        if os.path.isfile(os.path.join(self.game, PACK_MANIFEST)):
            self._open_pack()
            return
        self.is_pack = False
        self.data_bytes = os.path.join(self.game, 'Data', 'data')
        if not os.path.isdir(self.data_bytes):
            raise CascError('no Data\\data in %s' % self.game)
        self.build_info = read_build_info(self.game)
        self.build_key = self.build_info['Build Key']
        self.config = read_config(self.game, self.build_key)
        self.version_num = self.build_info.get('Version', '?')
        self._open_files = {}
        self._encoding = None
        self.index_ = {}
        self.file_set = {}
        hash_key = self._tree_key()
        stored = _TREES.get(hash_key)
        if stored is None:
            memo = _memo()
            stored = memo.load('casc', hash_key)
            if not (isinstance(stored, tuple) and len(stored) == 2 and stored[0] and stored[1]):
                stored = None
            else:
                _TREES[hash_key] = stored
        if stored is not None:
            self.index_, self.file_set = stored
            return
        self._read_indices()
        if load_tvfs:
            self._load_tvfs()
            _TREES[hash_key] = (self.index_, self.file_set)
            memo = _memo()
            memo.save('casc', hash_key, _TREES[hash_key])

    def _open_pack(self):
        import json
        with open(os.path.join(self.game, PACK_MANIFEST), encoding='utf-8') as f:
            m = json.load(f)
        self.is_pack = True
        self.version_num, self.build_key = m['version'], m['build_key']
        self.build_info, self.config = {'Version': self.version_num, 'Build Key': self.build_key}, {}
        self.index_, self._open_files, self._encoding = {}, {}, None
        self._objects = m.get('objects') or {}
        self._store = os.path.normpath(os.path.join(self.game, m.get('store') or 'objects'))
        with open(os.path.join(self.game, PACK_LIST), encoding='utf-8') as f:
            self.file_set = dict((lx.lower(), (lx, None)) for lx in f.read().split('\n') if lx)
        if len(self.file_set) != m['total']:
            raise CascError('pack: %s has %d paths, the manifest says %d'
                            % (PACK_LIST, len(self.file_set), m['total']))

    def _tree_key(self):
        memo = _memo()
        idx = tuple(sorted((n, os.path.getsize(os.path.join(self.data_bytes, n))) for n in os.listdir(self.data_bytes)
                           if n.lower().endswith('.idx')))
        return memo.key(self.game.lower(), self.build_key, self.config.get('vfs-root', ''), idx)

    def _read_indices(self):
        newest = {}
        for fname in os.listdir(self.data_bytes):
            if not fname.lower().endswith('.idx') or len(fname) != 14:
                continue
            try:
                bucket = int(fname[0:2], 16)
                version_num = int(fname[2:10], 16)
            except ValueError:
                continue
            if bucket not in newest or version_num > newest[bucket][0]:
                newest[bucket] = (version_num, fname)
        if not newest:
            raise CascError('no .idx in %s' % self.data_bytes)
        for bucket in sorted(newest):
            with open(os.path.join(self.data_bytes, newest[bucket][1]), 'rb') as f:
                d = f.read()
            hash_size = struct.unpack_from('<I', d, 0)[0]
            version_num, _bucket, extra, b_size, b_off, b_key, bits = struct.unpack_from('<HBBBBBB', d, 8)
            if version_num != 7 or (b_size, b_off, b_key) != (4, 5, 9) or hash_size != 0x10:
                raise CascError('index %s: unknown header (version %d, fields %d/%d/%d)'
                                % (newest[bucket][1], version_num, b_size, b_off, b_key))
            entries_size = struct.unpack_from('<I', d, 0x20)[0]
            p, end_pos = 0x28, 0x28 + entries_size
            width = b_key + b_off + b_size
            bitmask = (1 << bits) - 1
            while p + width <= end_pos:
                hash_key = d[p:p + 9]
                v = int.from_bytes(d[p + 9:p + 14], 'big')
                sz = struct.unpack_from('<I', d, p + 14)[0]
                self.index_.setdefault(hash_key, []).append((v >> bits, v & bitmask, sz))
                p += width

    def _data_file(self, n):
        f = self._open_files.get(n)
        if f is None:
            f = open(os.path.join(self.data_bytes, 'data.%03d' % n), 'rb')
            self._open_files[n] = f
        return f

    def read_ekey(self, ekey):
        if isinstance(ekey, str):
            ekey = bytes.fromhex(ekey)
        ents = self.index_.get(ekey[:9])
        if not ents:
            raise CascError('EKey %s is not in the local indexes (file not installed?)' % ekey[:9].hex())
        try:
            return self._read_ekey(ekey, ents)
        except CascError:
            raise
        except (struct.error, IndexError, ValueError, OSError) as e:
            raise CascError('EKey %s: %s: %s' % (ekey[:9].hex(), type(e).__name__, e))

    def _read_ekey(self, ekey, ents):
        error_list = []
        for file_, off, sz in ents:
            f = self._data_file(file_)
            f.seek(off)
            raw_bytes = f.read(sz)
            if len(raw_bytes) != sz:
                error_list.append('data.%03d@%d truncated' % (file_, off))
                continue
            if raw_bytes[:4] == b'BLTE':
                return blte_decode(raw_bytes)
            if raw_bytes[0:16][::-1][:9] == ekey[:9] and raw_bytes[30:34] == b'BLTE':
                return blte_decode(raw_bytes[30:])
            error_list.append('data.%03d@%d: neither BLTE nor a header with the requested EKey' % (file_, off))
        raise CascError('EKey %s: %s' % (ekey[:9].hex(), '; '.join(error_list)))

    def _load_encoding(self):
        if self._encoding is not None:
            return
        ck, ek = self.config['encoding'].split()[:2]
        d = self.read_ekey(ek)
        if d[:2] != b'EN':
            raise CascError('encoding: missing signature')
        ck_size, ek_size = d[3], d[4]
        page_ce_kb, page_es_kb = struct.unpack_from('>HH', d, 5)
        n_ce, n_es = struct.unpack_from('>II', d, 9)
        espec_size = struct.unpack_from('>I', d, 18)[0]
        p = 22 + espec_size
        table = []
        for _ in range(n_ce):
            table.append(d[p:p + ck_size])
            p += ck_size + 16
        self._encoding = (d, p, page_ce_kb * 1024, table, ck_size, ek_size)

    def ekey_from_ckey(self, ckey):
        import bisect
        if isinstance(ckey, str):
            ckey = bytes.fromhex(ckey)
        self._load_encoding()
        d, begin, page_size, table, ck_size, ek_size = self._encoding
        i = bisect.bisect_right(table, ckey) - 1
        if i < 0:
            return None
        p = begin + i * page_size
        end_pos = p + page_size
        while p < end_pos:
            n = d[p]
            if n == 0:
                break
            ck = d[p + 6:p + 6 + ck_size]
            if ck == ckey:
                return d[p + 6 + ck_size:p + 6 + ck_size + ek_size]
            p += 6 + ck_size + n * ek_size
        return None

    def read_ckey(self, ckey):
        ek = self.ekey_from_ckey(ckey)
        if ek is None:
            raise CascError('CKey %s is not in the encoding file' % (ckey if isinstance(ckey, str) else ckey.hex()))
        return self.read_ekey(ek)

    def _load_tvfs(self):
        if 'vfs-root' not in self.config:
            raise CascError('build config without vfs-root: this reader only knows the WC3 TVFS root')
        self._vfs = set()
        for k, v in self.config.items():
            if k.startswith('vfs-') and not k.endswith('-size'):
                pieces = v.split()
                if len(pieces) >= 2:
                    self._vfs.add(bytes.fromhex(pieces[1])[:9])
        root = self.read_ekey(self.config['vfs-root'].split()[1])
        self._tvfs_directory(root, '')

    @staticmethod
    def _tvfs_header(d):
        if d[:4] != b'TVFS':
            raise CascError('TVFS: missing signature')
        version_num, ek_size = d[4], d[6]
        flags, off_path, path_size, off_vfs, vfs_size, off_cft, cft_size = struct.unpack_from('>7I', d, 8)
        max_depth = struct.unpack_from('>H', d, 36)[0]

        def width(t):
            return 4 if t > 0xFFFFFF else 3 if t > 0xFFFF else 2 if t > 0xFF else 1
        return dict(version_num=version_num, flags=flags, ek_size=ek_size, off_path=off_path, path_size=path_size,
                    off_vfs=off_vfs, vfs_size=vfs_size, off_cft=off_cft, cft_size=cft_size,
                    cft_width=width(cft_size), max_depth=max_depth)

    def _tvfs_directory(self, d, prefix):
        h = self._tvfs_header(d)
        self._tvfs_table(d, h, h['off_path'], h['off_path'] + h['path_size'], prefix)

    def _tvfs_spans(self, d, h, off):
        p = h['off_vfs'] + off
        n = d[p]
        p += 1
        if n == 0 or n > 224:
            raise CascError('TVFS: VFS entry with %d spans' % n)
        spans = []
        for _ in range(n):
            c_off, c_size = struct.unpack_from('>II', d, p)
            o_cft = int.from_bytes(d[p + 8:p + 8 + h['cft_width']], 'big')
            p += 8 + h['cft_width']
            q = h['off_cft'] + o_cft
            ekey = d[q:q + h['ek_size']]
            spans.append((c_off, c_size, bytes(ekey)))
        return spans

    def _tvfs_table(self, d, h, p, end_pos, file_path):
        base = file_path
        while p < end_pos:
            fname = ''
            if d[p] == 0:
                fname += '\\'
                p += 1
            if p < end_pos and d[p] != 0xFF:
                n = d[p]
                fname += d[p + 1:p + 1 + n].decode('utf-8', 'replace')
                p += 1 + n
            if p < end_pos and d[p] == 0:
                fname += '\\'
                p += 1
            elif p < end_pos and d[p] != 0xFF:
                fname += '\\'
            file_path = file_path + fname
            if p < end_pos and d[p] == 0xFF:
                field_value = struct.unpack_from('>I', d, p + 1)[0]
                p += 5
                if field_value & 0x80000000:
                    sz = field_value & 0x7FFFFFFF
                    dir_end = p + sz - 4
                    self._tvfs_table(d, h, p, dir_end, file_path)
                    p = dir_end
                else:
                    spans = self._tvfs_spans(d, h, field_value)
                    if len(spans) == 1 and spans[0][2][:9] in self._vfs:
                        sub = self.read_ekey(spans[0][2])
                        self._tvfs_directory(sub, file_path + ':')
                    else:
                        self.file_set[file_path.lower()] = (file_path, spans)
                file_path = base

    def read_data(self, file_path):
        hash_key = file_path.replace('/', '\\').lower()
        ent = self.file_set.get(hash_key)
        if ent is None:
            raise CascError('"%s" is not in the CASC' % file_path)
        if self.is_pack:
            sha = self._objects.get(hash_key)
            try:
                with open(os.path.join(self._store, sha) if sha else pack_file_path(self.game, hash_key), 'rb') as f:
                    return f.read()
            except OSError:
                raise CascError('"%s" is a game file, but the game data pack does not have it' % file_path)
        spans = ent[1]
        if len(spans) == 1:
            return self.read_ekey(spans[0][2])
        sz = max(o + t for o, t, _ in spans)
        buf = bytearray(sz)
        for o, t, ek in spans:
            part = self.read_ekey(ek)
            if len(part) < t:
                raise CascError('"%s": span at %d of %d bytes, the EKey decoded %d' % (file_path, o, t, len(part)))
            buf[o:o + t] = part[:t]
        return bytes(buf)

    def listing(self, default_value):
        pad = default_value.replace('/', '\\').lower()
        return sorted(v[0] for k, v in self.file_set.items() if fnmatch.fnmatchcase(k, pad))

    def wc3_candidates(self, game_path, hd=False):
        c = game_path.replace('/', '\\').lstrip('\\').lower()
        if c.endswith('.mdl'):
            c = c[:-4] + '.mdx'
        order = []
        if hd:
            order.append('war3.w3mod:_hd.w3mod:' + c)
        order.append('war3.w3mod:' + c)
        return order

    def resolve(self, game_path, hd=False):
        for cand in self.wc3_candidates(game_path, hd):
            if cand in self.file_set:
                return self.file_set[cand][0]
        return None

    def read_wc3(self, game_path, hd=False):
        cpath = self.resolve(game_path, hd)
        if cpath is None:
            raise CascError('the game does not have "%s" (%s)' % (game_path, 'HD' if hd else 'SD'))
        return self.read_data(cpath)

    def on_close(self):
        for f in self._open_files.values():
            f.close()
        self._open_files = {}

