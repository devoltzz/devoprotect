// The page in the user's language: every text node translated by the language's dictionary.
'use strict';

(function () {
  const D = window.I18N_DATA || { linguas: {}, modelos: [], textos: {} };
  const LANGS = Object.assign({ en: 'English' }, D.linguas);
  const KEY = D.storageKey || 'page.lang';
  const ATTRS = ['title', 'placeholder', 'aria-label'];
  const SKIP = 'pre, code, textarea, script, style, input, [translate="no"], .mono, .cmd';
  const orig = new WeakMap();
  const written = new WeakMap();
  const origAttr = new WeakMap();
  let lang = pick();

  function pick() {
    let saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) { }
    if (saved && LANGS[saved]) return saved;
    for (const l of navigator.languages || [navigator.language || 'en']) {
      const low = String(l).toLowerCase();
      if (/^zh-(tw|hk|mo|hant)\b/.test(low) && LANGS['zh-TW']) return 'zh-TW';
      const code = low.split('-')[0];
      if (LANGS[code]) return code;
    }
    return 'en';
  }

  const escape = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const rxOf = (m, gap) => new RegExp('^' + m.split(/(\{\d+\})/).map(p =>
    /^\{\d+\}$/.test(p) ? gap : escape(p)).join('') + '$');
  const AND = '{0} and {1}';
  const RX_LIST = /^((?:[^\s,]+, )*[^\s,]+) and ([^\s,]+)$/;
  const NAME = /[._\\\/0-9]|[a-z][A-Z]|^[A-Z0-9]{3,}$/;
  const RX = (D.modelos || []).filter(m => m !== AND).map(m => {
    const fixed = m.split(/\{\d+\}/);
    return [rxOf(m, '([\\s\\S]*?)'), m, fixed.join('').length,
      fixed.reduce((a, b) => (b.length > a.length ? b : a), ''), (fixed.join('').match(/[A-Za-z]/g) || []).length,
      /\{\d+\}[^A-Za-z]*\{\d+\}/.test(m) ? rxOf(m, '([\\s\\S]*)') : null];
  }).sort((a, b) => b[2] - a[2]);
  const WORDS = /[A-Za-z]{2,}\s+[A-Za-z]{2,}/;
  const COUNTS = /^(.*?[A-Za-z].*?)((?:\s*\(\d+\))+)$/;
  const BARE = /^[A-Za-z ]*(\{\d+\}[A-Za-z ]*)+$/;
  const LEAD = /^[\s\-*•·>]*/;

  function line(s, depth) {
    const dict = D.textos[lang];
    if (!dict) return s;
    const whole = s.trim();
    if (whole && dict[whole]) return s.slice(0, s.indexOf(whole)) + dict[whole] + s.slice(s.indexOf(whole) + whole.length);
    const lead = s.match(LEAD)[0];
    const core = s.slice(lead.length).trim();
    if (!core || !/[A-Za-z]/.test(core)) return s;
    const trail = s.slice(lead.length + s.slice(lead.length).indexOf(core) + core.length);
    const mid = s.slice(lead.length, lead.length + s.slice(lead.length).indexOf(core));
    if (dict[core]) return lead + mid + dict[core] + trail;
    const counted = core.match(COUNTS);
    if (counted && !(depth > 0)) {
      const t = line(counted[1], 1);
      if (t !== counted[1]) return lead + mid + t + counted[2] + trail;
    }
    let overall = null;
    for (const [rx, m, , piece, letters, greedy] of RX) {
      if (!dict[m] || (piece && core.indexOf(piece) < 0)) continue;
      let best = null;
      for (const r of greedy ? [rx, greedy] : [rx]) {
        const g = core.match(r);
        if (!g) continue;
        const gaps = g.slice(1);
        if (letters < 12 && BARE.test(m) && gaps.some(v => WORDS.test(v) && !dict[v.trim()])) continue;
        let left = 0;
        const done = gaps.map(v => {
          const t = gap(v, depth);
          if (t === v && /[A-Za-z]{3,}/.test(v) && !/[._\\\/0-9]|[a-z][A-Z]/.test(v.trim())) left++;
          return t;
        });
        if (!best || left < best[1]) best = [done, left];
        if (!left) break;
      }
      if (!best) continue;
      const out = lead + mid + dict[m].replace(/\{(\d+)\}/g, (_x, i) => best[0][+i] || '') + trail;
      if (!best[1]) return out;
      if (!overall || best[1] < overall[1]) overall = [out, best[1]];
    }
    return overall ? overall[0] : s;
  }

  function gap(v, depth) {
    const dict = D.textos[lang];
    const t = v.trim();
    if (!t) return v;
    const pre = v.slice(0, v.indexOf(t)), post = v.slice(v.indexOf(t) + t.length);
    if (dict[t]) return pre + dict[t] + post;
    const list = t.match(RX_LIST);
    if (list && dict[AND] && (list[1] + ', ' + list[2]).split(', ').every(x => NAME.test(x)))
      return pre + dict[AND].replace('{0}', list[1]).replace('{1}', list[2]) + post;
    if ((depth || 0) < 1 && /[A-Za-z]{2,}/.test(t)) {
      const x = line(t, (depth || 0) + 1);
      if (x !== t) return pre + x + post;
    }
    return v;
  }
  const tr = s => (s.indexOf('\n') >= 0 ? s.split('\n').map(x => line(x)).join('\n') : line(s));

  function skipped(node) {
    const p = node.nodeType === 1 ? node : node.parentElement;
    return !p || !!p.closest(SKIP);
  }

  function doText(node) {
    if (skipped(node)) return;
    let o = orig.get(node);
    if (o === undefined || node.data !== written.get(node)) {
      o = node.data;
      orig.set(node, o);
    }
    const out = lang === 'en' ? o : tr(o);
    if (node.data !== out) node.data = out;
    written.set(node, out);
  }

  function doAttrs(el) {
    if (skipped(el)) return;
    let o = origAttr.get(el);
    if (!o) { o = {}; origAttr.set(el, o); }
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      const v = el.getAttribute(a);
      if (o[a] === undefined || v !== o['=' + a]) o[a] = v;
      const out = lang === 'en' ? o[a] : tr(o[a]);
      o['=' + a] = out;
      if (v !== out) el.setAttribute(a, out);
    }
  }

  function walk(root) {
    if (!root) return;
    if (root.nodeType === 3) { doText(root); return; }
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) doAttrs(root);
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (n.nodeType === 3) doText(n);
      else doAttrs(n);
    }
  }

  const observer = new MutationObserver(list => {
    for (const m of list) {
      if (m.type === 'characterData') doText(m.target);
      else if (m.type === 'attributes') doAttrs(m.target);
      else m.addedNodes.forEach(walk);
    }
  });

  const loading = {};
  function load(code) {
    if (code === 'en' || D.textos[code]) return Promise.resolve();
    if (!loading[code]) {
      loading[code] = new Promise(resolve => {
        const s = document.createElement('script');
        s.src = 'lang/' + code + '.js';
        s.onload = s.onerror = () => resolve();
        document.head.appendChild(s);
      });
    }
    return loading[code];
  }

  function start() {
    document.documentElement.lang = lang;
    load(lang).then(() => walk(document.body));
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true,
      attributeFilter: ATTRS });
  }

  function setLang(code, quiet) {
    if (!LANGS[code] || code === lang) return;
    lang = code;
    if (!quiet) { try { localStorage.setItem(KEY, code); } catch (e) { } }
    document.documentElement.lang = code;
    load(code).then(() => {
      if (lang !== code) return;
      walk(document.body);
      document.dispatchEvent(new CustomEvent('page-lang', { detail: code }));
    });
  }

  window.pageI18n = { langs: LANGS, get lang() { return lang; }, setLang, tr: s => (lang === 'en' ? s : tr(s)) };
  if (document.body) start();
  else document.addEventListener('DOMContentLoaded', start);
})();
