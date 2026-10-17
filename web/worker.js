// The Web Worker: Pyodide with the protection engine.
import { loadPyodide } from './pyodide/pyodide.mjs';
import { runWasi } from './wasi_mini.js';
import { windowsRules } from './fs_windows.js';
import { mpqNative } from './mpqcrypt.js';

const APP = '/home/pyodide/app';
let py = null;
let mod = null;
let mounts = 0;
let queue = Promise.resolve();

function post(msg, transfer) { self.postMessage(msg, transfer || []); }

async function boot() {
  post({ type: 'boot', label: 'Loading Python...' });
  py = await loadPyodide({ indexURL: new URL('pyodide/', import.meta.url).href, stdout: () => {}, stderr: () => {} });
  windowsRules(py.FS);
  post({ type: 'boot', label: 'Loading numpy and Pillow...' });
  await py.loadPackage(['numpy', 'pillow'], { messageCallback: () => {} });
  post({ type: 'boot', label: 'Loading the protector...' });
  const r = await fetch('engine.zip');
  if (!r.ok) throw new Error('engine.zip: ' + r.status);
  py.unpackArchive(await r.arrayBuffer(), 'zip', { extractDir: APP });
  const pj = await fetch('pjass.wasm');
  if (pj.ok) {
    const wasm = await WebAssembly.compile(await pj.arrayBuffer());
    self.runPjass = (args, files) => runWasi(wasm, Array.from(args), files);
  }
  const mc = await fetch('mpqcrypt.wasm');
  if (mc.ok) {
    const native = mpqNative(await mc.arrayBuffer());
    self.mpqDecrypt = native.decrypt;
    if (native.keys) self.mpqKeys = native.keys;
    if (native.huffman) self.mpqHuffman = native.huffman;
    if (native.adpcm) self.mpqAdpcm = native.adpcm;
    if (native.explode) self.mpqExplode = native.explode;
    if (native.encrypt) self.mpqEncrypt = native.encrypt;
    if (native.jpegScan) { self.jpegScan = native.jpegScan; self.jpegWrite = native.jpegWrite; }
  }
  for (const d of ['/maps', '/in', '/out']) py.FS.mkdirTree(d);
  py.FS.writeFile('/home/pyodide/protect_worker.py', await (await fetch('worker.py')).text());
  py.runPython('import sys; sys.path.insert(0, "/home/pyodide")');
  mod = py.pyimport('protect_worker');
  post({ type: 'ready' });
}

function addFile(path, file) {
  const dir = '/in/' + (mounts++);
  py.FS.mkdirTree(dir);
  py.FS.mount(py.FS.filesystems.WORKERFS, { files: [file] }, dir);
  try { py.FS.unlink(path); } catch (e) { }
  py.FS.mkdirTree(path.slice(0, path.lastIndexOf('/')) || '/');
  py.FS.symlink(dir + '/' + file.name, path);
}

function readFile(rid, path) {
  try {
    let p = path;
    if (py.FS.isDir(py.FS.stat(path).mode)) {
      p = '/out/' + path.split('/').filter(Boolean).pop() + '.zip';
      mod.zip_folder(path, p);
    }
    const bytes = py.FS.readFile(p);
    post({ type: 'reply', rid, name: p.split('/').pop(), bytes }, [bytes.buffer]);
  } catch (e) {
    post({ type: 'reply', rid, error: String(e && e.message || e) });
  }
}

const booted = boot().catch(e => { post({ type: 'boot_failed', message: String(e && e.message || e) }); throw e; });

self.onmessage = ev => {
  const m = ev.data;
  queue = queue.then(() => booted).then(() => {
    if (m.type === 'hello') post({ type: 'reply', rid: m.rid, hello: mod.hello() });
    else if (m.type === 'file') addFile(m.path, m.file);
    else if (m.type === 'read') readFile(m.rid, m.path);
    else if (m.type === 'delete') {
      try { py.FS.unlink(m.path); } catch (e) { }
      post({ type: 'reply', rid: m.rid });
    } else if (m.type === 'job') mod.run(JSON.stringify(m.job), s => post({ type: 'event', event: s }));
  }).catch(e => {
    if (m.type === 'job' && m.job && m.job.id) post({ type: 'event', event: JSON.stringify({
      type: 'error', job: m.job.id, message: 'The engine stopped: ' + String(e && e.message || e) }) });
    else if (m.rid) post({ type: 'reply', rid: m.rid, error: String(e && e.message || e) });
  });
};
