// The window in the browser: the API the page calls, answered by the Web Worker.
'use strict';

(function () {
  const CFG = window.DEVOPROTECT_WEB || {};
  const worker = new Worker('worker.js', { type: 'module' });
  const pending = {};
  let rid = 0;
  let readyDone, readyFail;
  const ready = new Promise((res, rej) => { readyDone = res; readyFail = rej; });
  ready.catch(() => {});

  function status(text) {
    const el = document.getElementById('summary');
    if (el) el.textContent = text;
  }

  function call(msg) {
    return new Promise((res, rej) => {
      const id = ++rid;
      pending[id] = { res, rej };
      worker.postMessage(Object.assign({ rid: id }, msg));
    });
  }

  function download(name, bytes) {
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }

  async function fetchResults(ev) {
    for (const path of [ev.out, ev.key].filter(Boolean)) {
      try {
        const r = await call({ type: 'read', path });
        download(r.name, r.bytes);
        await call({ type: 'delete', path });
      } catch (e) {
        status('Could not save ' + path.split('/').pop() + ': ' + (e && e.message ? e.message : e));
      }
    }
  }

  worker.onmessage = msg => {
    const m = msg.data;
    if (m.type === 'boot') status(m.label);
    else if (m.type === 'ready') { status(''); readyDone(); }
    else if (m.type === 'boot_failed') {
      status('The protector did not load: ' + m.message);
      readyFail(new Error(m.message));
    } else if (m.type === 'reply') {
      const p = pending[m.rid];
      delete pending[m.rid];
      if (p) { if (m.error) p.rej(new Error(m.error)); else p.res(m); }
    } else if (m.type === 'event') {
      let ev = null;
      try { ev = JSON.parse(m.event); } catch (e) { ev = null; }
      const sub = ev && subjobs[ev.job];
      if (sub) {
        if (ev.type === 'progress') sub.send(ev);
        else sub.done(ev);
        return;
      }
      if (window.onJob) window.onJob(m.event);
      if (ev && ev.type === 'result' && ev.ok) fetchResults(ev);
    }
  };

  const subjobs = {};
  const sizes = {};
  let batches = 0;

  async function runBatch(id, params) {
    const send = ev => { if (window.onJob) window.onJob(JSON.stringify(Object.assign({}, ev, { job: id }))); };
    const maps = [];
    for (let i = 0; i < params.maps.length; i++) {
      const name = params.maps[i];
      const path = params.folder + '/' + name;
      send({ type: 'progress', step: 'map', text: 'Map ' + (i + 1) + ' of ' + params.maps.length + ': ' + name });
      const sub = id + '_' + i;
      const ev = await new Promise(done => {
        subjobs[sub] = { send, done };
        worker.postMessage({ type: 'job', job: { id: sub, map: path, out: params.out + '/' + protectedName(name),
                                                 options: params.options } });
      });
      delete subjobs[sub];
      const ok = ev.type === 'result' && !!ev.ok;
      if (ok) await fetchResults(ev);
      maps.push({ name, ok, out: ok ? ev.out : null, key: ok ? ev.key || null : null, seconds: ev.seconds || null,
                  bytes_in: ev.bytes_in || sizes[path] || 0, bytes_out: ok ? ev.bytes_out : null,
                  reason: ok ? null : (ev.type === 'error' ? ev.message : ev.summary) || 'failed' });
    }
    const r = await call({ type: 'py', fn: 'folder_report', arg: JSON.stringify({ maps, out: params.out }) });
    send(Object.assign(JSON.parse(r.text), { type: 'result' }));
  }

  function pickFiles(accept, folder, multiple) {
    return new Promise(res => {
      const input = document.createElement('input');
      input.type = 'file';
      if (accept) input.accept = accept;
      if (multiple) input.multiple = true;
      if (folder) { input.webkitdirectory = true; input.multiple = true; }
      input.addEventListener('change', () => res(input.files && input.files.length ? Array.from(input.files) : null));
      input.addEventListener('cancel', () => res(null));
      input.click();
    });
  }

  function baseName(p) { return String(p).split(/[\\/]/).pop(); }
  function protectedName(p) { return baseName(p).replace(/(\.[^.]+)?$/, ext => '_protected' + (ext || '')); }

  window._fakeApi = {
    hello: async () => {
      await ready;
      const h = JSON.parse((await call({ type: 'hello' })).hello);
      return { version: CFG.version || '', app: h.app, map: null, options: h.options, tables: h.tables };
    },
    pick_map: async () => {
      const files = await pickFiles('.w3x,.w3m,.w3n');
      if (!files) return null;
      const f = files[0];
      if (CFG.sizeLimit && f.size > CFG.sizeLimit) {
        status('This map is too big for the browser (' + Math.round(f.size / 1048576) + ' MB): use the program.');
        return null;
      }
      await ready;
      worker.postMessage({ type: 'file', path: '/maps/' + f.name, file: f });
      return '/maps/' + f.name;
    },
    inspect_map: async path => {
      await ready;
      return JSON.parse((await call({ type: 'py', fn: 'inspect_map', arg: JSON.stringify(path) })).text);
    },
    pick_save: async suggested => '/out/' + baseName(suggested || 'protected.w3x'),
    pick_key: async folder => {
      const files = await pickFiles(folder ? '' : '.tsv', folder);
      if (!files) return null;
      await ready;
      if (!folder) {
        worker.postMessage({ type: 'file', path: '/in/keys/' + files[0].name, file: files[0] });
        return '/in/keys/' + files[0].name;
      }
      const base = '/in/keys/' + ((files[0].webkitRelativePath || '').split('/')[0] || 'keys');
      for (const f of files) {
        worker.postMessage({ type: 'file', path: f.webkitRelativePath ? '/in/keys/' + f.webkitRelativePath : base + '/' + f.name,
                             file: f });
      }
      return base;
    },
    pick_folder: async () => {
      const files = await pickFiles('.w3x,.w3m,.w3n', false, true);
      if (!files) return null;
      await ready;
      const folder = '/maps/batch' + (++batches);
      const maps = [];
      for (const f of files) {
        if (!/\.(w3x|w3m|w3n)$/i.test(f.name)) continue;
        if (CFG.sizeLimit && f.size > CFG.sizeLimit) {
          status('Left out, too big for the browser (' + Math.round(f.size / 1048576) + ' MB): ' + f.name);
          continue;
        }
        worker.postMessage({ type: 'file', path: folder + '/' + f.name, file: f });
        sizes[folder + '/' + f.name] = f.size;
        maps.push(f.name);
      }
      return { folder, maps, out: '/out/batch' + batches };
    },
    pick_out_folder: async () => null,
    save_preset: async options => {
      await ready;
      const r = await call({ type: 'py', fn: 'preset_text', arg: JSON.stringify(options) });
      download('devoprotect_preset.json', new TextEncoder().encode(r.text));
      return 'devoprotect_preset.json';
    },
    load_preset: async () => {
      const files = await pickFiles('.json');
      if (!files) return null;
      await ready;
      const r = JSON.parse((await call({ type: 'py', fn: 'preset_read', arg: JSON.stringify(await files[0].text()) })).text);
      return r.error ? { error: r.error } : { options: r.options, warnings: r.warnings, name: files[0].name };
    },
    start: async params => {
      await ready;
      if (params.folder) {
        const batch = 'job' + (++rid);
        runBatch(batch, params);
        return batch;
      }
      const id = 'job' + (++rid);
      const out = params.out || '/out/' + protectedName(params.map);
      worker.postMessage({ type: 'job', job: { id, map: params.map, out, options: params.options } });
      return id;
    },
  };

  document.addEventListener('DOMContentLoaded', () => {
    const change = document.getElementById('pickout');
    if (change) change.hidden = true;
    const wrap = document.querySelector('.wrap');
    if (wrap) {
      const note = document.createElement('p');
      note.className = 'hint';
      note.textContent = 'Everything runs in your browser: your map is never uploaded.';
      wrap.appendChild(note);
    }
  });
})();
