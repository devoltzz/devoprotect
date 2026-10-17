// Runs pjass.wasm against pjass's own tests through the site's WASI.
import fs from 'node:fs';
import path from 'node:path';
import { runWasi } from './wasi_mini.js';

const [wasm, src] = process.argv.slice(2);
if (!wasm || !src) {
  console.error('usage: node web/check_pjass.mjs <pjass.wasm> <pjass source>');
  process.exit(2);
}
const mod = await WebAssembly.compile(fs.readFileSync(wasm));
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(d => d.isDirectory() ? walk(path.join(dir, d.name)) :
    d.name.endsWith('.j') ? [path.join(dir, d.name)] : []);
}
let bad = 0, n = 0;
for (const [kind, want] of [['should-check', 0], ['should-fail', 1]]) {
  for (const f of walk(path.join(src, 'tests', kind))) {
    const rel = path.relative(src, f).split(path.sep).join('/');
    const r = runWasi(mod, [rel], { [rel]: new Uint8Array(fs.readFileSync(f)) });
    n++;
    if ((r.code === 0 ? 0 : 1) !== want) {
      bad++;
      console.log('WRONG ' + rel + ' (exit ' + r.code + ')\n' + r.stdout + r.stderr);
    }
  }
}
console.log(n + ' pjass tests, ' + bad + ' wrong');
process.exit(bad ? 1 : 0);
