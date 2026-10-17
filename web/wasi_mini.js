// The WASI calls pjass.wasm imports, over files held in memory.
const ERRNO = { SUCCESS: 0, BADF: 8, INVAL: 28, NOENT: 44, NOTCAPABLE: 76 };
const FILETYPE = { CHAR: 2, DIR: 3, FILE: 4 };
const ALL_RIGHTS = 0xFFFFFFFFFFFFFFFFn;
const PREOPEN = 3;

class Exit {
  constructor(code) { this.code = code; }
}

export function runWasi(module, args, files) {
  const enc = new TextEncoder();
  const argv = ['pjass', ...args].map(a => enc.encode(a + '\0'));
  const table = new Map();
  for (const [p, b] of Object.entries(files)) table.set(p.replace(/^\/+/, ''), b);
  const fds = new Map();
  let next = PREOPEN + 1;
  const out = { 1: [], 2: [] };
  let mem = null;
  const view = () => new DataView(mem.buffer);
  const bytes = () => new Uint8Array(mem.buffer);

  const wasi = {
    args_sizes_get(argcPtr, sizePtr) {
      view().setUint32(argcPtr, argv.length, true);
      view().setUint32(sizePtr, argv.reduce((n, a) => n + a.length, 0), true);
      return ERRNO.SUCCESS;
    },
    args_get(argvPtr, bufPtr) {
      let p = bufPtr;
      argv.forEach((a, i) => {
        view().setUint32(argvPtr + 4 * i, p, true);
        bytes().set(a, p);
        p += a.length;
      });
      return ERRNO.SUCCESS;
    },
    fd_prestat_get(fd, ptr) {
      if (fd !== PREOPEN) return ERRNO.BADF;
      view().setUint8(ptr, 0);
      view().setUint32(ptr + 4, 1, true);
      return ERRNO.SUCCESS;
    },
    fd_prestat_dir_name(fd, ptr, len) {
      if (fd !== PREOPEN) return ERRNO.BADF;
      bytes().set(enc.encode('/').subarray(0, len), ptr);
      return ERRNO.SUCCESS;
    },
    fd_fdstat_get(fd, ptr) {
      const type = fd <= 2 ? FILETYPE.CHAR : fd === PREOPEN ? FILETYPE.DIR : fds.has(fd) ? FILETYPE.FILE : 0;
      if (!type) return ERRNO.BADF;
      const v = view();
      v.setUint8(ptr, type);
      v.setUint16(ptr + 2, 0, true);
      v.setBigUint64(ptr + 8, ALL_RIGHTS, true);
      v.setBigUint64(ptr + 16, ALL_RIGHTS, true);
      return ERRNO.SUCCESS;
    },
    fd_fdstat_set_flags() { return ERRNO.SUCCESS; },
    path_open(dirfd, _dirflags, pathPtr, pathLen, oflags, _rb, _ri, _fdflags, fdPtr) {
      if (dirfd !== PREOPEN) return ERRNO.BADF;
      if (oflags & 1) return ERRNO.NOTCAPABLE;
      const path = new TextDecoder().decode(bytes().subarray(pathPtr, pathPtr + pathLen)).replace(/^\.\//, '');
      const data = table.get(path);
      if (!data) return ERRNO.NOENT;
      const fd = next++;
      fds.set(fd, { data, pos: 0 });
      view().setUint32(fdPtr, fd, true);
      return ERRNO.SUCCESS;
    },
    fd_read(fd, iovs, iovsLen, nreadPtr) {
      const f = fds.get(fd);
      if (!f && fd !== 0) return ERRNO.BADF;
      let n = 0;
      for (let i = 0; i < iovsLen && f; i++) {
        const ptr = view().getUint32(iovs + 8 * i, true), len = view().getUint32(iovs + 8 * i + 4, true);
        const chunk = f.data.subarray(f.pos, f.pos + len);
        bytes().set(chunk, ptr);
        f.pos += chunk.length;
        n += chunk.length;
        if (chunk.length < len) break;
      }
      view().setUint32(nreadPtr, n, true);
      return ERRNO.SUCCESS;
    },
    fd_seek(fd, offset, whence, newPtr) {
      const f = fds.get(fd);
      if (!f) return ERRNO.BADF;
      const base = whence === 0 ? 0 : whence === 1 ? f.pos : f.data.length;
      const pos = base + Number(offset);
      if (pos < 0) return ERRNO.INVAL;
      f.pos = pos;
      view().setBigUint64(newPtr, BigInt(pos), true);
      return ERRNO.SUCCESS;
    },
    fd_write(fd, iovs, iovsLen, nwrittenPtr) {
      if (fd !== 1 && fd !== 2) return ERRNO.BADF;
      let n = 0;
      for (let i = 0; i < iovsLen; i++) {
        const ptr = view().getUint32(iovs + 8 * i, true), len = view().getUint32(iovs + 8 * i + 4, true);
        out[fd].push(bytes().slice(ptr, ptr + len));
        n += len;
      }
      view().setUint32(nwrittenPtr, n, true);
      return ERRNO.SUCCESS;
    },
    fd_close(fd) { return fds.delete(fd) ? ERRNO.SUCCESS : ERRNO.BADF; },
    proc_exit(code) { throw new Exit(code); },
  };

  const instance = new WebAssembly.Instance(module, { wasi_snapshot_preview1: wasi });
  mem = instance.exports.memory;
  let code = 0;
  try {
    instance.exports._start();
  } catch (e) {
    if (!(e instanceof Exit)) throw e;
    code = e.code;
  }
  const text = parts => new TextDecoder().decode(parts.reduce((acc, b) => {
    const r = new Uint8Array(acc.length + b.length); r.set(acc); r.set(b, acc.length); return r;
  }, new Uint8Array(0)));
  return { code, stdout: text(out[1]), stderr: text(out[2]) };
}
