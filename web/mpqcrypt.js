// The MPQ's hot loops in WebAssembly (mpqcrypt.wasm), for the engine in the browser.
export function mpqNative(wasmBytes) {
  const mod = new WebAssembly.Module(wasmBytes);
  const exp = new WebAssembly.Instance(mod, {}).exports;
  const exports = exp;
  const { memory, mpq_buffer: buffer, mpq_decrypt, mpq_key_candidates, mpq_huffman, mpq_adpcm, mpq_explode } = exp;
  const copyIn = (data, extra) => {
    const ptr = buffer(data.length + extra);
    new Uint8Array(memory.buffer, ptr, data.length).set(data);
    return ptr;
  };
  const decrypt = (data, key) => {
    const ptr = copyIn(data, 0);
    mpq_decrypt(ptr, data.length, key);
    return new Uint8Array(memory.buffer, ptr, data.length).slice();
  };
  const encrypt = (data, key) => {
    const ptr = copyIn(data, 0);
    exp.mpq_encrypt(ptr, data.length, key);
    return new Uint8Array(memory.buffer, ptr, data.length).slice();
  };
  const keys = (enc0, enc1, d0) => {
    const ptr = buffer(2048);
    const n = mpq_key_candidates(enc0, enc1, d0, ptr);
    return new Uint32Array(memory.buffer, ptr, 2 * n).slice();
  };
  const output = (ptr, length, n) => (n < 0 ? undefined : new Uint8Array(memory.buffer, ptr + length, n).slice());
  const huffman = (data, cap) => {
    const ptr = copyIn(data, cap);
    return output(ptr, data.length, mpq_huffman(ptr, data.length, ptr + data.length, cap));
  };
  const adpcm = (data, channels, cap) => {
    const ptr = copyIn(data, cap);
    return output(ptr, data.length, mpq_adpcm(ptr, data.length, channels, ptr + data.length, cap));
  };
  const explode = (data, expected) => {
    const ptr = copyIn(data, expected);
    return output(ptr, data.length, mpq_explode(ptr, data.length, ptr + data.length, expected));
  };
  const { jpeg_huff_scan, jpeg_huff_write } = exports;
  const align = (x) => (x + 3) & ~3;
  const jpegScan = (data, ent, nmcu, dri, spec, tabs, cap) => {
    let ntab = 0;
    for (let q = 0; q + 18 <= tabs.length; q += 18 + (tabs[q + 16] | (tabs[q + 17] << 8))) ntab++;
    const ps = data.length, pt = ps + spec.length, po = align(pt + tabs.length);
    const ptr = buffer(po + 4 * cap);
    const mem = new Uint8Array(memory.buffer);
    mem.set(data, ptr);
    mem.set(spec, ptr + ps);
    mem.set(tabs, ptr + pt);
    const n = jpeg_huff_scan(ptr, data.length, ent, nmcu, dri, ptr + ps, spec.length, ptr + pt, tabs.length, ptr + po,
      cap);
    return n < 0 ? undefined : new Uint8Array(memory.buffer, ptr + po, 4 * (2 + 256 * ntab + n)).slice();
  };
  const jpegWrite = (recs, codes, ac, ntab, cap) => {
    const pc = align(recs.length), pa = pc + codes.length, po = pa + ac.length;
    const ptr = buffer(po + cap);
    const mem = new Uint8Array(memory.buffer);
    mem.set(recs, ptr);
    mem.set(codes, ptr + pc);
    mem.set(ac, ptr + pa);
    const n = jpeg_huff_write(ptr, recs.length / 4, ptr + pc, ptr + pa, ntab, ptr + po, cap);
    return n < 0 ? undefined : new Uint8Array(memory.buffer, ptr + po, n).slice();
  };
  return { decrypt, keys: mpq_key_candidates ? keys : null, huffman: mpq_huffman ? huffman : null,
    adpcm: mpq_adpcm ? adpcm : null, explode: mpq_explode ? explode : null,
    encrypt: exp.mpq_encrypt ? encrypt : null,
    jpegScan: jpeg_huff_scan ? jpegScan : null, jpegWrite: jpeg_huff_write ? jpegWrite : null };
}
