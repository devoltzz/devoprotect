// The sector codec of the 512-byte pack in WebAssembly (setor512.wasm), for the browser.
export function s512Native(wasmBytes) {
  const mod = new WebAssembly.Module(wasmBytes);
  const imports = {};
  for (const { module, name } of WebAssembly.Module.imports(mod)) {
    imports[module] ??= {};
    imports[module][name] = name === 'proc_exit' ? (code) => { throw new Error('setor512: exit ' + code); } : () => 52;
  }
  const exp = new WebAssembly.Instance(mod, imports).exports;
  if (exp._initialize) exp._initialize();
  return (data, sector, margin, mode) => {
    const n = Math.ceil(data.length / sector);
    if (!n) return new Uint8Array(0);
    const pl = (2 * data.length + 3) & ~3;
    const ptr = exp.s512_buffer(pl + 4 * n);
    if (!ptr) return undefined;
    new Uint8Array(exp.memory.buffer, ptr, data.length).set(data);
    const k = exp.s512_fatia(ptr, data.length, sector, margin, mode, ptr + data.length, ptr + pl);
    if (k !== n) return undefined;
    const lens = new Uint32Array(exp.memory.buffer, ptr + pl, n);
    let total = 0;
    for (let i = 0; i < n; i++) total += lens[i];
    const out = new Uint8Array(4 * n + total);
    out.set(new Uint8Array(exp.memory.buffer, ptr + pl, 4 * n), 0);
    out.set(new Uint8Array(exp.memory.buffer, ptr + data.length, total), 4 * n);
    return out;
  };
}
