(function () {
  'use strict';
  const { $, $$, h, esc, fmtTime, fmtLong, fmtInt, fmtDate, fmtRelative, fmtBytes, debounce, shuffle, clamp, coverUrl, imageUrl, parseTitle, canonEra, eraSortKey, ERA_YEARS, CATS, CAT_BY_KEY, catName, songChips, normalizeQuery } = U;
  const el = (id) => document.getElementById(id);
  window.__thumbs = true;

  const S = {
    songs: [], byId: new Map(), eras: new Map(), catCounts: {}, fetchedAt: 0, catalogVersion: 0,
    likes: new Set(), likedAt: {}, playlists: [], history: [], playCounts: {}, downloads: {},
    settings: {}, app: {},
    queue: [], qIndex: -1, queueSource: [], shuffle: false, repeat: 'off', ctx: null,
    current: null, playCounted: false, errStreak: 0,
    route: null, stack: [], fwd: [], list: null, listPrefs: {},
    rightTab: 'lyrics', rightOpen: true, npvOpen: false, maximized: false,
    detailCache: new Map(), detailWaiters: new Map(), detailTarget: null, lyParsed: null, lyFor: null,
    dlp: new Map(), q: '', status: null,
  };
  const engine = new Engine();
  let scroller, lyPanel, lyFull, seekSlider, volSlider;

  document.addEventListener('DOMContentLoaded', boot);

  function killTooltips() {
    const strip = (el) => { if (el && el.hasAttribute && el.hasAttribute('title')) el.removeAttribute('title'); };
    const sweep = (root) => { strip(root); if (root && root.querySelectorAll) root.querySelectorAll('[title]').forEach(strip); };
    sweep(document.body);
    new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.type === 'attributes') strip(m.target);
        else for (const n of m.addedNodes) if (n.nodeType === 1) sweep(n);
      }
    }).observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['title'] });
  }

  async function boot() {
    scroller = el('main-scroll');
    buildRefractionMap();
    paintChrome();
    killTooltips();
    bindChrome();
    bindPlayer();
    bindKeyboard();
    Bridge.connect();
    const b = await Bridge.ready;
    wireBridge();
    if (b) Bridge.fire('ready');
    else onInit(JSON.stringify({ app: { name: '999 player', version: 'dev' }, settings: {}, library: {}, catalog: { count: 0 }, maximized: false }));
  }

  function wireBridge() {
    const on = Bridge.bus.on;
    on('init', onInit);
    on('catalogChanged', async (count, version) => { S.catalogVersion = version; await loadCatalog(true); setStatus('ok', `${fmtInt(count)} tracks · synced just now`); });
    on('catalogProgress', (n, t) => setStatus('busy', `syncing ${fmtInt(n)} / ${fmtInt(t)}…`));
    on('catalogError', () => { setStatus(S.songs.length ? 'ok' : 'err', S.songs.length ? `${fmtInt(S.songs.length)} tracks · offline` : 'could not reach the vault'); if (!S.songs.length) { el('splash-st').textContent = 'could not reach the vault. check your connection — retrying…'; setTimeout(() => Bridge.fire('refreshCatalog'), 8000); } });
    on('detail', (id, json) => { let d = null; try { d = JSON.parse(json); } catch (e) {  } S.detailCache.set(id, d); const w = S.detailWaiters.get(id); if (w) { S.detailWaiters.delete(id); w.forEach((r) => r(d)); } });
    on('detailError', (id, msg) => { S.detailCache.set(id, null);  const w = S.detailWaiters.get(id); if (w) { S.detailWaiters.delete(id); w.forEach((r) => r(null)); } Bridge.log('warning', 'detail failed ' + id + ': ' + msg); });
    on('catalogChanged', () => { for (const [k, v] of S.detailCache) if (v === null) S.detailCache.delete(k); });
    on('downloadProgress', (id, got, total) => { S.dlp.set(id, total ? got / total : 0); refreshRow(id); if (S.current && S.current.id === id) paintPlayerDownload(); });
    on('downloadDone', (id, path, ok, err) => { S.dlp.delete(id); refreshRow(id); if (S.current && S.current.id === id) paintPlayerDownload(); const s = S.byId.get(id); if (ok) toast(`saved “${s ? parseTitle(s.title).name : 'track'}” to your music folder`, 'ok'); else toast(`download failed: ${err}`, 'err'); });
    on('downloadsChanged', (json) => { try { S.downloads = JSON.parse(json) || {}; } catch (e) {  } if (S.settings.offlineOnly) { applyCatalog(null, true); } else if (S.route && S.route.name === 'downloads') renderView(S.route, scroller.scrollTop); });
    on('settingChanged', (k, v) => { try { S.settings[k] = JSON.parse(v); } catch (e) { S.settings[k] = v; } if (S.route && S.route.name === 'settings') renderView(S.route, scroller.scrollTop); });
    on('winState', (max) => setMaximized(max));
    on('discordStatus', (s) => { S.discordStatus = s; const n = el('s-dcstatus'); if (n) n.textContent = `status: ${s}`; });
    on('accent', (ref, json) => { if (ref !== S.accentRef) return; try { applyAccent(JSON.parse(json)); } catch (e) {  } });
    on('lastfmStatus', (json) => { try { S.lastfm = JSON.parse(json); } catch (e) { return; } paintLastfm(); });
    on('lyricsStatus', (json) => { try { S.lyricsStore = JSON.parse(json); } catch (e) { return; } paintLyricsStore(); });
    on('localChanged', (json) => { try { applyLocal(JSON.parse(json)); } catch (e) { return; } renderSidebar(); toast(`local files: ${fmtInt(S.local.length)} tracks`, 'ok'); if (S.route && (S.route.name === 'local' || S.route.name === 'settings')) renderView(S.route, scroller.scrollTop); });
    on('mediaKey', (k) => { if (k === 'playpause') togglePlay(); else if (k === 'next') next(); else if (k === 'prev') prev(); else if (k === 'pause' || k === 'stop') engine.pause(); });
    on('toast', (kind, msg) => toast(msg, kind));
    on('updateStatus', (json) => { const prev = S.update || {}; try { S.update = JSON.parse(json); } catch (e) { return; } paintUpdate(prev); });
  }

  async function onInit(json) {
    let p = {}; try { p = JSON.parse(json); } catch (e) {  }
    S.app = p.app || {};
    S.discordStatus = p.discordStatus || 'off';
    S.lastfm = p.lastfm || {};
    S.lyricsStore = p.lyrics || {};
    S.local = [];
    S.pendingLocal = p.local || [];
    S.settings = Object.assign({ volume: 0.8, muted: false, shuffle: false, repeat: 'off', glass: 'full', rightPanel: 'lyrics', rightPanelOpen: true, sidebarCollapsed: false, tagAudio: true, discordEnabled: true, discordClientId: '', offlineOnly: false, autoUpdate: true }, p.settings || {});
    S.update = p.update || { state: 'idle', current: S.app.version };
    paintUpdate();
    applyLibrary(p.library || {});
    S.shuffle = !!S.settings.shuffle; S.repeat = S.settings.repeat || 'off';
    S.rightTab = S.settings.rightPanel === 'none' ? 'lyrics' : (S.settings.rightPanel || 'lyrics');
    S.rightOpen = S.settings.rightPanelOpen !== false;
    document.documentElement.dataset.glass = S.settings.glass || 'full';
    paintOfflineChip();
    el('workspace').classList.toggle('right-closed', !S.rightOpen);
    el('workspace').classList.toggle('sb-collapsed', !!S.settings.sidebarCollapsed);
    applyNavSections();
    engine.setVolume(S.settings.volume ?? 0.8); engine.setMuted(!!S.settings.muted);
    volSlider.set(engine.volume); paintVolume();
    setMaximized(!!p.maximized);
    paintShuffleRepeat();
    renderRight();
    el('splash-st').textContent = (p.catalog && p.catalog.count) ? 'loading your library…' : 'downloading the catalog for the first time…';
    try { const r = await fetch('covers/covers.json', { cache: 'no-store' }); if (r.ok) window.__eraCovers = await r.json(); } catch (e) {  }
    try { const r = await fetch('covers/discord_art.json', { cache: 'no-store' }); if (r.ok) window.__discordArt = await r.json(); } catch (e) {  }
    try { await loadCatalog(false); } catch (e) { Bridge.log('warning', 'catalog not ready: ' + e.message); }
    if (!S.route) go({ name: 'home' }, { replace: true });
    if (S.songs.length) hideSplash();
    if (location.search.includes('selftest')) setTimeout(selftest, 800);
  }

  function hideSplash() { const s = el('splash'); if (s && !s.classList.contains('hide')) { s.classList.add('hide'); setTimeout(() => s.remove(), 600); } }

  function applyLibrary(lib) {
    S.likes = new Set((lib.likes || []).map(Number)); S.likedAt = lib.likedAt || {};
    S.playlists = lib.playlists || []; S.history = lib.history || []; S.playCounts = lib.playCounts || {}; S.downloads = lib.downloads || {};
    U.setDownloadedCheck((id) => !!S.downloads[String(id)]);
  }

  async function loadCatalog(isUpdate) {
    const [r, li] = await Promise.all([
      fetch(`/__data/catalog.json?v=${Date.now()}`, { cache: 'no-store' }),
      fetch(`/__data/lyrics_index.json?v=${Date.now()}`, { cache: 'no-store' }).catch(() => null),
    ]);
    if (!r.ok) throw new Error('catalog unavailable');
    const data = await r.json();
    S.lyricsIndex = new Map();
    try { if (li && li.ok) for (const [id, e] of Object.entries((await li.json()).songs || {})) S.lyricsIndex.set(+id, e); } catch (e) {  }
    applyCatalog(data, isUpdate);
  }

  const AUX_SUBS = new Set(['instrumental', 'raw', 'acapellas', 'acapella']);
  const AUX_TAG = /[\[({](?:instrumental|acapella|a cappella|raw vocals?|vocals? only)[\])}]/i;
  function isAux(s) { return AUX_SUBS.has(String(s.sub || '').toLowerCase()) || AUX_TAG.test(s.title || ''); }
  function catSongs(key) {
    if (key === 'all') return S.songs.filter((s) => !s.aux);
    if (key === 'misc') return S.songs.filter((s) => s.cat === 'misc' || s.aux);
    return S.songs.filter((s) => s.cat === key);
  }
  function applyCatalog(data, isUpdate) {
    if (data) { S._catalogRaw = data; }
    const raw = S._catalogRaw;
    if (!raw) return;
    const cur = S.current && S.current.id;
    const sourceSongs = raw.songs || [];
    S.songs = S.settings.offlineOnly ? sourceSongs.filter((s) => !!S.downloads[String(s.id)]) : sourceSongs;
    S.fetchedAt = raw.fetched || 0;
    S.byId = new Map(); S.eras = new Map(); S.catCounts = { all: 0 };
    for (const s of S.songs) {
      s.eraKey = canonEra(s.era);
      s.nm = parseTitle(s.title).name;
      s.q = normalizeQuery(`${s.title} ${(s.alt || []).join(' ')}`);
      S.byId.set(s.id, s);
      s.aux = isAux(s);
      S.catCounts[s.cat] = (S.catCounts[s.cat] || 0) + 1;
      if (!s.aux) S.catCounts.all++;
      else if (s.cat !== 'misc') S.catCounts.misc = (S.catCounts.misc || 0) + 1;
      if (s.eraKey) { let e = S.eras.get(s.eraKey); if (!e) { e = { key: s.eraKey, name: s.eraKey, count: 0, songs: [], raw: new Set() }; S.eras.set(s.eraKey, e); } e.count++; e.songs.push(s); e.raw.add(s.era); }
    }
    for (const e of S.eras.values()) e.songs.sort((a, b) => b.plays - a.plays);
    const idx = S.lyricsIndex || new Map();
    S.lyricsCands = [];
    for (const s of S.songs) { const e = idx.get(s.id); if (e) { s.lyr = true; s.wt = s.wt || !!e.w; } if (s.lyr) S.lyricsCands.push(s); }
    for (const [id, e] of idx) if (!S.byId.has(id)) S.lyricsCands.push({ id, title: e.t || '', author: e.a || 'Juice WRLD', era: e.e || null, dur: e.d || 0, lyr: true, wt: !!e.w, cat: 'unreleased', fromIndex: true });
    applyLocal(S.pendingLocal || S.local || []); S.pendingLocal = null;
    if (cur && S.byId.has(cur)) S.current = S.byId.get(cur);
    renderSidebar();
    setStatus('ok', `${fmtInt(S.songs.length)} tracks · ${S.fetchedAt ? 'synced ' + fmtRelative(S.fetchedAt * 1000) : 'cached'}`);
    if (isUpdate && S.route && S.route.name !== 'settings') renderView(S.route, scroller.scrollTop);
    if (S.songs.length) hideSplash();
  }

  function applyLocal(list) {
    for (const old of S.local) if (S.byId.get(old.id) === old) S.byId.delete(old.id);
    S.local = list || [];
    for (const s of S.local) {
      s.eraKey = null; s.nm = parseTitle(s.title).name; s.q = normalizeQuery(`${s.title} ${s.author} ${s.era || ''}`); S.byId.set(s.id, s);
      const m = U.lyricsMatch(s, S.lyricsCands || S.songs);
      s.lyrSrc = m ? { id: m.id, title: m.title, wt: !!m.wt } : null;
      s.lyr = !!m; s.wt = !!(m && m.wt); s.est = !!(m && m.est);
    }
  }
  function catalogStatusHTML() { return `${fmtInt(S.songs.length)} tracks · ${S.fetchedAt ? 'synced ' + fmtRelative(S.fetchedAt * 1000) : 'not synced'}${S.status && S.status.kind === 'err' ? ' · ' + esc(S.status.text) : ''}`; }
  function setStatus(kind, text) { S.status = { kind, text }; const n = el('s-catstatus'); if (n && kind !== 'busy') n.innerHTML = catalogStatusHTML(); }

  function paintChrome() {
    el('brand-logo').innerHTML = I('logo'); el('splash-logo').innerHTML = I('logo');
    el('win-min').innerHTML = I('minimize'); el('win-max').innerHTML = I('maximize'); el('win-close').innerHTML = I('close');
    el('nav-back').innerHTML = I('chevronL'); el('nav-fwd').innerHTML = I('chevronR');
    el('search-ic').innerHTML = I('search'); el('search-clear').innerHTML = I('close');
    el('tb-collapse').innerHTML = I('chevronL'); el('tb-settings').innerHTML = I('settings');
    el('pl-new').innerHTML = I('plus'); el('right-close').innerHTML = I('close');
    for (const c of $$('.nav-sec .chev')) c.innerHTML = I('chevronD');
    el('p-shuffle').innerHTML = I('shuffle'); el('p-prev').innerHTML = I('prev'); el('p-next').innerHTML = I('next'); el('p-repeat').innerHTML = I('repeat');
    el('p-play').insertAdjacentHTML('afterbegin', I('play'));
    el('p-like').innerHTML = I('heart'); el('p-lyrics').innerHTML = I('mic'); el('p-queue').innerHTML = I('queue'); el('p-info').innerHTML = I('info');
    el('p-download').innerHTML = I('download'); el('p-mute').innerHTML = I('volume'); el('p-expand').innerHTML = I('expand');
    el('npv-close').innerHTML = I('collapse');
    $('#p-cover .exp').innerHTML = I('expand');
  }

  function bindChrome() {
    el('win-min').onclick = () => Bridge.fire('winMinimize');
    el('win-max').onclick = () => Bridge.fire('winToggleMax');
    el('win-close').onclick = () => Bridge.fire('winClose');
    const drag = el('drag');
    drag.addEventListener('mousedown', (e) => { if (e.button === 0 && !e.target.closest('button')) Bridge.fire('winDrag'); });
    drag.addEventListener('dblclick', (e) => { if (!e.target.closest('button')) Bridge.fire('winToggleMax'); });
    for (const z of $$('.edge')) z.addEventListener('mousedown', (e) => { if (e.button === 0) { e.preventDefault(); Bridge.fire('winResize', z.dataset.edge); } });
    el('nav-back').onclick = back; el('nav-fwd').onclick = forward;
    el('tb-settings').onclick = () => go({ name: 'settings' });
    el('tb-collapse').onclick = () => { const c = !el('workspace').classList.contains('sb-collapsed'); el('workspace').classList.toggle('sb-collapsed', c); setSetting('sidebarCollapsed', c); el('tb-collapse').innerHTML = I(c ? 'chevronR' : 'chevronL'); setTimeout(paintNavActive, 320); };
    el('tb-offline').innerHTML = I('offline');
    el('tb-offline').onclick = () => setOfflineMode(false);
    paintOfflineChip();
    if (S.settings.sidebarCollapsed) el('tb-collapse').innerHTML = I('chevronR');
    const search = el('search');
    const runSearch = debounce(() => { const q = search.value.trim(); S.q = q; el('search-clear').classList.toggle('hidden', !q); if (q) go({ name: 'search', q }, { replace: S.route && S.route.name === 'search' }); else if (S.route && S.route.name === 'search') back(); }, 140);
    search.addEventListener('input', runSearch);
    search.addEventListener('keydown', (e) => { if (e.key === 'Escape') { search.value = ''; runSearch(); search.blur(); } if (e.key === 'Enter') { const first = S.list && S.list.items[0]; if (first) playFrom(S.list.items, 0, 'search'); } });
    el('search-clear').onclick = () => { search.value = ''; runSearch(); search.focus(); };
    el('pl-new').onclick = () => createPlaylistFlow();
    for (const sec of $$('.nav-sec[data-sec]')) sec.querySelector('.sec-toggle').onclick = () => toggleNavSection(sec.dataset.sec);
    el('right-close').onclick = () => toggleRight(false);
    el('npv-close').onclick = () => openNPV(false);
    document.addEventListener('click', (e) => { if (openMenu && performance.now() - openMenu.t < 150) return; if (!e.target.closest('.menu')) closeMenus(); });
    window.addEventListener('blur', closeMenus);
    scroller.addEventListener('scroll', closeMenus, { passive: true });
    document.addEventListener('contextmenu', (e) => { if (!e.target.closest('input, textarea')) e.preventDefault(); });
    window.addEventListener('resize', () => { if (S.list && S.list.vl) S.list.vl._schedule(true); paintNavActive(); });
    let sbRaf = 0;
    $('.sb-scroll').addEventListener('scroll', () => { if (!sbRaf) sbRaf = requestAnimationFrame(() => { sbRaf = 0; paintNavActive(); }); }, { passive: true });
  }

  function setMaximized(max) { S.maximized = !!max; document.body.classList.toggle('maximized', S.maximized); el('win-max').innerHTML = I(S.maximized ? 'restore' : 'maximize'); el('win-max').title = S.maximized ? 'restore' : 'maximize'; }
  function setSetting(k, v) { S.settings[k] = v; Bridge.fire('setSetting', k, JSON.stringify(v)); }

  function paintOfflineChip() {
    const n = el('tb-offline'); if (!n) return;
    n.classList.toggle('hidden', !S.settings.offlineOnly);
  }
  function setOfflineMode(on) {
    on = !!on;
    if (S.settings.offlineOnly === on) return;
    setSetting('offlineOnly', on);
    applyCatalog(null, true);
    paintOfflineChip();
    const sw = el('s-offline'); if (sw) sw.classList.toggle('on', on);
  }

  function navItem(icon, label, route, count, extra) {
    const b = h('button', { class: 'nav-item' + (extra || ''), dataset: { route: JSON.stringify(route) } });
    b.innerHTML = `${I(icon)}<span class="lbl">${esc(label)}</span>${count !== undefined ? `<span class="count">${fmtInt(count)}</span>` : ''}`;
    b.onclick = () => go(route);
    return b;
  }
  function renderSidebar() {
    const m = el('nav-main'); m.innerHTML = '';
    m.append(navItem('home', 'home', { name: 'home' }));
    const b = el('nav-browse'); b.innerHTML = '';
    for (const c of CATS) if (!['stems', 'remasters'].includes(c.key)) b.append(navItem(c.icon, c.name, { name: 'cat', key: c.key }, S.catCounts[c.key] || 0));
    const entries = {
      liked: () => navItem('heart', 'liked songs', { name: 'liked' }, S.likes.size),
      downloads: () => navItem('download', 'downloads', { name: 'downloads' }, Object.keys(S.downloads).length),
      local: () => navItem('folder', 'local files', { name: 'local' }, S.local.length),
      recent: () => navItem('clock', 'recently played', { name: 'recent' }),
    };
    for (const pl of S.playlists) entries['pl:' + pl.id] = () => { const item = navItem('music', pl.name, { name: 'playlist', id: pl.id }, pl.songs.length, ' pl-item'); item.oncontextmenu = (e) => { e.preventDefault(); showMenu(playlistMenu(pl), e.clientX, e.clientY); }; return item; };
    const saved = Array.isArray(S.settings.collectionOrder) ? S.settings.collectionOrder : [];
    const order = [...saved.filter((k) => entries[k]), ...Object.keys(entries).filter((k) => !saved.includes(k))];
    const hidden = new Set(S.settings.collectionHidden || []);
    const c = el('nav-collection'); c.innerHTML = ''; el('nav-playlists').innerHTML = '';
    for (const key of order) {
      if (hidden.has(key)) continue;
      const item = entries[key](); item.dataset.key = key; item.draggable = true;
      if (!key.startsWith('pl:')) item.oncontextmenu = (e) => { e.preventDefault(); showMenu([{ header: collectionLabel(key) }, { label: 'open', icon: 'external', action: () => go(JSON.parse(item.dataset.route)) }, { sep: true }, { label: 'hide from sidebar', icon: 'eyeOff', action: () => hideCollectionItem(key) }], e.clientX, e.clientY); };
      c.append(item);
    }
    bindCollectionDrag(c, order);
    paintNavActive();
  }
  function collectionLabel(key) {
    if (key.startsWith('pl:')) { const pl = S.playlists.find((p) => 'pl:' + p.id === key); return pl ? pl.name : null; }
    return { liked: 'liked songs', downloads: 'downloads', local: 'local files', recent: 'recently played' }[key] || null;
  }
  function hideCollectionItem(key) {
    const hidden = (S.settings.collectionHidden || []).filter((k) => k !== key);
    hidden.push(key);
    setSetting('collectionHidden', hidden);
    renderSidebar();
    toast(`“${collectionLabel(key) || key}” hidden · unhide it in settings`, '', 4000);
  }
  function unhideCollectionItem(key) {
    setSetting('collectionHidden', (S.settings.collectionHidden || []).filter((k) => k !== key));
    renderSidebar();
    if (S.route && S.route.name === 'settings') renderView(S.route, scroller.scrollTop);
  }
  function bindCollectionDrag(container, order) {
    let dragKey = null;
    container.querySelectorAll('.nav-item').forEach((item) => {
      item.addEventListener('dragstart', (e) => { dragKey = item.dataset.key; item.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; try { e.dataTransfer.setData('text/plain', dragKey); } catch (err) {  } });
      item.addEventListener('dragend', () => { dragKey = null; container.querySelectorAll('.nav-item').forEach((x) => x.classList.remove('dragging', 'drop-before', 'drop-after')); });
      item.addEventListener('dragover', (e) => { if (!dragKey || item.dataset.key === dragKey) return; e.preventDefault(); e.dataTransfer.dropEffect = 'move'; const r = item.getBoundingClientRect(); const before = e.clientY < r.top + r.height / 2; item.classList.toggle('drop-before', before); item.classList.toggle('drop-after', !before); });
      item.addEventListener('dragleave', () => item.classList.remove('drop-before', 'drop-after'));
      item.addEventListener('drop', (e) => {
        if (!dragKey || item.dataset.key === dragKey) return;
        e.preventDefault();
        const r = item.getBoundingClientRect(); const before = e.clientY < r.top + r.height / 2;
        const next = order.filter((k) => k !== dragKey);
        const idx = next.indexOf(item.dataset.key) + (before ? 0 : 1);
        next.splice(idx, 0, dragKey);
        setSetting('collectionOrder', next);
        renderSidebar();
      });
    });
  }
  function applyNavSections() {
    const closed = S.settings.navCollapsed || {};
    for (const sec of $$('.nav-sec[data-sec]')) {
      const key = sec.dataset.sec, off = !!closed[key];
      sec.classList.toggle('closed', off);
      el('sec-' + key).classList.toggle('closed', off);
      sec.querySelector('.sec-toggle').title = (off ? 'show ' : 'hide ') + (key === 'browse' ? 'browse' : 'your collection');
    }
  }
  function toggleNavSection(key) {
    const closed = Object.assign({}, S.settings.navCollapsed || {});
    closed[key] = !closed[key];
    setSetting('navCollapsed', closed);
    applyNavSections();
    const t0 = performance.now();
    const tick = () => { paintNavActive(); if (performance.now() - t0 < 380) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
  }
  function paintNavActive() {
    const cur = JSON.stringify(S.route && (S.route.name === 'search' || S.route.name === 'settings' || S.route.name === 'era' ? null : S.route));
    let active = null;
    for (const b of $$('.nav-item')) { const on = b.dataset.route === cur; b.classList.toggle('active', on); if (on) active = b; }
    if (active && active.closest('.sec-body.closed')) active = null;
    moveIndicator(el('nav-ind'), active, el('sidebar'));
  }
  function moveIndicator(ind, target, host) {
    if (!ind) return;
    if (!target) { ind.classList.remove('show'); return; }
    const parent = target.closest('.sb-scroll') || host;
    if (ind.parentElement !== parent) { parent.appendChild(ind); ind.style.transition = 'none'; requestAnimationFrame(() => { ind.style.transition = ''; }); }
    const pr = parent.getBoundingClientRect(), tr = target.getBoundingClientRect();
    const bw = parent.clientLeft || 0, bh = parent.clientTop || 0;
    ind.style.left = `${Math.round(tr.left - pr.left - bw + parent.scrollLeft)}px`;
    ind.style.width = `${Math.round(tr.width)}px`;
    ind.style.height = `${Math.round(tr.height)}px`;
    ind.style.top = `${Math.round(tr.top - pr.top - bh + parent.scrollTop)}px`;
    ind.classList.add('show');
  }
  function buildRefractionMap() {
    const n = 96, c = document.createElement('canvas'); c.width = c.height = n;
    const g = c.getContext('2d'); const im = g.createImageData(n, n);
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const nx = (x / (n - 1)) * 2 - 1, ny = (y / (n - 1)) * 2 - 1;
      const d = Math.max(Math.abs(nx), Math.abs(ny));
      const e = d < 0.62 ? 0 : Math.pow((d - 0.62) / 0.38, 1.6);
      const i = (y * n + x) * 4;
      im.data[i] = Math.round(128 - nx * e * 110); im.data[i + 1] = Math.round(128 - ny * e * 110); im.data[i + 2] = 128; im.data[i + 3] = 255;
    }
    g.putImageData(im, 0, 0);
    const map = document.getElementById('lg-map');
    if (map) map.setAttribute('href', c.toDataURL());
  }

  function go(route, opts = {}) {
    if (S.route && !opts.replace) { S.stack.push({ route: S.route, scroll: scroller.scrollTop }); if (S.stack.length > 60) S.stack.shift(); S.fwd = []; }
    S.route = route;
    if (route.name !== 'search' && el('search').value && !opts.keepSearch) { el('search').value = ''; el('search-clear').classList.add('hidden'); }
    renderView(route, opts.scroll || 0);
  }
  function back() { const prev = S.stack.pop(); if (!prev) return; S.fwd.push({ route: S.route, scroll: scroller.scrollTop }); S.route = prev.route; if (prev.route.name === 'search') el('search').value = prev.route.q; else { el('search').value = ''; el('search-clear').classList.add('hidden'); } renderView(prev.route, prev.scroll); }
  function forward() { const nx = S.fwd.pop(); if (!nx) return; S.stack.push({ route: S.route, scroll: scroller.scrollTop }); S.route = nx.route; renderView(nx.route, nx.scroll); }

  function renderView(route, scrollTop) {
    closeMenus();
    if (S.list && S.list.vl) { S.list.vl.destroy(); }
    S.list = null;
    const view = el('view'); view.innerHTML = '';
    const node = h('div', { class: 'view' });
    view.appendChild(node);
    const fn = VIEWS[route.name] || VIEWS.home;
    try { fn(node, route); } catch (e) { console.error('view error', e); node.innerHTML = `<div class="empty">${I('info')}<h3>something went wrong</h3><div>${esc(e.message)}</div></div>`; }
    paintNavActive();
    el('nav-back').disabled = !S.stack.length; el('nav-fwd').disabled = !S.fwd.length;
    requestAnimationFrame(() => { scroller.scrollTop = scrollTop || 0; if (S.list && S.list.vl) S.list.vl._schedule(true); paintNavActive(); });
  }

  function imgTag(song, w, cls, attrs = '') {
    const t = coverUrl(song, w), f = imageUrl(song);
    if (!t) return `<div class="ph">${I('music')}</div>`;
    return `<img class="${cls || ''}" src="${esc(t)}" data-full="${esc(f)}" loading="lazy" decoding="async" alt="" onerror="imgErr(this)" ${attrs}>`;
  }
  window.imgErr = function (img) { if (img.dataset.full && img.src !== img.dataset.full) img.src = img.dataset.full; else { img.style.visibility = 'hidden'; } };

  function chipsHTML(song, max = 3) {
    const chips = songChips(song).slice(0, max);
    return chips.length ? `<span class="chips">${chips.map((c) => `<span class="chip ${/stem|instrumental|acapella/i.test(c) ? 'accent' : ''}">${esc(c)}</span>`).join('')}</span>` : '';
  }
  function eraLink(song) {
    if (!song.era) return '';
    return song.eraKey && S.eras.has(song.eraKey) ? `<a class="era-link" data-era="${esc(song.eraKey)}" href="#">${esc(song.era)}</a>` : esc(song.era);
  }
  function subLine(song) {
    const parts = [esc(song.author)]; if (song.era) parts.push(eraLink(song));
    const dl = S.downloads[String(song.id)] ? `<span class="dl" title="downloaded">${I('check')}</span>` : '';
    const ly = song.lyr ? `<span style="color:#9fe9cf"> · lyrics</span>` : '';
    return `${dl}${parts.join(' · ')}${ly}`;
  }

  function rowHTML(song, i, opts) {
    const rank = opts && opts.showRank ? `<span class="rank">${(opts.rankOffset || 0) + i + 1}</span>` : `<span class="n">${i + 1}</span>`;
    const liked = S.likes.has(song.id);
    const dlp = S.dlp.get(song.id);
    return `<div class="c-idx">${rank}<span class="eq"><i></i><i></i><i></i></span><button class="pb" data-act="play" title="play">${I('play')}</button></div>
      <div class="c-title"><div class="cv-sm" ${song.eraKey && S.eras.has(song.eraKey) ? `data-era="${esc(song.eraKey)}" title="go to ${esc(song.era)}"` : ''}>${imgTag(song, 64)}</div><div class="txt"><div class="t"><span class="nm" title="${esc(song.title)}">${esc(song.nm || song.title)}</span>${chipsHTML(song)}</div><div class="s">${subLine(song)}</div></div></div>
      <div class="c-era" title="${esc(song.era || '')}" ${song.eraKey && S.eras.has(song.eraKey) ? `data-era="${esc(song.eraKey)}"` : ''}>${esc(song.eraKey || song.era || '—')}</div>
      <div class="c-act"><button class="btn-icon xs plain ${liked ? 'liked' : ''}" data-act="like" title="${liked ? 'remove from liked songs' : 'save to liked songs'}">${I('heart')}</button>${dlp !== undefined ? `<span class="dlp">${Math.round(dlp * 100)}%</span>` : `<button class="btn-icon xs plain" data-act="download" title="download">${I('download')}</button>`}<button class="btn-icon xs plain" data-act="more" title="more">${I('more')}</button></div>
      <div class="c-dur">${esc(song.len || fmtTime(song.dur))}</div>`;
  }
  function rowState(elm, song) {
    const playing = S.current && S.current.id === song.id;
    elm.classList.toggle('playing', !!playing);
    elm.classList.toggle('paused', !!playing && engine.state !== 'playing' && engine.state !== 'loading');
    elm.classList.toggle('has-liked', S.likes.has(song.id));
  }
  function refreshRow(id) {
    if (!S.list || !S.list.vl) return;
    const elm = S.list.vl.elementFor(id); if (!elm) return;
    const i = S.list.items.findIndex((s) => s.id === id); if (i < 0) return;
    elm.innerHTML = rowHTML(S.list.items[i], i, S.list.opts); rowState(elm, S.list.items[i]);
  }
  function highlightRows() { if (S.list && S.list.vl) for (const [k, elm] of S.list.vl.pool) { const s = S.byId.get(k); if (s) rowState(elm, s); } }

  const SORTS = [['default', 'default order'], ['newest', 'newest'], ['oldest', 'oldest'], ['az', 'title a–z'], ['plays', 'most played'], ['longest', 'longest'], ['shortest', 'shortest']];
  function sortItems(items, sort) {
    const a = items.slice();
    switch (sort) {
      case 'newest': return a.sort((x, y) => (y.created || '').localeCompare(x.created || ''));
      case 'oldest': return a.sort((x, y) => (x.created || '').localeCompare(y.created || ''));
      case 'az': return a.sort((x, y) => x.nm.localeCompare(y.nm, 'en', { sensitivity: 'base' }));
      case 'plays': return a.sort((x, y) => y.plays - x.plays);
      case 'longest': return a.sort((x, y) => y.dur - x.dur);
      case 'shortest': return a.sort((x, y) => x.dur - y.dur);
      default: return a;
    }
  }

  function trackList(host, baseItems, opts = {}) {
    const key = opts.ctxKey || 'list';
    const prefs = S.listPrefs[key] || (S.listPrefs[key] = { q: '', era: null, lyr: false, sort: opts.defaultSort || 'default' });
    const wrap = h('div', { class: 'tl' + (opts.tools === false ? ' no-tools' : '') });
    host.appendChild(wrap);
    let tools = null, headRow, tracks, vl, items = [];

    const compute = () => {
      let it = baseItems;
      if (prefs.era) it = it.filter((s) => s.eraKey === prefs.era);
      if (prefs.lyr) it = it.filter((s) => s.lyr);
      if (prefs.q) { const q = normalizeQuery(prefs.q); it = it.filter((s) => s.q.includes(q) || (s.era && normalizeQuery(s.era).includes(q)) || (s.prod && normalizeQuery(s.prod).includes(q))); }
      items = sortItems(it, prefs.sort);
      S.list = { items, ctxKey: key, vl, opts };
      vl.setItems(items);
      if (tools) tools.querySelector('.cnt').textContent = `${fmtInt(items.length)} tracks · ${fmtLong(items.reduce((a, s) => a + (s.dur || 0), 0))}`;
      if (opts.onItems) opts.onItems(items);
    };

    if (opts.tools !== false) {
      tools = h('div', { class: 'toolbar' });
      const eras = [...new Set(baseItems.map((s) => s.eraKey).filter(Boolean))].map((k) => S.eras.get(k)).filter(Boolean).sort((a, b) => eraSortKey(a.key) - eraSortKey(b.key) || b.count - a.count);
      tools.innerHTML = `<label class="pill">${I('search')}<input type="text" placeholder="filter this list" value="${esc(prefs.q)}"></label>
        <button class="pill era ${prefs.era ? 'on' : ''}">${I('layers')}<span>${esc(prefs.era || 'all eras')}</span>${I('chevronD')}</button>
        <button class="pill lyr ${prefs.lyr ? 'on' : ''}">${I('mic')}<span>lyrics</span></button>
        <span class="spacer"></span><span class="cnt" style="font-size:12px;color:var(--text-3)"></span>
        <button class="pill sort">${I('sort')}<span>${esc((SORTS.find((s) => s[0] === prefs.sort) || SORTS[0])[1])}</span>${I('chevronD')}</button>`;
      wrap.appendChild(tools);
      tools.querySelector('input').addEventListener('input', debounce((e) => { prefs.q = e.target.value; compute(); }, 120));
      tools.querySelector('.era').onclick = (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const its = [{ label: 'all eras', check: true, on: !prefs.era, action: () => { prefs.era = null; renderView(S.route, scroller.scrollTop); } }, { sep: true }];
        for (const er of eras) its.push({ label: er.name, sub: fmtInt(baseItems.filter((s) => s.eraKey === er.key).length), check: true, on: prefs.era === er.key, action: () => { prefs.era = er.key; renderView(S.route, scroller.scrollTop); } });
        showMenu(its, r.left, r.bottom + 6, { cls: 'sub-menu' });
      };
      tools.querySelector('.lyr').onclick = () => { prefs.lyr = !prefs.lyr; tools.querySelector('.lyr').classList.toggle('on', prefs.lyr); compute(); };
      tools.querySelector('.sort').onclick = (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        showMenu(SORTS.map(([k, label]) => ({ label, check: true, on: prefs.sort === k, action: () => { prefs.sort = k; renderView(S.route, scroller.scrollTop); } })), r.right - 220, r.bottom + 6);
      };
    }
    headRow = h('div', { class: 'row head' });
    headRow.innerHTML = `<div class="c-idx">#</div><div class="c-title">title</div><div class="c-era">era</div><div class="c-act"></div><div class="c-dur">${I('clock')}</div>`;
    wrap.appendChild(headRow);
    tracks = h('div', { class: 'tracks' });
    wrap.appendChild(tracks);
    vl = new VirtualList({ scroller, container: tracks, rowHeight: 58, render: (song, i) => { const r = h('div', { class: 'row', dataset: { id: song.id } }); r.innerHTML = rowHTML(song, i, opts); rowState(r, song); return r; }, update: (r, song, i) => { if (r.__i !== i || r.__v !== S.catalogVersion) { r.innerHTML = rowHTML(song, i, opts); r.__i = i; r.__v = S.catalogVersion; } rowState(r, song); } });
    tracks.addEventListener('click', (e) => {
      const row = e.target.closest('.row'); if (!row) return;
      const id = +row.dataset.id; const i = items.findIndex((s) => s.id === id); const song = S.byId.get(id);
      const era = e.target.closest('[data-era]'); if (era) { e.preventDefault(); if (S.eras.has(era.dataset.era)) go({ name: 'era', key: era.dataset.era }); return; }
      const act = e.target.closest('[data-act]'); if (!act) return;
      const a = act.dataset.act;
      if (a === 'play') { if (S.current && S.current.id === id) togglePlay(); else playFrom(items, i, key); }
      else if (a === 'like') toggleLike(id);
      else if (a === 'download') download(id);
      else if (a === 'more') { const r = act.getBoundingClientRect(); row.classList.add('menu-open'); showMenu(songMenu(song, { items, index: i, removable: opts.removable }), r.right - 230, r.bottom + 4, { onClose: () => row.classList.remove('menu-open') }); }
    });
    tracks.addEventListener('dblclick', (e) => { const row = e.target.closest('.row'); if (!row || e.target.closest('button')) return; const id = +row.dataset.id; const i = items.findIndex((s) => s.id === id); if (i >= 0) playFrom(items, i, key); });
    tracks.addEventListener('contextmenu', (e) => { const row = e.target.closest('.row'); if (!row) return; e.preventDefault(); const id = +row.dataset.id; const i = items.findIndex((s) => s.id === id); row.classList.add('menu-open'); showMenu(songMenu(S.byId.get(id), { items, index: i, removable: opts.removable }), e.clientX, e.clientY, { onClose: () => row.classList.remove('menu-open') }); });
    compute();
    if (!items.length) tracks.insertAdjacentHTML('afterend', `<div class="empty">${I('music')}<h3>${esc(opts.emptyTitle || 'nothing here yet')}</h3><div>${esc(opts.emptyText || 'try another filter or search.')}</div></div>`);
    return { get items() { return items; }, recompute: compute };
  }

  const plCoverKey = (id) => `jv.plcover.${id}`;
  function plCover(id) { try { return localStorage.getItem(plCoverKey(id)) || ''; } catch (e) { return ''; } }
  function setPlCover(id, dataUrl) { try { if (dataUrl) localStorage.setItem(plCoverKey(id), dataUrl); else localStorage.removeItem(plCoverKey(id)); return true; } catch (e) { toast('could not save the cover on this device', 'err'); return false; } }
  function pickCover() {
    return new Promise((resolve) => {
      const inp = document.createElement('input'); inp.type = 'file'; inp.accept = 'image/*';
      inp.onchange = () => {
        const f = inp.files && inp.files[0]; if (!f) return resolve('');
        const url = URL.createObjectURL(f); const img = new Image();
        img.onload = () => {
          const N = 512, c = document.createElement('canvas'); c.width = N; c.height = N;
          const side = Math.min(img.naturalWidth, img.naturalHeight), sx = (img.naturalWidth - side) / 2, sy = (img.naturalHeight - side) / 2;
          c.getContext('2d').drawImage(img, sx, sy, side, side, 0, 0, N, N);
          URL.revokeObjectURL(url); resolve(c.toDataURL('image/jpeg', 0.86));
        };
        img.onerror = () => { URL.revokeObjectURL(url); toast('that file is not an image', 'err'); resolve(''); };
        img.src = url;
      };
      inp.click();
    });
  }
  function headerHTML({ eyebrow, icon, title, sub, art, mosaic, editable }) {
    let artHTML = '';
    if (mosaic && mosaic.length) artHTML = `<div class="art mosaic">${mosaic.slice(0, 4).map((s) => imgTag(s, 128)).join('')}</div>`;
    else if (art && art.song) artHTML = `<div class="art">${imgTag(art.song, 384)}</div>`;
    else if (art && art.url) artHTML = `<div class="art"><img src="${esc(art.url)}" alt=""></div>`;
    else if (art && art.icon) artHTML = `<div class="art icon-art">${I(art.icon)}</div>`;
    return `<div class="page-h">${artHTML}<div class="meta"><div class="eyebrow">${icon ? I(icon) : ''}${esc(eyebrow || '')}</div><h1 class="title ${editable ? 'editable' : ''}" ${editable ? 'contenteditable="true" spellcheck="false"' : ''}>${esc(title)}</h1><div class="sub">${sub || ''}</div><div class="actions"></div></div></div>`;
  }
  function headerActions(node, items, { ctxKey, extra } = {}) {
    const a = node.querySelector('.actions');
    const play = h('button', { class: 'btn-play-lg', title: 'play' }); play.innerHTML = I('play');
    play.onclick = () => { if (items.length) { const was = S.shuffle; S.shuffle = false; playFrom(items, 0, ctxKey); S.shuffle = was; paintShuffleRepeat(); if (was) reshuffleQueueKeepCurrent(); } };
    const sh = h('button', { class: 'btn' }); sh.innerHTML = I('shuffle') + 'shuffle';
    sh.onclick = () => { if (items.length) { const i = Math.floor(Math.random() * items.length); const was = S.shuffle; S.shuffle = true; playFrom(items, i, ctxKey); if (!was) { S.shuffle = true; setSetting('shuffle', true); paintShuffleRepeat(); } } };
    a.append(play, sh);
    if (extra) for (const b of extra) a.append(b);
    return a;
  }
  function cardHTML(song, { badge, rank, sub } = {}) {
    const playing = S.current && S.current.id === song.id;
    return `<div class="card ${playing ? 'playing' : ''}" data-id="${song.id}"><div class="cv">${imgTag(song, 256)}<button class="play" data-act="play">${I(playing && engine.state === 'playing' ? 'pause' : 'play')}</button>${rank ? `<span class="rank">${rank}</span>` : badge ? `<span class="badge">${esc(badge)}</span>` : ''}</div><div class="t" title="${esc(song.title)}">${esc(song.nm || song.title)}</div><div class="s">${sub ? esc(sub) : [esc(song.author), eraLink(song)].filter(Boolean).join(' · ')}</div></div>`;
  }
  function shelf(node, { title, more, songs, badgeFn, rank, subFn, wrap }) {
    if (!songs.length) return;
    const sh = h('div', { class: 'shelf' });
    sh.innerHTML = `<div class="shelf-h"><h2>${esc(title)}</h2>${more ? `<button class="more">show all</button>` : ''}</div><div class="cards ${wrap ? 'wrap' : ''}">${songs.map((s, i) => cardHTML(s, { badge: badgeFn && badgeFn(s), rank: rank ? i + 1 : 0, sub: subFn && subFn(s) })).join('')}</div>`;
    if (more) sh.querySelector('.more').onclick = more;
    bindCards(sh.querySelector('.cards'), songs, title);
    node.appendChild(sh);
  }
  function bindCards(container, songs, ctxKey) {
    container.addEventListener('click', (e) => {
      const card = e.target.closest('.card'); if (!card) return;
      const id = +card.dataset.id; const i = songs.findIndex((s) => s.id === id);
      const era = e.target.closest('[data-era]'); if (era) { e.preventDefault(); if (S.eras.has(era.dataset.era)) go({ name: 'era', key: era.dataset.era }); return; }
      if (e.target.closest('[data-act="play"]') || e.detail === 2) { if (S.current && S.current.id === id) togglePlay(); else playFrom(songs, i, ctxKey); }
      else openDetails(S.byId.get(id));
    });
    container.addEventListener('contextmenu', (e) => { const card = e.target.closest('.card'); if (!card) return; e.preventDefault(); const id = +card.dataset.id; showMenu(songMenu(S.byId.get(id), { items: songs, index: songs.findIndex((s) => s.id === id) }), e.clientX, e.clientY); });
  }

  const VIEWS = {
    home(node) {
      if (S.playlists.length) {
        const quick = S.playlists.map((pl) => ({ pl, cover: plCover(pl.id) }));
        const q = h('div', { class: 'shelf' });
        q.innerHTML = `<div class="shelf-h"><h2>your playlists</h2></div><div class="quick">${quick.map((x, i) => `<div class="quick-item" data-i="${i}"><div class="qa">${x.cover ? `<img src="${esc(x.cover)}" alt="">` : I('music')}</div><div class="txt"><div class="qt">${esc(x.pl.name)}</div><div class="qs">${fmtInt(x.pl.songs.length)} tracks</div></div></div>`).join('')}</div>`;
        q.querySelectorAll('.quick-item').forEach((it) => (it.onclick = () => go({ name: 'playlist', id: quick[+it.dataset.i].pl.id })));
        node.appendChild(q);
      }
      const newest = S.songs.filter((s) => !s.aux).slice(0, 13);
      shelf(node, { title: 'recently uploaded', songs: newest, more: () => go({ name: 'cat', key: 'all' }) });
      const recent = S.history.slice().reverse().map((x) => S.byId.get(x.id)).filter(Boolean);
      const jump = [...new Map(recent.map((s) => [s.id, s])).values()].slice(0, 12);
      if (jump.length) shelf(node, { title: 'jump back in', songs: jump, more: () => go({ name: 'recent' }) });
      const lyr = shuffle(S.songs.filter((s) => s.lyr && s.wt)).slice(0, 12);
      shelf(node, { title: 'sing along · synced lyrics', songs: lyr, badgeFn: () => 'lyrics' });
      const topPlayed = Object.entries(S.playCounts).sort((a, b) => b[1] - a[1]).map(([id]) => S.byId.get(+id)).filter(Boolean).slice(0, 12);
      if (topPlayed.length >= 3) shelf(node, { title: 'your most played', songs: topPlayed, subFn: (s) => `${S.playCounts[s.id]} plays by you` });
    },

    cat(node, route) {
      const c = CAT_BY_KEY[route.key] || CAT_BY_KEY.all;
      const items = catSongs(c.key);
      node.innerHTML = headerHTML({ eyebrow: 'collection', icon: c.icon, title: c.name, sub: `<b>${fmtInt(items.length)} tracks</b><span class="dot"></span><span>${esc(c.blurb)}</span><span class="dot"></span><span>${fmtLong(items.reduce((a, s) => a + s.dur, 0))}</span>`, art: { icon: c.icon, grad: TILE_GRADS[CATS.indexOf(c) % TILE_GRADS.length] } });
      const tl = trackList(node, items, { ctxKey: 'cat:' + c.key, defaultSort: 'newest' });
      headerActions(node, tl.items, { ctxKey: 'cat:' + c.key });
    },

    recent(node) {
      const seen = new Set(); const items = [];
      for (const x of S.history.slice().reverse()) { const s = S.byId.get(x.id); if (s && !seen.has(s.id)) { seen.add(s.id); items.push(s); } }
      node.innerHTML = headerHTML({ eyebrow: 'your collection', icon: 'clock', title: 'recently played', sub: `<b>${fmtInt(items.length)} tracks</b><span class="dot"></span><span>only on this device</span>`, art: { icon: 'clock' } });
      const tl = trackList(node, items, { ctxKey: 'recent', emptyTitle: 'no plays yet', emptyText: 'everything you listen to shows up here.' });
      headerActions(node, tl.items, { ctxKey: 'recent' });
    },

    eras(node) {
      const eras = [...S.eras.values()].sort((a, b) => eraSortKey(a.key) - eraSortKey(b.key) || b.count - a.count);
      const main = eras.filter((e) => e.count >= 10), small = eras.filter((e) => e.count < 10);
      node.innerHTML = headerHTML({ eyebrow: 'browse', icon: 'layers', title: 'eras', sub: `<b>${fmtInt(eras.length)} eras</b><span class="dot"></span><span>from the 999 days to The Party Never Ends</span>`, art: { icon: 'layers', grad: 'linear-gradient(135deg,#c084fc,#8c96ff)' } });
      node.querySelector('.actions').remove();
      const tiles = h('div', { class: 'tiles', style: { marginBottom: '26px' } });
      tiles.innerHTML = main.map((e, i) => eraTileHTML(e, i, true)).join('');
      tiles.querySelectorAll('.tile').forEach((t) => (t.onclick = () => go({ name: 'era', key: t.dataset.key })));
      node.appendChild(tiles);
      if (small.length) {
        const more = h('div', { class: 'shelf' });
        more.innerHTML = `<div class="shelf-h"><h2>more eras & tags</h2></div><div class="chips">${small.map((e) => `<button class="pill era" data-key="${esc(e.key)}"><span>${esc(e.name)}</span><span style="color:var(--text-3)">${e.count}</span></button>`).join('')}</div>`;
        more.querySelectorAll('.pill').forEach((p) => (p.onclick = () => go({ name: 'era', key: p.dataset.key })));
        node.appendChild(more);
      }
    },

    era(node, route) {
      const e = S.eras.get(route.key);
      if (!e) { node.innerHTML = `<div class="empty">${I('layers')}<h3>unknown era</h3></div>`; return; }
      const items = e.songs.slice();
      const raw = [...e.raw].filter((r) => r !== e.name);
      node.innerHTML = headerHTML({ eyebrow: `era${ERA_YEARS[e.name] ? ' · ' + ERA_YEARS[e.name] : ''}`, icon: 'layers', title: e.name, sub: `<b>${fmtInt(items.length)} tracks</b><span class="dot"></span><span>${fmtLong(items.reduce((a, s) => a + s.dur, 0))}</span>${raw.length ? `<span class="dot"></span><span>also tagged: ${esc(raw.join(', '))}</span>` : ''}`, art: items.length ? { song: items[0] } : { icon: 'layers' } });
      const tl = trackList(node, items, { ctxKey: 'era:' + e.key, defaultSort: 'plays' });
      headerActions(node, tl.items, { ctxKey: 'era:' + e.key });
    },

    liked(node) {
      const items = [...S.likes].map((id) => S.byId.get(id)).filter(Boolean).sort((a, b) => (S.likedAt[b.id] || 0) - (S.likedAt[a.id] || 0));
      node.innerHTML = headerHTML({ eyebrow: 'playlist', icon: 'heart', title: 'liked songs', sub: `<b>${fmtInt(items.length)} tracks</b><span class="dot"></span><span>${fmtLong(items.reduce((a, s) => a + s.dur, 0))}</span>`, art: { icon: 'heart', grad: 'linear-gradient(135deg,#f472b6,#8c96ff)' } });
      const tl = trackList(node, items, { ctxKey: 'liked', emptyTitle: 'songs you like will appear here', emptyText: 'save songs by tapping the heart.' });
      headerActions(node, tl.items, { ctxKey: 'liked' });
    },

    playlist(node, route) {
      const pl = S.playlists.find((p) => p.id === route.id);
      if (!pl) { node.innerHTML = `<div class="empty">${I('music')}<h3>playlist not found</h3></div>`; return; }
      const items = pl.songs.map((id) => S.byId.get(id)).filter(Boolean);
      node.innerHTML = headerHTML({ eyebrow: 'playlist', icon: 'music', title: pl.name, sub: `<b>${fmtInt(items.length)} tracks</b><span class="dot"></span><span>${fmtLong(items.reduce((a, s) => a + s.dur, 0))}</span><span class="dot"></span><span>created ${fmtDate(pl.created * 1000)}</span>`, art: plCover(pl.id) ? { url: plCover(pl.id) } : { icon: 'music' }, editable: true });
      const art = node.querySelector('.page-h .art'); art.classList.add('pickable');
      const change = async () => { const d = await pickCover(); if (d && setPlCover(pl.id, d)) { go(route, { replace: true }); renderSidebar(); } };
      art.onclick = change;
      art.oncontextmenu = (e) => { e.preventDefault(); showMenu([{ label: 'change cover', icon: 'edit', action: change }, plCover(pl.id) ? { label: 'remove cover', icon: 'trash', action: () => { setPlCover(pl.id, ''); go(route, { replace: true }); renderSidebar(); } } : null].filter(Boolean), e.clientX, e.clientY); };
      const t = node.querySelector('h1.title');
      t.addEventListener('blur', () => { const name = t.textContent.trim(); if (name && name !== pl.name) { updatePlaylist(pl.id, { name }); } else t.textContent = pl.name; });
      t.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); t.blur(); } });
      const tl = trackList(node, items, { ctxKey: 'pl:' + pl.id, removable: pl.id, emptyTitle: 'this playlist is empty', emptyText: 'right-click any song → add to playlist.' });
      const more = h('button', { class: 'btn-icon', title: 'more' }); more.innerHTML = I('more');
      more.onclick = (e) => { const r = e.currentTarget.getBoundingClientRect(); showMenu(playlistMenu(pl), r.left, r.bottom + 6); };
      headerActions(node, tl.items, { ctxKey: 'pl:' + pl.id, extra: [more] });
    },

    local(node) {
      const items = S.local.slice();
      const folders = S.settings.localFolders || [];
      node.innerHTML = headerHTML({ eyebrow: 'your collection', icon: 'folder', title: 'local files', sub: `<b>${fmtInt(items.length)} tracks</b><span class="dot"></span><span>${fmtLong(items.reduce((a, s) => a + (s.dur || 0), 0))}</span><span class="dot"></span><span style="overflow-wrap:anywhere">${folders.length ? esc(folders.join(' · ')) : 'no folders yet'}</span>`, art: { icon: 'folder', grad: 'linear-gradient(135deg,#60a5fa,#5de6b2)' } });
      const add = h('button', { class: 'btn' }); add.innerHTML = I('plus') + 'add folder'; add.onclick = () => Bridge.call('addLocalFolder');
      const re = h('button', { class: 'btn ghost' }); re.innerHTML = I('refresh') + 'rescan'; re.onclick = () => { Bridge.fire('rescanLocal'); toast('scanning your folders…'); };
      const tl = trackList(node, items, { ctxKey: 'local', defaultSort: 'default', emptyTitle: 'no local files yet', emptyText: 'add a folder with your own mp3 / wav / flac / m4a files and they show up here, playable like everything else.' });
      headerActions(node, tl.items, { ctxKey: 'local', extra: [add, re] });
    },

    downloads(node) {
      const entries = Object.entries(S.downloads).map(([id, info]) => ({ id: +id, info, song: S.byId.get(+id) })).sort((a, b) => (b.info.at || 0) - (a.info.at || 0));
      const items = entries.map((e) => e.song).filter(Boolean);
      const total = entries.reduce((a, e) => a + (e.info.size || 0), 0);
      node.innerHTML = headerHTML({ eyebrow: 'your collection', icon: 'download', title: 'downloads', sub: `<b>${fmtInt(entries.length)} files</b><span class="dot"></span><span>${fmtBytes(total)}</span><span class="dot"></span><span style="overflow-wrap:anywhere">${esc(S.settings.downloadDir || '')}</span>`, art: { icon: 'download', grad: 'linear-gradient(135deg,#5de6b2,#c084fc)' } });
      const open = h('button', { class: 'btn' }); open.innerHTML = I('folder') + 'open folder'; open.onclick = () => Bridge.fire('openDownloads');
      const change = h('button', { class: 'btn ghost' }); change.innerHTML = I('edit') + 'change folder'; change.onclick = () => Bridge.call('chooseDownloadFolder');
      const tl = trackList(node, items, { ctxKey: 'downloads', emptyTitle: 'no downloads yet', emptyText: 'hit the download arrow on any track — files are tagged with title, artist, era and cover art.' });
      headerActions(node, tl.items, { ctxKey: 'downloads', extra: [open, change] });
    },

    search(node, route) {
      const q = normalizeQuery(route.q);
      const toks = q.split(' ').filter(Boolean);
      const scored = [];
      for (const s of S.songs) {
        let sc = 0;
        if (s.q === q) sc += 100; else if (s.q.startsWith(q)) sc += 60; else if (s.q.includes(q)) sc += 40;
        else if (toks.length > 1 && toks.every((t) => s.q.includes(t))) sc += 25;
        if (!sc) { const extra = normalizeQuery(`${s.era || ''} ${s.prod || ''} ${s.author}`); if (extra.includes(q)) sc += 12; else if (toks.length > 1 && toks.every((t) => extra.includes(t) || s.q.includes(t))) sc += 10; }
        if (sc) scored.push([sc + Math.min(s.plays, 5000) / 1000, s]);
      }
      scored.sort((a, b) => b[0] - a[0]);
      const items = scored.map((x) => x[1]);
      const eras = [...S.eras.values()].filter((e) => normalizeQuery(e.name).includes(q) || [...e.raw].some((r) => normalizeQuery(r).includes(q)));
      const pls = S.playlists.filter((p) => normalizeQuery(p.name).includes(q));
      node.innerHTML = `<div class="page-h" style="padding-bottom:10px"><div class="meta"><div class="eyebrow">${I('search')}search</div><h1 class="title" style="font-size:34px">“${esc(route.q)}”</h1><div class="sub"><b>${fmtInt(items.length)} tracks</b>${eras.length ? `<span class="dot"></span><span>${eras.length} eras</span>` : ''}${pls.length ? `<span class="dot"></span><span>${pls.length} playlists</span>` : ''}</div></div></div>`;
      if (eras.length || pls.length) {
        const row = h('div', { class: 'chips', style: { padding: '0 4px 18px' } });
        for (const e of eras.slice(0, 8)) { const b = h('button', { class: 'pill era' }); b.innerHTML = I('layers') + `<span>${esc(e.name)}</span>` + `<span style="color:var(--text-3)">${e.count}</span>`; b.onclick = () => go({ name: 'era', key: e.key }); row.appendChild(b); }
        for (const p of pls.slice(0, 6)) { const b = h('button', { class: 'pill era' }); b.innerHTML = I('music') + `<span>${esc(p.name)}</span>`; b.onclick = () => go({ name: 'playlist', id: p.id }); row.appendChild(b); }
        node.appendChild(row);
      }
      if (items.length) shelf(node, { title: 'top results', songs: items.slice(0, 6) });
      trackList(node, items, { ctxKey: 'search', tools: false, emptyTitle: `no results for “${route.q}”`, emptyText: 'check the spelling, or try an alternate title.' });
    },

    settings(node) {
      const st = S.settings;
      node.innerHTML = headerHTML({ eyebrow: 'app', icon: 'settings', title: 'settings', sub: `<b>${esc(String(S.app.name || '999 player').toLowerCase())}</b><span class="dot"></span><span>v${esc(S.app.version || 'dev')}</span>`, art: { icon: 'settings', grad: 'linear-gradient(135deg,#8c96ff,#5de6b2)' } });
      node.querySelector('.actions').remove();
      const hiddenItems = (st.collectionHidden || []).map((k) => [k, collectionLabel(k)]).filter(([, name]) => name);
      const wrap = h('div');
      wrap.innerHTML = `
        <div class="set-card"><h3>offline mode</h3>
          <div class="set-row"><div class="l"><div class="t">only show downloaded tracks</div><div class="d">when you go offline, you'll only be able to play the local music you have imported or the music you've downloaded</div></div><button class="switch ${S.settings.offlineOnly ? 'on' : ''}" id="s-offline"></button></div>
        </div>
        <div class="set-card"><h3>downloads</h3>
          <div class="set-row"><div class="l"><div class="t">download folder</div><div class="d">${esc(st.downloadDir || '')}</div></div><div style="display:flex;gap:8px"><button class="btn sm" id="s-open">${I('folder')}open</button><button class="btn sm" id="s-folder">${I('edit')}change</button></div></div>
          <div class="set-row"><div class="l"><div class="t">tag downloaded files</div><div class="d">write title, artist, era and cover art into the audio file</div></div><button class="switch ${st.tagAudio !== false ? 'on' : ''}" id="s-tag"></button></div>
        </div>
        <div class="set-card"><h3>appearance</h3>
          <div class="set-row"><div class="l"><div class="t">glass intensity</div><div class="d">blur costs gpu time, enable a lower setting on weaker machines</div></div><div class="seg" id="s-glass">${['full', 'reduced', 'off'].map((k) => `<button data-k="${k}" class="${(st.glass || 'full') === k ? 'on' : ''}">${k}</button>`).join('')}</div></div>
          <div class="set-row"><div class="l"><div class="t">gpu acceleration</div><div class="d">turn this off if you experience app crashes or if the app goes blank every few minutes</div></div><button class="switch ${st.gpuOff ? '' : 'on'}" id="s-gpu"></button></div>
        </div>
        <div class="set-card"><h3>sidebar</h3>
          <div class="set-row"><div class="l"><div class="t">hidden items</div><div class="d">${hiddenItems.length ? 'these are tucked away from your collection' : 'nothing hidden, right-click anything under your collection to hide it'}</div></div>${hiddenItems.length > 1 ? `<button class="btn sm ghost" id="s-showall">${I('eye')}show all</button>` : ''}</div>
          ${hiddenItems.map(([k, name]) => `<div class="set-row"><div class="l"><div class="t">${esc(name)}</div></div><button class="btn sm" data-unhide="${esc(k)}">${I('eye')}show</button></div>`).join('')}
        </div>
        <div class="set-card"><h3>local files</h3>
          <div class="set-row"><div class="l"><div class="t">music folders</div><div class="d">${(st.localFolders || []).length ? '' : 'no folders yet, '}your own files show up under local files in the sidebar</div></div><div style="display:flex;gap:8px;flex:none"><button class="btn sm" id="s-lcadd">${I('plus')}add folder</button><button class="btn sm ghost" id="s-lcscan">${I('refresh')}rescan</button></div></div>
          ${(st.localFolders || []).map((f, i) => `<div class="set-row"><div class="l"><div class="d" style="overflow-wrap:anywhere">${esc(f)}</div></div><button class="btn sm ghost danger" data-lcrm="${i}">${I('trash')}remove</button></div>`).join('')}
        </div>
        <div class="set-card"><h3>lyrics</h3>
          <div class="set-row"><div class="l"><div class="t">offline lyrics</div><div class="d" id="s-lystatus">…</div></div><div style="display:flex;gap:8px;flex:none"><button class="btn sm" id="s-lydl">${I('refresh')}refresh lyrics</button><button class="btn sm ghost" id="s-lyopen">${I('folder')}open folder</button></div></div>
        </div>
        <div class="set-card"><h3>discord</h3>
          <div class="set-row"><div class="l"><div class="t">show what i'm playing on discord</div><div class="d" id="s-dcstatus">status: ${esc(S.discordStatus || 'off')}</div></div><button class="switch ${st.discordEnabled !== false ? 'on' : ''}" id="s-dc"></button></div>
          <div class="set-row"><div class="l"><div class="t">application id</div><div class="d">one-time setup: open discord.com/developers/applications, hit "new application", name it <b>999 player</b>, copy the application id and paste it here. that name is what shows as "listening to …".</div></div><div style="display:flex;gap:8px;align-items:center;flex:none"><input class="field sm" id="s-dcid" style="width:210px" placeholder="paste application id" value="${esc(st.discordClientId || '')}" spellcheck="false"><button class="btn sm" id="s-dcsave">save</button><button class="btn sm ghost" id="s-dcopen">${I('external')}open</button></div></div>
        </div>
        <div class="set-card"><h3>last.fm</h3>
          <div class="set-row"><div class="l"><div class="t">scrobble to last.fm</div><div class="d" id="s-lfstatus">status: …</div></div><button class="switch ${st.lastfmEnabled !== false ? 'on' : ''}" id="s-lf"></button></div>
          <div class="set-row stack"><div class="l"><div class="t">api key &amp; shared secret</div><div class="d">one-time setup: get them at last.fm/api/account/create (any name, no callback needed), paste both, save, then press connect and approve in the browser.</div></div><div style="display:flex;gap:8px;align-items:center;flex:none;flex-wrap:wrap;justify-content:flex-end"><input class="field sm" id="s-lfkey" style="width:180px" placeholder="api key" value="${esc(st.lastfmApiKey || '')}" spellcheck="false"><input class="field sm" id="s-lfsecret" style="width:180px" placeholder="shared secret" type="password" value="${esc(st.lastfmSecret || '')}" spellcheck="false"><button class="btn sm" id="s-lfsave">save</button><button class="btn sm ghost" id="s-lfopen">${I('external')}get keys</button></div></div>
          <div class="set-row"><div class="l"><div class="t">account</div><div class="d">connect opens last.fm; press allow there and come back, it connects on its own (or press “i approved”).</div></div><div style="display:flex;gap:8px;flex:none"><button class="btn sm" id="s-lfconnect">connect</button><button class="btn sm primary hidden" id="s-lffinish">i approved</button><button class="btn sm ghost hidden" id="s-lfdisc">disconnect</button></div></div>
        </div>
        <div class="set-card" id="s-upcard">${updateCardHTML()}</div>
        <div class="set-card"><h3>library</h3>
          <div class="set-row"><div class="l"><div class="t">catalog</div><div class="d" id="s-catstatus">${catalogStatusHTML()}</div></div><button class="btn sm" id="s-sync">${I('refresh')}sync now</button></div>
          <div class="set-row"><div class="l"><div class="t">your data</div><div class="d">likes, playlists and history live in ${esc(S.app.dataDir || 'your local app data')}</div></div><button class="btn sm" id="s-logs">${I('file')}open logs</button></div>
          <div class="set-row"><div class="l"><div class="t">source</div><div class="d">all music and metadata streams from juicewrldvault.com, support them if you can</div></div><button class="btn sm" id="s-site">${I('external')}open site</button></div>
          <div class="set-row"><div class="l"><div class="t">discord</div><div class="d">bugs, requests, beta codes, or just to hang out</div></div><button class="btn sm" id="s-discord">${I('external')}join</button></div>
        </div>
        <div class="set-card"><h3>keyboard</h3><div class="keys">
          <div><span>play / pause</span><kbd>space</kbd></div><div><span>next / previous</span><span><kbd>shift</kbd> <kbd>→</kbd> / <kbd>←</kbd></span></div>
          <div><span>seek 5s</span><span><kbd>→</kbd> / <kbd>←</kbd></span></div><div><span>volume</span><span><kbd>↑</kbd> / <kbd>↓</kbd></span></div>
          <div><span>mute</span><kbd>m</kbd></div><div><span>lyrics panel</span><kbd>l</kbd></div><div><span>queue panel</span><kbd>q</kbd></div><div><span>now playing view</span><kbd>f</kbd></div>
          <div><span>search</span><span><kbd>ctrl</kbd> <kbd>k</kbd></span></div><div><span>shuffle / repeat</span><span><kbd>s</kbd> / <kbd>r</kbd></span></div><div><span>like current</span><kbd>h</kbd></div><div><span>back</span><span><kbd>alt</kbd> <kbd>←</kbd></span></div>
        </div></div>`;
      node.appendChild(wrap);
      bindUpdateCard(wrap);
      wrap.querySelector('#s-offline').onclick = (e) => { const on = !e.currentTarget.classList.contains('on'); e.currentTarget.classList.toggle('on', on); setOfflineMode(on); };
      wrap.querySelector('#s-open').onclick = () => Bridge.fire('openDownloads');
      wrap.querySelector('#s-folder').onclick = () => Bridge.call('chooseDownloadFolder');
      wrap.querySelector('#s-tag').onclick = (e) => { const on = !e.currentTarget.classList.contains('on'); e.currentTarget.classList.toggle('on', on); setSetting('tagAudio', on); };
      wrap.querySelectorAll('[data-unhide]').forEach((b) => (b.onclick = () => unhideCollectionItem(b.dataset.unhide)));
      const showAll = wrap.querySelector('#s-showall'); if (showAll) showAll.onclick = () => { setSetting('collectionHidden', []); renderSidebar(); renderView(S.route, scroller.scrollTop); };
      wrap.querySelector('#s-gpu').onclick = (e) => { const on = !e.currentTarget.classList.contains('on'); e.currentTarget.classList.toggle('on', on); setSetting('gpuOff', !on); toast(on ? 'gpu acceleration on after the next restart' : 'software rendering after the next restart', '', 4000); };
      wrap.querySelector('#s-glass').onclick = (e) => { const b = e.target.closest('button'); if (!b) return; wrap.querySelectorAll('#s-glass button').forEach((x) => x.classList.toggle('on', x === b)); document.documentElement.dataset.glass = b.dataset.k; setSetting('glass', b.dataset.k); };
      const dcApply = () => { const id = wrap.querySelector('#s-dcid').value.replace(/\D/g, ''); const on = wrap.querySelector('#s-dc').classList.contains('on'); S.settings.discordClientId = id; S.settings.discordEnabled = on; Bridge.fire('configureDiscord', id, on); pushPresence(true); };
      wrap.querySelector('#s-dc').onclick = (e) => { e.currentTarget.classList.toggle('on'); dcApply(); };
      wrap.querySelector('#s-dcsave').onclick = () => { dcApply(); toast('discord settings saved', 'ok'); };
      wrap.querySelector('#s-dcid').onkeydown = (e) => { if (e.key === 'Enter') { dcApply(); toast('discord settings saved', 'ok'); } };
      wrap.querySelector('#s-dcopen').onclick = () => Bridge.fire('openExternal', 'https://discord.com/developers/applications');
      wrap.querySelector('#s-lydl').onclick = () => { Bridge.fire('downloadLyrics'); toast('refreshing every song’s lyrics…'); };
      wrap.querySelector('#s-lyopen').onclick = () => Bridge.fire('openLyricsFolder');
      paintLyricsStore();
      wrap.querySelector('#s-lcadd').onclick = () => Bridge.call('addLocalFolder');
      wrap.querySelector('#s-lcscan').onclick = () => { Bridge.fire('rescanLocal'); toast('scanning your folders…'); };
      wrap.querySelectorAll('[data-lcrm]').forEach((b) => (b.onclick = () => Bridge.fire('removeLocalFolder', (st.localFolders || [])[+b.dataset.lcrm])));
      const lfApply = () => { const k = wrap.querySelector('#s-lfkey').value.trim(), sec = wrap.querySelector('#s-lfsecret').value.trim(), on = wrap.querySelector('#s-lf').classList.contains('on'); S.settings.lastfmApiKey = k; S.settings.lastfmSecret = sec; S.settings.lastfmEnabled = on; Bridge.fire('lastfmConfigure', k, sec, on); };
      wrap.querySelector('#s-lf').onclick = (e) => { e.currentTarget.classList.toggle('on'); lfApply(); };
      wrap.querySelector('#s-lfsave').onclick = () => { lfApply(); toast('last.fm keys saved', 'ok'); };
      wrap.querySelector('#s-lfopen').onclick = () => Bridge.fire('openExternal', 'https://www.last.fm/api/account/create');
      wrap.querySelector('#s-lfconnect').onclick = () => { lfApply(); if (!S.settings.lastfmApiKey || !S.settings.lastfmSecret) { toast('paste your last.fm api key and shared secret first — opening the page to get them', 'err', 5000); Bridge.fire('openExternal', 'https://www.last.fm/api/account/create'); wrap.querySelector('#s-lfkey').focus(); return; } Bridge.fire('lastfmConnect'); toast('approve the app in your browser, then press “i approved”', '', 6000); };
      wrap.querySelector('#s-lffinish').onclick = () => Bridge.fire('lastfmFinish');
      wrap.querySelector('#s-lfdisc').onclick = () => Bridge.fire('lastfmDisconnect');
      paintLastfm();
      wrap.querySelector('#s-sync').onclick = () => { Bridge.fire('refreshCatalog'); toast('syncing with the vault…'); };
      wrap.querySelector('#s-logs').onclick = () => Bridge.fire('openLogs');
      wrap.querySelector('#s-site').onclick = () => Bridge.fire('openExternal', 'https://juicewrldvault.com/');
      wrap.querySelector('#s-discord').onclick = () => Bridge.fire('openExternal', 'https://discord.gg/yhK8zSH8T3');
    },
  };

  const TILE_GRADS = ['linear-gradient(135deg,#8c96ff,#c084fc)', 'linear-gradient(135deg,#f472b6,#fb923c)', 'linear-gradient(135deg,#5de6b2,#8c96ff)', 'linear-gradient(135deg,#c084fc,#f472b6)', 'linear-gradient(135deg,#60a5fa,#5de6b2)', 'linear-gradient(135deg,#fb923c,#c084fc)', 'linear-gradient(135deg,#8c96ff,#5de6b2)'];
  function eraTileHTML(e, i, big) {
    return `<div class="tile ${big ? 'lg' : ''}" data-key="${esc(e.key)}" style="--tile-grad:${TILE_GRADS[i % TILE_GRADS.length]}"><div class="mosaic">${e.songs.slice(0, 4).map((s) => imgTag(s, 96)).join('')}</div><h3>${esc(e.name)}</h3><div class="s">${fmtInt(e.count)} tracks${ERA_YEARS[e.name] ? ' · ' + ERA_YEARS[e.name] : ''}</div></div>`;
  }

  function playFrom(items, index, ctxKey) {
    if (!items || !items.length) return;
    const ids = items.map((s) => s.id);
    S.ctx = ctxKey; S.queueSource = ids;
    if (S.shuffle) { const first = ids[index]; S.queue = [first, ...shuffle(ids.filter((_, i) => i !== index))]; S.qIndex = 0; }
    else { S.queue = ids; S.qIndex = index; }
    playSong(ids[index]);
  }
  function reshuffleQueueKeepCurrent() {
    const cur = S.current ? S.current.id : null;
    if (S.shuffle) { const rest = shuffle(S.queueSource.filter((id) => id !== cur)); S.queue = cur ? [cur, ...rest] : rest; S.qIndex = cur ? 0 : -1; }
    else { S.queue = S.queueSource.slice(); S.qIndex = cur ? S.queue.indexOf(cur) : -1; }
    renderQueueIfOpen();
  }
  function playSong(id, { autoplay = true } = {}) {
    const s = S.byId.get(id); if (!s) return;
    S.current = s; S.playCounted = false;
    engine.load(s, { autoplay });
    paintPlayer(); setAmbient(s); requestAccent(s); highlightRows(); updateCards();
    S.detailTarget = null;
    loadDetailFor(s);
    renderRight();
    paintNPV();
    const nextId = S.queue[S.qIndex + 1]; if (nextId) engine.preload(S.byId.get(nextId));
    document.title = `${s.nm} · ${s.author}`;
    setMediaSession(s);
    presLast = null;
    pushPresence(true);
    S.scrob = { id: s.id, started: Math.floor(Date.now() / 1000), played: 0, lastT: null, done: false, np: false };
  }

  function lastfmPayload(s) { return { artist: s.author, track: s.nm, album: s.era || null, duration: Math.round(engine.duration || s.dur || 0) }; }
  function lastfmTick(t) {
    const sc = S.scrob; if (!sc || sc.done || !S.current || S.current.id !== sc.id) return;
    if (sc.lastT !== null) { const d = t - sc.lastT; if (d > 0 && d < 2) sc.played += d; }
    sc.lastT = t;
    const dur = engine.duration || S.current.dur || 0;
    if (dur > 30 && (sc.played >= dur / 2 || sc.played >= 240)) {
      sc.done = true;
      Bridge.fire('lastfmScrobble', JSON.stringify({ ...lastfmPayload(S.current), timestamp: sc.started }));
    }
  }
  function paintLyricsStore() {
    const n = el('s-lystatus'); if (!n) return;
    const l = S.lyricsStore || {};
    const b = el('s-lydl'); if (b) b.disabled = !!l.busy;
    if (l.busy) { n.textContent = l.t ? `refreshing… ${fmtInt(l.n || 0)} / ${fmtInt(l.t)}` : 'refreshing…'; return; }
    const total = Math.max(l.user || 0, l.bundled || 0);
    const parts = [total ? `built in for ${fmtInt(total)} songs, they keep working even if the site goes down` : 'nothing saved yet'];
    if (l.synced) parts.push(`refreshed ${fmtRelative(l.synced * 1000)}`);
    if (l.error) parts.push('last refresh failed: ' + l.error);
    n.textContent = parts.join(' · ');
  }
  function paintLastfm() {
    const n = el('s-lfstatus'); if (!n) return;
    const l = S.lastfm || {};
    n.textContent = 'status: ' + (l.error ? l.error : !l.ready ? 'enter your api key and shared secret' : l.connected ? `connected as ${l.user}` : l.pending ? 'waiting for you to press allow on last.fm…' : 'not connected');
    const c = el('s-lfconnect'), f = el('s-lffinish'), d = el('s-lfdisc');
    if (c) c.classList.toggle('hidden', !!l.connected);
    if (f) f.classList.toggle('hidden', !l.pending || !!l.connected);
    if (d) d.classList.toggle('hidden', !l.connected);
  }

  let presTimer = 0, presLast = null;
  function pushPresence(force) {
    clearTimeout(presTimer);
    presTimer = setTimeout(() => {
      const s = S.current;
      if (!s || engine.state === 'idle') { Bridge.fire('presence', ''); return; }
      const playing = engine.state === 'playing' || engine.state === 'loading';
      const ck = U.coverEraKey(s);
      const override = ck && window.__discordArt && window.__discordArt[ck];
      let art = '';
      if (override && /^https:\/\//i.test(override)) {
        art = override;
      } else {
        const remote = U.remoteImageUrl(s);
        if (remote) art = `${U.SITE}/_next/image?url=${encodeURIComponent(remote)}&w=1080&q=90`;
      }
      Bridge.fire('presence', JSON.stringify({ title: s.nm, artist: s.author, album: s.era || catName(s.cat) || '999 player', image: art, pos: engine.currentTime, dur: engine.duration || s.dur || 0, playing }));
    }, force ? 40 : 500);
  }
  function togglePlay() { if (!S.current) { if (S.list && S.list.items.length) playFrom(S.list.items, 0, S.list.ctxKey); else if (S.songs.length) playFrom(S.songs, 0, 'all'); return; } engine.toggle(); }
  function next(auto) {
    if (!S.queue.length) return;
    if (auto && S.repeat === 'one') { engine.seek(0); engine.play(); return; }
    let ni = S.qIndex + 1;
    if (ni >= S.queue.length) {
      if (S.repeat === 'all' || !auto) ni = 0;
      else { engine.pause(); engine.seek(0); return; }
    }
    S.qIndex = ni; playSong(S.queue[ni]);
  }
  function prev() {
    if (!S.queue.length) return;
    if (engine.currentTime > 3 || S.qIndex <= 0) { engine.seek(0); return; }
    S.qIndex--; playSong(S.queue[S.qIndex]);
  }
  function playNext(id) { if (S.qIndex < 0) { S.queue = [id]; S.queueSource = [id]; S.qIndex = 0; playSong(id); return; } S.queue.splice(S.qIndex + 1, 0, id); S.queueSource.push(id); toast('playing next'); renderQueueIfOpen(); }
  function addToQueue(id) { if (S.qIndex < 0) { playNext(id); return; } S.queue.push(id); S.queueSource.push(id); toast('added to queue'); renderQueueIfOpen(); }
  function jumpTo(i) { if (i < 0 || i >= S.queue.length) return; S.qIndex = i; playSong(S.queue[i]); }
  function removeFromQueue(i) { if (i === S.qIndex) return; S.queue.splice(i, 1); if (i < S.qIndex) S.qIndex--; renderQueueIfOpen(); }
  function clearQueue() { const cur = S.queue[S.qIndex]; S.queue = cur ? [cur] : []; S.queueSource = S.queue.slice(); S.qIndex = cur ? 0 : -1; renderQueueIfOpen(); }

  function sweepGarbage(force) {
    if (typeof window.gc !== 'function') return;
    if (!force && !(engine.state === 'playing' || S.npvOpen)) return;
    const run = () => { try { window.gc(); } catch (e) {  } };
    if (typeof requestIdleCallback === 'function') requestIdleCallback(run, { timeout: 4000 }); else run();
  }

  let rafPending = false;
  engine.addEventListener('time', () => { if (rafPending) return; rafPending = true; requestAnimationFrame(() => { rafPending = false; paintTime(); }); });
  engine.addEventListener('state', (e) => {
    const st = e.detail;
    paintPlayState();
    highlightRows(); updateCards();
    if (lyPanel) lyPanel.setPlaying(st === 'playing');
    if (lyFull) lyFull.setPlaying(st === 'playing');
    if (st === 'playing' || st === 'paused' || st === 'idle' || st === 'ended') pushPresence();
    if (st === 'playing') { S.errStreak = 0; if (!S.playCounted && S.current) { S.playCounted = true; Bridge.fire('recordPlay', S.current.id); S.history.push({ id: S.current.id, at: Date.now() / 1000 }); S.playCounts[S.current.id] = (S.playCounts[S.current.id] || 0) + 1; } if (S.scrob && !S.scrob.np && S.current) { S.scrob.np = true; Bridge.fire('lastfmNowPlaying', JSON.stringify(lastfmPayload(S.current))); } }
    if (navigator.mediaSession) navigator.mediaSession.playbackState = st === 'playing' ? 'playing' : 'paused';
  });
  engine.addEventListener('ended', () => next(true));
  if (typeof window.gc === 'function') setInterval(() => sweepGarbage(true), 10000);
  engine.addEventListener('error', (e) => {
    toast(`couldn’t play “${S.current ? S.current.nm : 'track'}” — ${e.detail || 'unknown error'}`, 'err');
    Bridge.log('warning', `playback error for ${S.current && S.current.id}: ${e.detail}`);
    S.errStreak++;
    if (S.errStreak < 4 && S.queue.length > 1) setTimeout(() => next(true), 1200);
  });

  function setMediaSession(s) {
    if (!('mediaSession' in navigator)) return;
    try {
      const remote = U.remoteImageUrl(s);
      navigator.mediaSession.metadata = new MediaMetadata({ title: s.nm, artist: s.author, album: s.era || '999 player', artwork: remote ? [{ src: remote, sizes: '640x640', type: 'image/jpeg' }] : [] });
      navigator.mediaSession.setActionHandler('play', () => engine.play());
      navigator.mediaSession.setActionHandler('pause', () => engine.pause());
      navigator.mediaSession.setActionHandler('previoustrack', prev);
      navigator.mediaSession.setActionHandler('nexttrack', () => next());
      navigator.mediaSession.setActionHandler('seekto', (d) => engine.seek(d.seekTime));
    } catch (e) {  }
  }

  function makeSlider(root, { onInput, onChange }) {
    let dragging = false;
    const ratio = (e) => { const r = root.getBoundingClientRect(); return clamp((e.clientX - r.left) / r.width, 0, 1); };
    root.addEventListener('pointerdown', (e) => { if (e.button !== 0) return; dragging = true; root.classList.add('drag'); root.setPointerCapture(e.pointerId); const p = ratio(e); root.style.setProperty('--p', p); onInput && onInput(p); });
    root.addEventListener('pointermove', (e) => { if (!dragging) return; const p = ratio(e); root.style.setProperty('--p', p); onInput && onInput(p); });
    const end = (e) => { if (!dragging) return; dragging = false; root.classList.remove('drag'); onChange && onChange(ratio(e)); };
    root.addEventListener('pointerup', end); root.addEventListener('pointercancel', end);
    return { set(p) { if (!dragging) root.style.setProperty('--p', clamp(p, 0, 1)); }, get dragging() { return dragging; } };
  }
  function bindPlayer() {
    seekSlider = makeSlider(el('p-slider'), { onInput: (p) => { el('p-cur').textContent = fmtTime(p * engine.duration); }, onChange: (p) => engine.seek(p * engine.duration) });
    volSlider = makeSlider(el('v-slider'), { onInput: (p) => { engine.setVolume(p); if (engine.muted) engine.setMuted(false); paintVolume(); }, onChange: (p) => { setSetting('volume', p); setSetting('muted', false); } });
    el('v-slider').addEventListener('wheel', (e) => { e.preventDefault(); const v = clamp(engine.volume + (e.deltaY < 0 ? 0.05 : -0.05), 0, 1); engine.setVolume(v); volSlider.set(v); paintVolume(); setSetting('volume', v); }, { passive: false });
    el('p-play').onclick = togglePlay; el('p-next').onclick = () => next(false); el('p-prev').onclick = prev;
    el('p-shuffle').onclick = () => { S.shuffle = !S.shuffle; setSetting('shuffle', S.shuffle); paintShuffleRepeat(); reshuffleQueueKeepCurrent(); toast(S.shuffle ? 'shuffle on' : 'shuffle off'); };
    el('p-repeat').onclick = () => { S.repeat = S.repeat === 'off' ? 'all' : S.repeat === 'all' ? 'one' : 'off'; setSetting('repeat', S.repeat); paintShuffleRepeat(); toast(S.repeat === 'off' ? 'repeat off' : S.repeat === 'all' ? 'repeat all' : 'repeat one'); };
    el('p-mute').onclick = () => { engine.setMuted(!engine.muted); setSetting('muted', engine.muted); paintVolume(); };
    el('p-mute').oncontextmenu = (e) => { e.preventDefault(); e.stopPropagation(); volumeMenu(e.clientX, e.clientY); };
    el('p-like').onclick = () => S.current && toggleLike(S.current.id);
    el('p-download').onclick = () => S.current && download(S.current.id);
    el('p-lyrics').onclick = () => toggleRightTab('lyrics'); el('p-queue').onclick = () => toggleRightTab('queue'); el('p-info').onclick = () => toggleRightTab('details');
    el('p-expand').onclick = () => openNPV(!S.npvOpen);
    el('p-cover').onclick = () => openNPV(true);
    el('p-title').onclick = () => S.current && openDetails(S.current);
    el('p-sub').addEventListener('click', (e) => { const a = e.target.closest('[data-era]'); if (a && S.eras.has(a.dataset.era)) go({ name: 'era', key: a.dataset.era }); });
    el('player').addEventListener('contextmenu', (e) => { if (S.current && e.target.closest('.p-left')) { e.preventDefault(); showMenu(songMenu(S.current, {}), e.clientX, e.clientY); } });
  }
  function paintPlayer() {
    const s = S.current; const p = el('player');
    p.classList.toggle('idle', !s);
    if (!s) { el('p-title').textContent = 'nothing playing'; el('p-sub').textContent = 'pick a track to start the vault'; el('np-mini').textContent = ''; return; }
    el('p-cover').innerHTML = `${imgTag(s, 128)}<div class="exp">${I('expand')}</div>`;
    el('p-title').textContent = s.nm; el('p-title').title = s.title;
    el('p-sub').innerHTML = `${esc(s.author)}${s.eraKey ? ` · <a data-era="${esc(s.eraKey)}" href="#">${esc(s.era)}</a>` : ''}`;
    el('np-mini').textContent = `${s.nm} — ${s.author}`;
    el('p-dur').textContent = fmtTime(engine.duration || s.dur);
    paintLike(); paintPlayerDownload(); paintPlayState();
  }
  function paintLike() { const liked = S.current && S.likes.has(S.current.id); el('p-like').classList.toggle('liked', !!liked); el('p-like').title = liked ? 'remove from liked songs' : 'save to liked songs'; }
  function paintPlayerDownload() { const b = el('p-download'); if (!S.current) return; const p = S.dlp.get(S.current.id); const done = S.downloads[String(S.current.id)]; b.innerHTML = p !== undefined ? `<span class="dlp">${Math.round(p * 100)}%</span>` : I(done ? 'check' : 'download'); b.title = done ? 'downloaded (click to download again)' : 'download'; b.classList.toggle('on', !!done); }
  function paintPlayState() {
    const b = el('p-play'); const st = engine.state;
    b.classList.toggle('loading', st === 'loading');
    el('player').classList.toggle('playing', st === 'playing' || st === 'loading');
    const ic = b.querySelector('.ic'); if (ic) ic.outerHTML = I(st === 'playing' || st === 'loading' ? 'pause' : 'play');
    b.title = st === 'playing' ? 'pause' : 'play';
    el('npv-cover').classList.toggle('anim', st === 'playing');
  }
  function paintTime() {
    const t = engine.currentTime, d = engine.duration;
    if (!seekSlider.dragging) { const ct = fmtTime(t), ce = el('p-cur'); if (ce.textContent !== ct) ce.textContent = ct; seekSlider.set(d ? t / d : 0); }
    const dt = fmtTime(d), de = el('p-dur'); if (de.textContent !== dt) de.textContent = dt;
    try { const b = engine.mode === 'html5' && engine.cur.buffered; if (b && b.length && d) el('p-slider').style.setProperty('--b', clamp(b.end(b.length - 1) / d, 0, 1)); } catch (e) {  }
    if (lyPanel && S.rightOpen && S.rightTab === 'lyrics') lyPanel.update(t);
    if (lyFull && S.npvOpen) lyFull.update(t);
    if (engine.state === 'playing') {
      const now = performance.now();
      if (presLast && Math.abs((t - presLast.t) - (now - presLast.at) / 1000) > 1.5) pushPresence();
      presLast = { t, at: now };
      lastfmTick(t);
    }
  }
  function volumeMenu(x, y) {
    showMenu([], x, y, { cls: 'vol-menu' });
    const m = openMenu.el;
    const row = h('div', { class: 'vol-row' });
    row.innerHTML = `<input class="field" type="number" min="0" max="100" step="1" inputmode="numeric" value="${Math.round((engine.muted ? 0 : engine.volume) * 100)}"><span class="pct">%</span>`;
    const inp = row.querySelector('input');
    const apply = () => {
      if (inp.value === '') return;
      const n = clamp(Math.round(+inp.value || 0), 0, 100);
      engine.setVolume(n / 100); if (engine.muted && n > 0) engine.setMuted(false);
      paintVolume(); setSetting('volume', n / 100); setSetting('muted', engine.muted);
    };
    inp.oninput = apply;
    inp.onkeydown = (e) => { e.stopPropagation(); if (e.key === 'Enter' || e.key === 'Escape') { if (e.key === 'Enter') apply(); closeMenus(); } };
    m.appendChild(row);
    const presets = h('div', { class: 'vol-presets' });
    for (const n of [25, 50, 75, 100]) { const b = h('button', {}, n + '%'); b.onclick = (e) => { e.stopPropagation(); inp.value = n; apply(); closeMenus(); }; presets.appendChild(b); }
    m.appendChild(presets);
    const r = m.getBoundingClientRect();
    const bar = el('player').getBoundingClientRect();
    m.style.left = `${clamp(x - r.width / 2, 8, window.innerWidth - r.width - 8)}px`;
    m.style.top = `${clamp(bar.top - r.height - 10, 8, window.innerHeight - r.height - 8)}px`;
    inp.focus(); inp.select();
  }
  function paintVolume() { const v = engine.muted ? 0 : engine.volume; el('p-mute').innerHTML = I(v === 0 ? 'mute' : v < 0.5 ? 'volume1' : 'volume'); el('p-mute').title = engine.muted ? 'unmute' : 'mute'; volSlider.set(v); }
  function paintShuffleRepeat() { el('p-shuffle').classList.toggle('on', S.shuffle); el('p-repeat').classList.toggle('on', S.repeat !== 'off'); el('p-repeat').innerHTML = I(S.repeat === 'one' ? 'repeat1' : 'repeat'); el('p-repeat').title = `repeat: ${S.repeat}`; }
  function updateCards() { for (const c of $$('.card')) { const id = +c.dataset.id; const on = S.current && S.current.id === id; c.classList.toggle('playing', !!on); const b = c.querySelector('.play'); if (b) b.innerHTML = I(on && engine.state === 'playing' ? 'pause' : 'play'); } }

  function requestAccent(song) {
    const ref = U.localCover(song) || U.coverUrl(song, 256) || '';
    S.accentRef = ref;
    if (ref) Bridge.fire('requestAccent', ref);
  }
  function applyAccent(a) {
    const r = document.documentElement.style;
    r.setProperty('--accent-rgb', a.rgb.join(','));
    r.setProperty('--accent-2-rgb', a.rgb2.join(','));
    r.setProperty('--accent', a.hex);
  }

  const ambPairs = [{ a: 'amb-a', b: 'amb-b', flip: false, direct: true }, { a: 'npv-bg-a', b: 'npv-bg-b', flip: false, direct: false }];
  let ambUrl = '';
  function setAmbient(song) {
    const url = coverUrl(song, 640); if (!url || url === ambUrl) return; ambUrl = url;
    const img = new Image();
    img.onload = () => {
      for (const p of ambPairs) {
        const a = el(p.a), b = el(p.b); if (!a || !b) continue;
        const show = p.flip ? a : b, hide = p.flip ? b : a; p.flip = !p.flip;
        if (p.direct) show.style.backgroundImage = `url('${url}')`; else show.style.setProperty('--art', `url('${url}')`);
        show.classList.add('show'); hide.classList.remove('show');
      }
    };
    img.src = url;
  }

  function toggleRight(open) { S.rightOpen = open === undefined ? !S.rightOpen : open; el('workspace').classList.toggle('right-closed', !S.rightOpen); setSetting('rightPanelOpen', S.rightOpen); paintPanelButtons(); if (S.rightOpen) renderRight(); setTimeout(() => S.list && S.list.vl && S.list.vl._schedule(true), 300); }
  function toggleRightTab(tab) { if (S.rightOpen && S.rightTab === tab) { toggleRight(false); return; } S.rightTab = tab; setSetting('rightPanel', tab); if (!S.rightOpen) toggleRight(true); else renderRight(); }
  function paintPanelButtons() { for (const [k, id] of [['lyrics', 'p-lyrics'], ['queue', 'p-queue'], ['details', 'p-info']]) el(id).classList.toggle('on', S.rightOpen && S.rightTab === k); }
  function renderRight() {
    paintPanelButtons();
    el('right-title').textContent = { lyrics: 'lyrics', queue: 'queue', details: 'details' }[S.rightTab] || 'lyrics';
    const body = el('right-body'); body.innerHTML = '';
    if (S.rightTab === 'lyrics') {
      const s = S.current;
      if (s) { const np = h('div', { class: 'panel-np' }); np.innerHTML = `${imgTag(s, 128)}<div style="min-width:0"><div class="t">${esc(s.nm)}</div><div class="s">${esc(s.author)}${s.era ? ' · ' + esc(s.era) : ''}</div></div>`; body.appendChild(np); }
      if (!lyPanel) { const d = h('div'); lyPanel = new Lyrics.LyricsView(d, { onSeek: (t) => engine.seek(t) }); }
      body.appendChild(lyPanel.el);
      if (!s) lyPanel.setEmpty('nothing playing', 'lyrics appear here when a track is playing.');
      else if (S.lyFor !== s.id) { lyPanel.setEmpty('loading lyrics…'); }
      else applyLyricsTo(lyPanel);
      lyPanel.update(engine.currentTime);
    } else if (S.rightTab === 'queue') renderQueue(body);
    else renderDetails(body, S.detailTarget || S.current);
  }
  function renderQueueIfOpen() { if (S.rightOpen && S.rightTab === 'queue') renderRight(); }
  function renderQueue(body) {
    const q = h('div', { class: 'queue' });
    if (!S.queue.length) { q.innerHTML = `<div class="ly-empty">${I('queue')}<div class="ly-empty-t">queue is empty</div><div class="ly-empty-s">play something, or right-click a track → add to queue.</div></div>`; body.appendChild(q); return; }
    const cur = S.queue[S.qIndex];
    const row = (id, i, on) => { const s = S.byId.get(id); if (!s) return ''; return `<div class="qrow ${on ? 'on' : ''}" data-i="${i}">${imgTag(s, 64)}<div style="min-width:0"><div class="t">${esc(s.nm)}</div><div class="s">${esc(s.author)}${s.era ? ' · ' + esc(s.era) : ''}</div></div>${on ? `<span></span>` : `<button class="btn-icon xs plain x" data-x="${i}" title="remove">${I('close')}</button>`}</div>`; };
    const upcoming = S.queue.slice(S.qIndex + 1, S.qIndex + 1 + 200);
    q.innerHTML = `<div class="qh"><span>now playing</span></div>${cur ? row(cur, S.qIndex, true) : ''}<div class="qh"><span>next up · ${fmtInt(S.queue.length - S.qIndex - 1)}</span><button class="btn sm ghost" id="q-clear">clear</button></div>${upcoming.map((id, k) => row(id, S.qIndex + 1 + k, false)).join('')}${S.queue.length - S.qIndex - 1 > 200 ? `<div class="qh">…and ${fmtInt(S.queue.length - S.qIndex - 201)} more</div>` : ''}`;
    q.addEventListener('click', (e) => { const x = e.target.closest('[data-x]'); if (x) { removeFromQueue(+x.dataset.x); return; } const r = e.target.closest('.qrow'); if (r && !r.classList.contains('on')) jumpTo(+r.dataset.i); });
    q.querySelector('#q-clear').onclick = () => { clearQueue(); toast('queue cleared'); };
    body.appendChild(q);
  }
  function kvRows(pairs) { return `<div class="kv">${pairs.map(([k, v]) => `<div class="k">${esc(k)}</div><div class="v ${v ? '' : 'nd'}">${v ? esc(v) : 'not documented'}</div>`).join('')}</div>`; }
  function renderDetails(body, s) {
    const d = h('div', { class: 'details' });
    if (!s) { d.innerHTML = `<div class="ly-empty">${I('info')}<div class="ly-empty-t">no track selected</div><div class="ly-empty-s">play a song or open details from any list.</div></div>`; body.appendChild(d); return; }
    const det = S.detailCache.get(s.id);
    const alt = (det && det.alt && det.alt.length ? det.alt : s.alt) || [];
    const sub = (det && det.disp) || (s.sub && U.SUB_LABEL[s.sub]) || null;
    d.innerHTML = `${imgTag(s, 640, 'big')}<h2>${esc(s.title)}</h2><div class="by">${esc(s.author)}${s.era ? ' · ' + esc(s.era) : ''} · ${esc(catName(s.cat))}${sub ? ' · ' + esc(String(sub).toLowerCase()) : ''}</div>
      ${alt.length ? `<div class="aka"><b>also known as</b> ${esc(alt.join(', '))}</div>` : ''}
      <div class="actions"></div>
      <div class="sec"><h4>credits</h4>${kvRows([['artist', s.author], ['producers', (det && det.prod) || s.prod], ['engineers', (det && det.eng) || s.eng]])}</div>
      <div class="sec"><h4>recording</h4>${kvRows([['era', s.era], ['recorded', (det && det.rec) || s.rec], ['location', (det && det.loc) || s.loc]])}</div>
      <div class="sec"><h4>track history</h4>${kvRows([['previewed', (det && det.prev) || s.prev], ['leaked', (det && det.leaked) || s.leaked], ['released', (det && det.rel) || s.rel], ['added to vault', fmtDate(s.created)]])}</div>
      <div class="sec"><h4>audio & archive</h4>${kvRows([['duration', s.len || fmtTime(s.dur)], ['format', U.ext(s)], ['leak type', (det && det.leakType) || s.leakType], ['bitrate', det && det.bitrate ? String(det.bitrate) : null], ['instrumentals', det && det.instrumental ? String(det.instrumental) : null], ['source', (det && det.src) || s.src], ['uploaded by', (det && det.up) || s.up], ['weekly plays', fmtInt(s.plays)], ['lyrics', s.lyr ? (s.lyrSrc ? `from vault · ${s.lyrSrc.title}` : s.wt ? 'synced · word timing' : 'synced') : 'none yet']])}</div>`;
    const a = d.querySelector('.actions');
    const pl = h('button', { class: 'btn primary sm' }); pl.innerHTML = I('play') + 'play'; pl.onclick = () => playFrom([s], 0, 'details');
    const lk = h('button', { class: 'btn sm' }); lk.innerHTML = I('heart') + (S.likes.has(s.id) ? 'liked' : 'like'); lk.onclick = () => { toggleLike(s.id); lk.innerHTML = I('heart') + (S.likes.has(s.id) ? 'liked' : 'like'); };
    const dl = h('button', { class: 'btn sm' }); dl.innerHTML = I('download') + 'download'; dl.onclick = () => download(s.id);
    const ad = h('button', { class: 'btn sm ghost' }); ad.innerHTML = I('plus') + 'playlist'; ad.onclick = () => addToPlaylistFlow([s.id]);
    a.append(pl, lk, dl, ad);
    body.appendChild(d);
    if (!S.detailCache.has(s.id)) loadDetail(s.id).then(() => { if (S.rightTab === 'details' && (S.detailTarget || S.current) === s) renderRight(); });
  }
  function openDetails(s) { S.detailTarget = s; S.rightTab = 'details'; setSetting('rightPanel', 'details'); if (!S.rightOpen) toggleRight(true); else renderRight(); }

  function loadDetail(id) {
    if (S.detailCache.has(id)) return Promise.resolve(S.detailCache.get(id));
    return new Promise((resolve) => { const w = S.detailWaiters.get(id); if (w) { w.push(resolve); return; } S.detailWaiters.set(id, [resolve]); Bridge.fire('getDetail', id); setTimeout(() => { const ww = S.detailWaiters.get(id); if (ww) { S.detailWaiters.delete(id); ww.forEach((r) => r(null)); } }, 20000); });
  }
  async function loadDetailFor(song) {
    S.lyFor = null; S.lyParsed = null;
    if (!song.lyr) { S.lyFor = song.id; S.lyParsed = null; applyLyricsTo(lyPanel); applyLyricsTo(lyFull); sweepGarbage(true); return; }
    const d = await loadDetail(song.lyrSrc ? song.lyrSrc.id : song.id);
    if (!S.current || S.current.id !== song.id) return;
    S.lyFor = song.id;
    S.lyParsed = d && d.lyrics ? Lyrics.parseLRC(d.lyrics) : null;
    S.lyMeta = d ? { offsetMs: d.offsetMs || 0, estimated: !!d.estimated, words: d.words, from: song.lyrSrc ? song.lyrSrc.title : null } : {};
    applyLyricsTo(lyPanel); applyLyricsTo(lyFull);
    sweepGarbage(true);
    if (S.rightTab === 'details' && !S.detailTarget) renderRight();
  }
  function applyLyricsTo(view) {
    if (!view) return;
    const s = S.current;
    if (!s) { view.setEmpty('nothing playing', 'lyrics appear here when a track is playing.'); return; }
    if (S.lyFor !== s.id) { view.setEmpty('loading lyrics…'); return; }
    if (!S.lyParsed || !S.lyParsed.lines.length) { view.setEmpty('no lyrics for this one yet', s.lyr ? 'the vault lists lyrics but they could not be loaded.' : s.local ? 'no vault song with lyrics matches this file’s title.' : 'the vault hasn’t imported lyrics for this track.'); return; }
    view.setData(S.lyParsed, S.lyMeta || {});
    view.update(engine.currentTime);
    view.setPlaying(engine.state === 'playing');
  }

  function openNPV(open) {
    S.npvOpen = !!open;
    el('npv').classList.toggle('open', S.npvOpen);
    document.body.classList.toggle('npv-open', S.npvOpen);
    el('p-expand').innerHTML = I(S.npvOpen ? 'collapse' : 'expand');
    if (S.npvOpen) { paintNPV(); if (lyFull) { applyLyricsTo(lyFull); lyFull.update(engine.currentTime); } }
  }
  function paintNPV() {
    const s = S.current; if (!s) return;
    if (!lyFull) { lyFull = new Lyrics.LyricsView(el('npv-lyrics'), { onSeek: (t) => engine.seek(t), mode: 'full' }); }
    const cov = el('npv-cover'); const url = coverUrl(s, 1080); if (url) { cov.src = url; cov.style.visibility = ''; } else cov.style.visibility = 'hidden';
    el('npv-title').textContent = s.nm; el('npv-by').textContent = [s.author, s.era, catName(s.cat)].filter(Boolean).join(' · ');
    if (S.npvOpen) applyLyricsTo(lyFull);
  }

  function toggleLike(id) {
    const liked = !S.likes.has(id);
    if (liked) { S.likes.add(id); S.likedAt[id] = Date.now() / 1000; } else { S.likes.delete(id); delete S.likedAt[id]; }
    Bridge.fire('setLiked', id, liked);
    refreshRow(id); paintLike(); renderSidebar();
    if (S.route && S.route.name === 'liked') renderView(S.route, scroller.scrollTop);
    toast(liked ? 'added to liked songs' : 'removed from liked songs', liked ? 'ok' : '');
  }
  function download(id) {
    const ls = S.byId.get(id); if (ls && ls.local) { Bridge.fire('revealFile', ls.path); return; }
    if (S.dlp.has(id)) return;
    S.dlp.set(id, 0); refreshRow(id); if (S.current && S.current.id === id) paintPlayerDownload();
    Bridge.fire('download', id, U.localCover(S.byId.get(id)) || '');
  }
  async function createPlaylistFlow(ids) {
    const name = await promptModal('new playlist', 'playlist name', `my playlist #${S.playlists.length + 1}`);
    if (!name) return;
    const json = await Bridge.call('createPlaylist', name, JSON.stringify(ids || []));
    try { const pl = JSON.parse(json); S.playlists.push(pl); renderSidebar(); toast(`created “${pl.name}”`, 'ok'); go({ name: 'playlist', id: pl.id }); } catch (e) { toast('could not create playlist', 'err'); }
  }
  async function updatePlaylist(pid, changes) {
    const json = await Bridge.call('updatePlaylist', pid, JSON.stringify(changes));
    if (!json) return;
    const pl = JSON.parse(json); const i = S.playlists.findIndex((p) => p.id === pid); if (i >= 0) S.playlists[i] = pl;
    renderSidebar();
    if (S.route && S.route.name === 'playlist' && S.route.id === pid) renderView(S.route, scroller.scrollTop);
    return pl;
  }
  async function addToPlaylistFlow(ids) {
    const pick = await listModal('add to playlist', S.playlists.map((p) => ({ id: p.id, label: p.name, sub: `${p.songs.length} tracks`, on: ids.every((id) => p.songs.includes(id)) })), { createLabel: 'new playlist' });
    if (pick === '__new') return createPlaylistFlow(ids);
    if (!pick) return;
    const pl = S.playlists.find((p) => p.id === pick); if (!pl) return;
    const add = ids.filter((id) => !pl.songs.includes(id));
    if (!add.length) { toast('already in that playlist'); return; }
    await updatePlaylist(pick, { add });
    toast(`added to “${pl.name}”`, 'ok');
  }
  async function deletePlaylistFlow(pl) {
    if (!(await confirmModal('delete playlist?', `“${pl.name}” will be removed. your songs stay in the vault.`, 'delete'))) return;
    await Bridge.call('deletePlaylist', pl.id);
    S.playlists = S.playlists.filter((p) => p.id !== pl.id); renderSidebar();
    if (S.route && S.route.name === 'playlist' && S.route.id === pl.id) go({ name: 'home' }, { replace: true });
    toast('playlist deleted');
  }
  function playlistMenu(pl) {
    return [
      { label: 'play', icon: 'play', action: () => { const items = pl.songs.map((id) => S.byId.get(id)).filter(Boolean); if (items.length) playFrom(items, 0, 'pl:' + pl.id); } },
      { label: 'shuffle', icon: 'shuffle', action: () => { const items = pl.songs.map((id) => S.byId.get(id)).filter(Boolean); if (items.length) { S.shuffle = true; setSetting('shuffle', true); paintShuffleRepeat(); playFrom(items, Math.floor(Math.random() * items.length), 'pl:' + pl.id); } } },
      { sep: true },
      { label: 'rename', icon: 'edit', action: async () => { const name = await promptModal('rename playlist', 'playlist name', pl.name); if (name && name !== pl.name) updatePlaylist(pl.id, { name }); } },
      { label: 'download all', icon: 'download', action: () => { let n = 0; for (const id of pl.songs) if (!S.downloads[String(id)]) { download(id); n++; } toast(n ? `downloading ${n} tracks` : 'everything is already downloaded'); } },
      { sep: true },
      { label: 'hide from sidebar', icon: 'eyeOff', action: () => hideCollectionItem('pl:' + pl.id) },
      { label: 'delete playlist', icon: 'trash', danger: true, action: () => deletePlaylistFlow(pl) },
    ];
  }
  function songMenu(s, { items, index, removable } = {}) {
    if (!s) return [];
    const inQueue = S.current && S.current.id === s.id;
    return [
      { header: s.nm },
      { label: inQueue ? (engine.state === 'playing' ? 'pause' : 'play') : 'play', icon: inQueue && engine.state === 'playing' ? 'pause' : 'play', action: () => { if (inQueue) togglePlay(); else if (items) playFrom(items, index, S.list ? S.list.ctxKey : 'menu'); else playFrom([s], 0, 'menu'); } },
      { label: 'play next', icon: 'zap', action: () => playNext(s.id) },
      { label: 'add to queue', icon: 'queue', action: () => addToQueue(s.id) },
      { sep: true },
      { label: S.likes.has(s.id) ? 'remove from liked songs' : 'save to liked songs', icon: 'heart', action: () => toggleLike(s.id) },
      { label: 'add to playlist', icon: 'plus', action: () => addToPlaylistFlow([s.id]) },
      removable ? { label: 'remove from this playlist', icon: 'close', action: () => updatePlaylist(removable, { remove: [s.id] }) } : null,
      { label: S.downloads[String(s.id)] ? 'download again' : 'download', icon: 'download', action: () => download(s.id) },
      S.downloads[String(s.id)] ? { label: 'show file in explorer', icon: 'folder', action: () => Bridge.fire('revealFile', S.downloads[String(s.id)].path) } : null,
      { sep: true },
      s.eraKey && S.eras.has(s.eraKey) ? { label: `go to era · ${s.eraKey}`, icon: 'layers', action: () => go({ name: 'era', key: s.eraKey }) } : null,
      { label: 'track details', icon: 'info', action: () => openDetails(s) },
      { label: 'copy title', icon: 'copy', action: () => { Bridge.fire('copyText', `${s.author} - ${s.title}`); toast('copied'); } },
      { label: 'copy stream link', icon: 'link', action: () => { Bridge.fire('copyText', U.audioUrl(s, true)); toast('stream link copied'); } },
    ].filter(Boolean);
  }

  let openMenu = null;
  function closeMenus() { if (openMenu) { openMenu.el.remove(); openMenu.onClose && openMenu.onClose(); openMenu = null; } }
  function showMenu(items, x, y, { onClose, cls } = {}) {
    closeMenus();
    const m = h('div', { class: 'menu ' + (cls || '') });
    for (const it of items) {
      if (!it) continue;
      if (it.sep) { m.appendChild(h('div', { class: 'sep' })); continue; }
      if (it.header) { m.appendChild(h('div', { class: 'mh' }, it.header)); continue; }
      const b = h('button', { class: `mi ${it.danger ? 'danger' : ''} ${it.check ? 'check' : ''} ${it.on ? 'on' : ''}` });
      b.innerHTML = `${it.icon ? I(it.icon) : ''}<span>${esc(it.label)}</span>${it.sub ? `<span class="sub">${esc(it.sub)}</span>` : ''}`;
      b.onclick = (e) => { e.stopPropagation(); closeMenus(); it.action && it.action(); };
      m.appendChild(b);
    }
    document.body.appendChild(m);
    const r = m.getBoundingClientRect();
    m.style.left = `${clamp(x, 8, window.innerWidth - r.width - 8)}px`;
    m.style.top = `${clamp(y, 8, window.innerHeight - r.height - 8)}px`;
    openMenu = { el: m, onClose, t: performance.now() };
  }
  function modal(buildFn) {
    return new Promise((resolve) => {
      const root = el('modal-root'); root.innerHTML = ''; root.classList.add('open');
      const box = h('div', { class: 'modal' });
      const done = (v) => { root.classList.remove('open'); root.innerHTML = ''; resolve(v); };
      buildFn(box, done);
      root.appendChild(box);
      root.onclick = (e) => { if (e.target === root) done(null); };
      const esc_ = (e) => { if (e.key === 'Escape') { done(null); document.removeEventListener('keydown', esc_); } };
      document.addEventListener('keydown', esc_);
      const f = box.querySelector('input'); if (f) { f.focus(); f.select(); }
    });
  }
  function promptModal(title, label, value) {
    return modal((box, done) => {
      box.innerHTML = `<h3>${esc(title)}</h3><input class="field" type="text" placeholder="${esc(label)}" value="${esc(value || '')}" maxlength="80"><div class="foot"><button class="btn ghost" data-a="cancel">cancel</button><button class="btn primary" data-a="ok">save</button></div>`;
      const inp = box.querySelector('input');
      box.querySelector('[data-a="cancel"]').onclick = () => done(null);
      box.querySelector('[data-a="ok"]').onclick = () => done(inp.value.trim() || null);
      inp.onkeydown = (e) => { if (e.key === 'Enter') done(inp.value.trim() || null); };
    });
  }
  function confirmModal(title, text, okLabel) {
    return modal((box, done) => {
      box.innerHTML = `<h3>${esc(title)}</h3><p>${esc(text)}</p><div class="foot"><button class="btn ghost" data-a="cancel">cancel</button><button class="btn primary danger" data-a="ok">${esc(okLabel || 'ok')}</button></div>`;
      box.querySelector('[data-a="cancel"]').onclick = () => done(false);
      box.querySelector('[data-a="ok"]').onclick = () => done(true);
    });
  }
  function listModal(title, items, { createLabel } = {}) {
    return modal((box, done) => {
      box.innerHTML = `<h3>${esc(title)}</h3><div class="list">${createLabel ? `<button class="mi" data-id="__new">${I('plus')}<span class="n">${esc(createLabel)}</span></button>` : ''}${items.map((it) => `<button class="mi ${it.on ? 'in' : ''}" data-id="${esc(it.id)}">${I(it.on ? 'check' : 'music')}<span class="n">${esc(it.label)}</span><span class="c">${esc(it.sub || '')}</span></button>`).join('')}${!items.length ? `<p style="padding:8px 12px">no playlists yet — create your first one.</p>` : ''}</div><div class="foot"><button class="btn ghost" data-a="cancel">cancel</button></div>`;
      box.querySelector('[data-a="cancel"]').onclick = () => done(null);
      box.querySelectorAll('.mi').forEach((b) => (b.onclick = () => done(b.dataset.id)));
    });
  }
  function toast(msg, kind, ms = 2600) {
    const t = h('div', { class: `toast ${kind || ''}` }); t.innerHTML = `${I(kind === 'ok' ? 'check' : kind === 'err' ? 'info' : 'music')}<span>${esc(msg)}</span>`;
    const root = el('toasts'); root.appendChild(t);
    while (root.children.length > 3) root.firstChild.remove();
    setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 260); }, ms);
  }

  function updateCardHTML() {
    const u = S.update || {}, st = S.settings, cur = u.current || S.app.version || 'dev';
    const pct = u.total ? Math.min(100, Math.round((u.done || 0) / u.total * 100)) : 0;
    const when = u.checked ? `checked ${fmtRelative(u.checked * 1000)}` : '';
    const text = {
      idle: 'looks for new versions on its own',
      checking: 'checking…',
      none: ['you have the latest version', when].filter(Boolean).join(' · '),
      available: `999 player ${u.version} is out`,
      downloading: `downloading 999 player ${u.version}${u.total ? ` · ${pct}%` : ''}`,
      ready: `999 player ${u.version} is downloaded, it installs next time you open the app`,
      installing: 'handing over to setup…',
      error: u.error || 'something went wrong',
    }[u.state] || '';
    const btn = { idle: 'check for updates', none: 'check again', error: 'try again', available: 'update now', ready: 'restart to update' }[u.state];
    const notes = (u.state === 'available' || u.state === 'ready') && u.notes ? `<div class="upd-notes">${esc(u.notes.slice(0, 1200))}</div>` : '';
    const bar = u.state === 'downloading' ? `<div class="upd-bar"><i style="width:${pct}%"></i></div>` : '';
    return `<h3>updates</h3>
      <div class="set-row"><div class="l"><div class="t">version ${esc(cur)}</div><div class="d" id="s-upd">${esc(text)}</div>${bar}${notes}</div>${btn ? `<button class="btn sm ${u.state === 'available' || u.state === 'ready' ? 'primary' : ''}" id="s-upbtn">${I(u.state === 'ready' ? 'refresh' : 'download')}${btn}</button>` : ''}</div>
      <div class="set-row"><div class="l"><div class="t">download updates automatically</div><div class="d">new versions download in the background and install next time you open the app</div></div><button class="switch ${st.autoUpdate !== false ? 'on' : ''}" id="s-upauto"></button></div>`;
  }
  function bindUpdateCard(root) {
    const card = root.querySelector('#s-upcard'); if (!card) return;
    const b = card.querySelector('#s-upbtn');
    if (b) b.onclick = () => { const st = (S.update || {}).state; if (st === 'available' || st === 'ready') { Bridge.fire('installUpdate'); toast(st === 'ready' ? 'closing to update…' : 'downloading the update…'); } else Bridge.fire('checkUpdates'); };
    card.querySelector('#s-upauto').onclick = (e) => { const on = !e.currentTarget.classList.contains('on'); e.currentTarget.classList.toggle('on', on); setSetting('autoUpdate', on); };
  }
  function paintUpdate(prev) {
    const u = S.update || {}, st = u.state;
    const tb = el('tb-settings'); if (tb) tb.classList.toggle('dot', st === 'available' || st === 'ready');
    const card = el('s-upcard');
    if (card) { card.innerHTML = updateCardHTML(); bindUpdateCard(card.parentNode); }
    if (prev && prev.state !== st && st === 'error' && u.error) toast(u.error, 'err', 4000);
    if (prev && prev.state !== st && st === 'none' && prev.state === 'checking' && S.route && S.route.name === 'settings') toast('you have the latest version', 'ok');
  }

  function bindKeyboard() {
    document.addEventListener('keydown', (e) => {
      const tag = (e.target.tagName || '').toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || e.target.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'f')) { e.preventDefault(); el('search').focus(); el('search').select(); return; }
      if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); back(); return; }
      if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); forward(); return; }
      if (e.key === 'Escape') { if (openMenu) closeMenus(); else if (S.npvOpen) openNPV(false); return; }
      if (typing) return;
      switch (e.key) {
        case ' ': e.preventDefault(); togglePlay(); break;
        case 'ArrowRight': e.preventDefault(); if (e.shiftKey) next(); else engine.seek(engine.currentTime + 5); break;
        case 'ArrowLeft': e.preventDefault(); if (e.shiftKey) prev(); else engine.seek(engine.currentTime - 5); break;
        case 'ArrowUp': e.preventDefault(); { const v = clamp(engine.volume + 0.05, 0, 1); engine.setVolume(v); paintVolume(); setSetting('volume', v); } break;
        case 'ArrowDown': e.preventDefault(); { const v = clamp(engine.volume - 0.05, 0, 1); engine.setVolume(v); paintVolume(); setSetting('volume', v); } break;
        case 'm': case 'M': el('p-mute').click(); break;
        case 'l': case 'L': toggleRightTab('lyrics'); break;
        case 'q': case 'Q': toggleRightTab('queue'); break;
        case 'i': case 'I': toggleRightTab('details'); break;
        case 'f': case 'F': openNPV(!S.npvOpen); break;
        case 's': case 'S': el('p-shuffle').click(); break;
        case 'r': case 'R': el('p-repeat').click(); break;
        case 'h': case 'H': if (S.current) toggleLike(S.current.id); break;
        case 'd': case 'D': if (S.current) download(S.current.id); break;
        default: break;
      }
    });
  }

  async function selftest() {
    const res = { ok: false, bridge: Bridge.connected, songs: S.songs.length, canPlay: engine.canPlay(), steps: [] };
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    try {
      engine.setVolume(0.02);
      const mp3 = S.songs.find((s) => U.ext(s) === 'mp3');
      if (mp3) { playFrom([mp3], 0, 'selftest'); await wait(5000); res.steps.push({ engine: 'html5', song: mp3.id, state: engine.state, t: engine.currentTime, mode: engine.mode }); }
      const m4a = S.songs.find((s) => U.ext(s) === 'm4a');
      if (m4a) { playFrom([m4a], 0, 'selftest'); await wait(6000); res.steps.push({ engine: 'native', song: m4a.id, state: engine.state, t: engine.currentTime, mode: engine.mode }); }
      const lyr = S.songs.find((s) => s.lyr && s.wt);
      if (lyr) { const d = await loadDetail(lyr.id); res.detail = { id: lyr.id, hasLyrics: !!(d && d.lyrics), words: d && d.words ? d.words.length : 0, lines: d && d.lyrics ? Lyrics.parseLRC(d.lyrics).lines.length : 0 }; }
      engine.stop();
      res.ok = res.songs > 0 && res.steps.length > 0 && res.steps.every((s) => s.t > 0.5);
    } catch (e) { res.error = String(e); }
    window.__selftestResult = res;
  }

  window.app = { S, go, back, playSong, playFrom, next, prev, togglePlay, openNPV, toggleRight, toggleRightTab, toast, engine, openDetails, showMenu };
})();
