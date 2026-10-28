(function () {
  'use strict';

  const MEDIA = 'https://media.juicewrldvault.com';
  const SITE = 'https://juicewrldvault.com';

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'class') el.className = v;
        else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
        else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k === 'html') el.innerHTML = v;
        else if (k === 'dataset') Object.assign(el.dataset, v);
        else if (v === true) el.setAttribute(k, '');
        else el.setAttribute(k, v);
      }
    }
    for (const c of children.flat(Infinity)) {
      if (c === null || c === undefined || c === false) continue;
      el.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
    }
    return el;
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function fmtTime(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    sec = Math.floor(sec);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
  }

  function fmtLong(sec) {
    sec = Math.round(sec || 0);
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    if (h) return `${h} hr ${m} min`;
    return `${m} min`;
  }

  function fmtInt(n) { return (n || 0).toLocaleString('en-US'); }

  function fmtDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return String(iso);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  }

  function fmtRelative(iso) {
    const d = new Date(iso); if (isNaN(d)) return '';
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} hr ago`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} d ago`;
    return fmtDate(iso);
  }

  function fmtBytes(n) {
    if (!n) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB']; let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
  }

  function debounce(fn, ms) {
    let t; return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
  }
  function throttle(fn, ms) {
    let last = 0, t; return function (...a) {
      const now = Date.now();
      if (now - last >= ms) { last = now; fn.apply(this, a); }
      else { clearTimeout(t); t = setTimeout(() => { last = Date.now(); fn.apply(this, a); }, ms - (now - last)); }
    };
  }

  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  let isDownloaded = () => false;
  function setDownloadedCheck(fn) { isDownloaded = fn; }
  function audioUrl(song, stream) {
    if (song.local) return `/__local/${Math.abs(song.id)}`;
    if (!stream && song.id > 0 && isDownloaded(song.id)) return `/__dl/${song.id}`;
    const p = song.path || '';
    if (/^https?:\/\//i.test(p)) return p;
    return `${MEDIA}/songs/${p.replace(/^\/+/, '')}`;
  }
  const COVER_KEYWORDS = [
    ['heartbroken', 'Heartbroken In Hollywood 999'], ['hih', 'Heartbroken In Hollywood 999'],
    ['juiced up', 'JUICED UP THE EP'], ['jute', 'JUICED UP THE EP'],
    ['affliction', 'Affliction'],
    ['bingedrinking', 'BINGEDRINKINGMUSIC'], ['bdm', 'BINGEDRINKINGMUSIC'],
    ["nothing's different", "NOTHING'S DIFFERENT </3"], ['nothings different', "NOTHING'S DIFFERENT </3"],
    ['goodbye', 'Goodbye & Good Riddance'], ['gb&gr', 'Goodbye & Good Riddance'], ['gbgr', 'Goodbye & Good Riddance'],
    ['wrld on drugs', 'WRLD On Drugs'], ['wod', 'WRLD On Drugs'],
    ['death race', 'Death Race For Love'], ['drfl', 'Death Race For Love'],
    ['outsiders', 'Outsiders'],
    ['posthumous', 'Posthumous'], ['post', 'Posthumous'],
    ['999', 'Juice WRLD 999'], ['9 9 9', 'Juice WRLD 999'], ['jw 999', 'Juice WRLD 999'],
    ['jw3', 'JW3'], ['juice wrld 3', 'JW3'],
  ];
  function coverEraKey(song) {
    if (!song || song.cat === 'released') return null;
    const m = window.__eraCovers || {};
    if (song.eraKey && m[song.eraKey]) return song.eraKey;
    const raw = String(song.era || '').toLowerCase().trim();
    if (song.local) {
      const hay = `${raw} ${song.title || ''} ${song.path || ''}`.toLowerCase().replace(/[_\-]+/g, ' ');
      for (const [kw, key] of COVER_KEYWORDS) {
        const hit = kw.length <= 4 ? new RegExp(`(^|[^a-z0-9])${kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z0-9]|$)`).test(hay) : hay.includes(kw);
        if (hit && m[key]) return key;
      }
      return null;
    }
    if (!raw) return null;
    for (const [kw, key] of COVER_KEYWORDS) {
      const hit = kw.length <= 4 ? raw === kw || raw.startsWith(kw + ' ') || raw.startsWith(kw + '(') : raw.includes(kw);
      if (hit && m[key]) return key;
    }
    return null;
  }
  function localCover(song) {
    const k = coverEraKey(song);
    return k ? window.__eraCovers[k] : null;
  }
  function remoteImageUrl(song) {
    if (song && song.local) return song.localArt ? `/__localart/${Math.abs(song.id)}` : null;
    const p = song && song.img;
    if (!p) return null;
    if (/^https?:\/\//i.test(p)) return p;
    const c = p.replace(/^\/+/, '');
    const pref = /^(images|playlist-covers|liked-songs)\//.test(c) ? c : `images/${c}`;
    return `${MEDIA}/${pref}`;
  }
  function imageUrl(song) { return localCover(song) || remoteImageUrl(song); }
  const THUMB_SIZES = [64, 96, 128, 256, 384, 640, 750, 1080];
  function coverUrl(song, w) {
    const local = localCover(song);
    if (local) return local;
    const full = remoteImageUrl(song);
    if (!full) return null;
    if (!window.__thumbs || song.local) return full;
    const size = THUMB_SIZES.find((s) => s >= (w || 96)) || 1080;
    return `${SITE}/_next/image?url=${encodeURIComponent(full)}&w=${size}&q=75`;
  }
  function ext(song) { const m = /\.([a-z0-9]{2,5})(\?|$)/i.exec(song.path || ''); return m ? m[1].toLowerCase() : 'mp3'; }

  const VERSION_RE = /^\(?v\d+(?:\.\d+)*\)?$/i;
  function parseTitle(title) {
    let name = String(title || '').trim();
    const tags = [];
    name = name.replace(/\[([^\]]+)\]/g, (_, t) => { tags.push(t.trim()); return ' '; });
    name = name.replace(/\((v\d+(?:\.\d+)*)\)/gi, (_, t) => { tags.push(t.toLowerCase()); return ' '; });
    name = name.replace(/\s{2,}/g, ' ').replace(/\s+([,)])/g, '$1').trim();
    if (!name) name = String(title || '').trim();
    return { name, tags };
  }

  const ERA_ALIASES = {
    'gb&gr': 'Goodbye & Good Riddance', 'gb&gr (5yae)': 'Goodbye & Good Riddance', 'gb&gr (ae)': 'Goodbye & Good Riddance',
    'goodbye & good riddance': 'Goodbye & Good Riddance',
    'drfl': 'Death Race For Love', 'drfl (tv)': 'Death Race For Love', 'death race for love': 'Death Race For Love',
    'wod': 'WRLD On Drugs', 'wrld on drugs': 'WRLD On Drugs',
    'lnd': 'Legends Never Die', 'lnd (eov)': 'Legends Never Die', 'lnd (5yae)': 'Legends Never Die',
    'legends never die': 'Legends Never Die', 'legends never die (5 year anniversary edition)': 'Legends Never Die',
    'fd': 'Fighting Demons', 'fd (dde)': 'Fighting Demons', 'fd (ce)': 'Fighting Demons', 'fighting demons': 'Fighting Demons',
    'tpne': 'The Party Never Ends', 'the party never ends': 'The Party Never Ends',
    'tpp': 'The Pre-Party', 'tpp (ee)': 'The Pre-Party',
    'post': 'Posthumous', 'posthumous': 'Posthumous',
    'nd': "NOTHING'S DIFFERENT </3", "nothing's different </3": "NOTHING'S DIFFERENT </3",
    'jute': 'JUICED UP THE EP', 'juiced up the ep': 'JUICED UP THE EP',
    'jw 999': 'Juice WRLD 999', 'juice wrld 999': 'Juice WRLD 999',
    'hih 999': 'Heartbroken In Hollywood 999', 'heartbroken in hollywood 999': 'Heartbroken In Hollywood 999',
    'bdm': 'BINGEDRINKINGMUSIC', 'bingedrinkingmusic': 'BINGEDRINKINGMUSIC',
    'outsiders': 'Outsiders',
    'jw3': 'JW3', 'jw3 (sessions)': 'JW3', 'juice wrld 3': 'JW3',
  };
  const ERA_ORDER = [
    'Juice WRLD 999', 'JUICED UP THE EP', 'Heartbroken In Hollywood 999', "NOTHING'S DIFFERENT </3", 'Mainstream', 'SoundCloud',
    'Goodbye & Good Riddance', 'WRLD On Drugs', 'Death Race For Love', 'Outsiders', 'Posthumous',
    'Legends Never Die', 'Fighting Demons', 'The Pre-Party', 'The Party Never Ends',
  ];
  const ERA_YEARS = {
    'Juice WRLD 999': '2015–16', 'JUICED UP THE EP': '2016', 'Heartbroken In Hollywood 999': '2017', "NOTHING'S DIFFERENT </3": '2017',
    'Goodbye & Good Riddance': '2018', 'WRLD On Drugs': '2018', 'Death Race For Love': '2019', 'Outsiders': '2019',
    'Posthumous': '2020+', 'Legends Never Die': '2020', 'Fighting Demons': '2021', 'The Pre-Party': '2024', 'The Party Never Ends': '2024',
  };
  function canonEra(raw) {
    if (!raw) return null;
    const k = String(raw).trim().toLowerCase();
    return ERA_ALIASES[k] || String(raw).trim();
  }
  function eraSortKey(name) {
    const i = ERA_ORDER.indexOf(name);
    return i === -1 ? 1000 : i;
  }

  const CATS = [
    { key: 'all', name: 'all music', icon: 'disc', blurb: 'every track in the vault' },
    { key: 'unreleased', name: 'unreleased', icon: 'lock', blurb: 'unheard snippets, demos and full tracks' },
    { key: 'released', name: 'released', icon: 'album', blurb: 'official releases, singles and features' },
    { key: 'sessions', name: 'studio sessions', icon: 'mic', blurb: 'raw studio takes and session recordings' },
    { key: 'stems', name: 'stems', icon: 'layers', blurb: 'isolated vocals, instrumentals and multitracks' },
    { key: 'remasters', name: 'remasters', icon: 'sparkles', blurb: 'cleaned, remastered and restored audio' },
    { key: 'misc', name: 'miscellaneous', icon: 'grid', blurb: 'masters, instrumentals, freestyles and more' },
  ];
  const CAT_BY_KEY = Object.fromEntries(CATS.map((c) => [c.key, c]));
  function catName(key) { return (CAT_BY_KEY[key] || CAT_BY_KEY.misc).name; }

  const SUB_LABEL = { masters: 'master', instrumental: 'instrumental', stem: 'stem edit', raw: 'raw', session_edit: 'session edit', freestyles: 'freestyle', acapellas: 'acapella' };

  function songChips(song) {
    const chips = [];
    const { tags } = parseTitle(song.title);
    const seen = new Set();
    for (const t of tags) {
      const k = t.toLowerCase();
      if (seen.has(k)) continue; seen.add(k);
      chips.push(t);
    }
    const sub = song.sub && SUB_LABEL[song.sub];
    if (sub && !seen.has(sub.toLowerCase()) && !tags.some((t) => t.toLowerCase().includes(sub.toLowerCase().split(' ')[0]))) chips.unshift(sub);
    return chips.slice(0, 3);
  }

  const _alnum = (s) => String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, ' ').trim();
  function titleFull(t) { return _alnum(String(t || '').replace(/\s*\(\d+\)\s*$/, '').replace(/^\s*juice\s*wrld\s*[-–—]\s*/i, '')); }
  function titleBase(t) {
    let n = parseTitle(String(t || '').replace(/\s*\(\d+\)\s*$/, '').replace(/^\s*juice\s*wrld\s*[-–—]\s*/i, '')).name;
    n = n.replace(/\((?:feat|ft|with|prod)\.?[^)]*\)/gi, ' ').replace(/\s(?:feat|ft)\.?\s.*$/i, ' ').replace(/\([^)]*\)/g, ' ').replace(/\s[-–—]\s.*$/, ' ');
    return _alnum(n);
  }
  function _bigrams(s) { const out = new Map(); const t = ' ' + s + ' '; for (let i = 0; i < t.length - 1; i++) { const b = t.slice(i, i + 2); out.set(b, (out.get(b) || 0) + 1); } return out; }
  function dice(a, b) {
    if (!a || !b) return 0; if (a === b) return 1;
    const A = _bigrams(a), B = _bigrams(b); let inter = 0, na = 0, nb = 0;
    for (const [k, v] of A) { na += v; if (B.has(k)) inter += Math.min(v, B.get(k)); }
    for (const v of B.values()) nb += v;
    return (2 * inter) / (na + nb);
  }
  function lyricsMatch(local, songs) {
    const lf = titleFull(local.title), lb = titleBase(local.title);
    if (!lb) return null;
    const la = _alnum(local.author);
    let best = null, bestScore = 0;
    for (const s of songs) {
      if (!s.lyr || s.id === local.id) continue;
      const sb = s._tb !== undefined ? s._tb : (s._tb = titleBase(s.title));
      if (sb !== lb && Math.abs(sb.length - lb.length) > 10) continue;
      const sf = s._tf !== undefined ? s._tf : (s._tf = titleFull(s.title));
      const d = dice(lf, sf);
      let score;
      if (sb === lb) score = 0.8 + 0.2 * d;
      else { if (d < 0.8) continue; score = d; }
      const dd = local.dur && s.dur ? Math.abs(local.dur - s.dur) : null;
      if (dd !== null) { if (dd <= 3) score += 0.5; else if (dd <= 15) score += 0.15; else if (sb !== lb && dd > 60) continue; }
      if (s.wt) score += 0.05;
      if (s.cat === 'stems' || s.sub === 'stem') score -= 0.3;
      if (la && _alnum(s.author) === la) score += 0.05;
      if (score > bestScore) { bestScore = score; best = s; }
    }
    return bestScore >= 0.8 ? best : null;
  }

  function normalizeQuery(s) { return String(s || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9\s&']/g, ' ').replace(/\s+/g, ' ').trim(); }

  window.U = { $, $$, h, esc, fmtTime, fmtLong, fmtInt, fmtDate, fmtRelative, fmtBytes, debounce, throttle, shuffle, clamp,
    audioUrl, setDownloadedCheck, imageUrl, remoteImageUrl, localCover, coverEraKey, coverUrl, ext, parseTitle, canonEra, eraSortKey, ERA_YEARS, CATS, CAT_BY_KEY, catName, songChips, SUB_LABEL, normalizeQuery, lyricsMatch, titleBase, titleFull, dice, MEDIA, SITE };
})();
