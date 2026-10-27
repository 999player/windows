/* LRC parsing, word-timing alignment and an Apple Music–style synced lyrics renderer.
   Motion model: every line is translated by a shared --ty variable and transitions on its own
   compositor layer with a per-line delay (the cascade), while the active line's words fill with a
   feathered gradient updated every frame. Long instrumental gaps show interlude dots. */
(function () {
  'use strict';

  const TS = /\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/g;
  const META = /^\[(ar|al|ti|au|by|offset|re|ve|length|tool|id):([^\]]*)\]$/i;
  const HEADER = /^\[[^\]\d][^\]]*\]$/;
  const GAP_MIN = 5;
  const LINE_MAX = 5.5;

  function parseLRC(text) {
    const out = { lines: [], timed: false, offset: 0 };
    if (!text) return out;
    for (const raw of text.split('\n')) {
      let line = raw.trim();
      if (!line) continue;
      const meta = META.exec(line);
      if (meta) { if (meta[1].toLowerCase() === 'offset') out.offset = parseInt(meta[2], 10) || 0; continue; }
      const times = [];
      line = line.replace(TS, (_, m, s, f) => { times.push(parseInt(m, 10) * 60 + parseInt(s, 10) + (f ? parseInt(f.padEnd(3, '0').slice(0, 3), 10) / 1000 : 0)); return ''; }).trim();
      const isHeader = HEADER.test(line);
      if (!line && times.length) { out.lines.push({ t: times[0], text: '', kind: 'instrumental' }); out.timed = true; continue; }
      if (times.length) { out.timed = true; for (const t of times) out.lines.push({ t, text: line, kind: isHeader ? 'header' : 'line' }); }
      else out.lines.push({ t: null, text: line, kind: isHeader ? 'header' : 'line' });
    }
    return out;
  }

  const norm = (s) => s.toLowerCase().replace(/[^a-z0-9']+/g, '');

  /** Feathered fill edge that stays fully inside the word: unsung words are entirely dim, sung words entirely bright. */
  function setFill(el, p) {
    const F = 9;
    let a, b;
    if (p <= 0) { a = 0; b = 0; } else if (p >= 100) { a = 100; b = 100; } else { a = Math.max(0, p - F); b = Math.min(100, p + F); }
    const va = `${a.toFixed(1)}%`, vb = `${b.toFixed(1)}%`;
    const st = el.style;
    if (st.getPropertyValue('--pa') !== va) st.setProperty('--pa', va);
    if (st.getPropertyValue('--pb') !== vb) st.setProperty('--pb', vb);
  }

  function attachWords(parsed, words) {
    if (!parsed || !words || !words.length) return false;
    const seq = words.map((w) => ({ s: w[0], e: w[1], text: String(w[2] || '') }));
    let wi = 0, matched = 0, total = 0;
    for (const line of parsed.lines) {
      if (line.kind !== 'line' || line.t === null) continue;
      const toks = line.text.split(/\s+/).filter(Boolean);
      total += toks.length;
      const lineWords = [];
      for (let ti = 0; ti < toks.length; ti++) {
        let found = -1;
        const key = norm(toks[ti]);
        if (key) for (let k = wi; k < Math.min(seq.length, wi + 14); k++) { if (norm(seq[k].text) === key) { found = k; break; } }
        if (found === -1) { lineWords.push({ text: toks[ti], s: null, e: null }); continue; }
        wi = found + 1; matched++;
        lineWords.push({ text: toks[ti], s: seq[found].s, e: seq[found].e });
      }
      let prev = line.t;
      for (let i = 0; i < lineWords.length; i++) {
        if (lineWords[i].s === null) {
          const next = lineWords.slice(i + 1).find((w) => w.s !== null);
          const end = next ? next.s : prev + 0.3;
          lineWords[i].s = prev; lineWords[i].e = Math.max(prev + 0.05, end);
        }
        prev = lineWords[i].e;
      }
      line.words = lineWords;
    }
    const ok = total > 0 && matched / total > 0.6;
    if (!ok) for (const l of parsed.lines) delete l.words;
    return ok;
  }

  class LyricsView {
    constructor(container, { onSeek, mode = 'panel' } = {}) {
      this.el = container;
      this.onSeek = onSeek;
      this.mode = mode;
      this.el.classList.add('lyx', `lyx-${mode}`);
      this.inner = document.createElement('div'); this.inner.className = 'lyx-inner';
      this.el.appendChild(this.inner);
      this.items = [];
      this.active = -1;
      this.playing = false;
      this.baseT = 0; this.baseAt = 0;
      this.offset = 0;
      this.scrollY = 0;
      this.browseTimer = 0;
      this.data = null;
      this._raf = 0;
      this._nowEl = null;
      this._ro = new ResizeObserver(() => this._layout(true));
      this._ro.observe(this.el);
      this.el.addEventListener('wheel', (e) => this._onWheel(e), { passive: false });
      this.el.addEventListener('click', (e) => {
        const p = e.target.closest('.lx'); if (!p) return;
        const it = this.items[+p.dataset.i];
        if (it && it.t !== null && this.onSeek) { this._endBrowse(false); this.onSeek(Math.max(0, it.t + this.offset)); }
      });
    }

    destroy() { this._ro.disconnect(); if (this._raf) cancelAnimationFrame(this._raf); clearTimeout(this.browseTimer); }

    setEmpty(message, sub) {
      this.data = null; this.items = []; this.active = -1; this._nowEl = null;
      this.el.classList.remove('timed', 'browsing');
      this.data = null; this.items = []; this._words = null; this._nowEl = null;
      this.inner.innerHTML = `<div class="ly-empty">${I('lyrics')}<div class="ly-empty-t">${U.esc(message)}</div>${sub ? `<div class="ly-empty-s">${U.esc(sub)}</div>` : ''}</div>`;
      this.inner.style.setProperty('--ty', '0px');
    }

    setData(parsed, { offsetMs = 0, estimated = false, words = null } = {}) {
      if (parsed && this.data === parsed && this._words === words && this.items.length) { this.offset = (offsetMs || 0) / 1000 + (parsed.offset || 0) / 1000; return; }
      this._words = words;
      this.data = parsed; this.active = -1; this.items = []; this._nowEl = null;
      this.offset = (offsetMs || 0) / 1000 + (parsed.offset || 0) / 1000;
      this.hasWords = words ? attachWords(parsed, words) : false;
      this.inner.innerHTML = '';
      this.el.classList.toggle('timed', !!parsed.timed);
      this.el.classList.remove('browsing');
      this.padTop = document.createElement('div'); this.padTop.className = 'lyx-pad';
      this.padBot = document.createElement('div'); this.padBot.className = 'lyx-pad';
      // Pill sits at the top of the scroll content (before padTop) so it's visible at rest
      // and translates up with the rest of the lyrics when the user scrolls down.
      const noteText = !parsed.timed ? 'lyrics aren’t time-synced for this track yet.' : estimated ? 'timing is estimated and may drift slightly.' : null;
      if (noteText) { const n = U.h('div', { class: 'ly-note' }); n.innerHTML = `<span>${U.esc(noteText)}</span>`; this.inner.appendChild(n); }
      this.inner.appendChild(this.padTop);

      const timed = parsed.timed;
      const src = timed ? parsed.lines.filter((l) => l.t !== null && l.kind !== 'header') : parsed.lines;
      for (let i = 0; i < src.length; i++) {
        const l = src[i]; const nx = src[i + 1];
        if (l.words && l.words.length) l.end = l.words[l.words.length - 1].e;
        else if (l.t !== null) l.end = Math.min(l.t + LINE_MAX, nx && nx.t !== null ? nx.t : l.t + LINE_MAX);
      }
      const addDots = (s, e) => {
        const d = document.createElement('div'); d.className = 'lx lx-dots'; d.dataset.i = this.items.length;
        d.innerHTML = '<i></i><i></i><i></i>';
        this.inner.appendChild(d);
        this.items.push({ el: d, kind: 'dots', t: s, end: e, dots: Array.from(d.children) });
      };
      if (timed && src.length && src[0].t >= GAP_MIN) addDots(0, src[0].t);
      for (let i = 0; i < src.length; i++) {
        const l = src[i];
        const p = document.createElement('p');
        p.className = 'lx' + (l.kind === 'header' ? ' lx-h' : '');
        p.dataset.i = this.items.length;
        const item = { el: p, kind: l.kind === 'instrumental' ? 'dots' : 'line', t: l.t, end: l.end, words: null };
        if (l.kind === 'instrumental') { p.className = 'lx lx-dots'; p.innerHTML = '<i></i><i></i><i></i>'; item.dots = Array.from(p.children); item.end = src[i + 1] && src[i + 1].t !== null ? src[i + 1].t : l.t + 8; }
        else if (l.words) {
          item.words = [];
          for (const w of l.words) { const sp = document.createElement('span'); sp.className = 'w'; sp.textContent = w.text; p.appendChild(sp); p.appendChild(document.createTextNode(' ')); item.words.push({ el: sp, s: w.s, e: w.e }); }
        } else p.textContent = l.kind === 'header' ? l.text.replace(/^\[|\]$/g, '') : l.text;
        this.inner.appendChild(p);
        this.items.push(item);
        const nx = src[i + 1];
        if (timed && item.kind === 'line' && nx && nx.t !== null && item.end !== undefined && nx.t - item.end >= GAP_MIN) addDots(item.end, nx.t);
      }
      this.inner.appendChild(this.padBot);
      this._layout(false);
      this._applyStates(-1, true);
      this._applyScroll(0, true);
      this._ensureLoop();
    }

    // ---- time
    update(t) { this.baseT = t; this.baseAt = performance.now(); this._sync(); this._ensureLoop(); }
    setPlaying(p) { this.playing = !!p; this.el.classList.toggle('playing', this.playing); if (this.playing) this.baseAt = performance.now(); this._ensureLoop(); }
    now() { return this.playing ? this.baseT + (performance.now() - this.baseAt) / 1000 : this.baseT; }

    _ensureLoop() { if (!this._raf) this._raf = requestAnimationFrame(() => this._tick()); }
    /** not on screen: detached, collapsed, or inside something transparent / visibility:hidden (the closed
        now playing view). the per-frame loop must sleep then, or it restyles hidden text 60 times a second
        for hours; the next update() from the player wakes it when the view is shown again. */
    _hidden() {
      if (!this.el.isConnected || this.el.clientHeight === 0) return true;
      if (typeof this.el.checkVisibility === 'function') { try { return !this.el.checkVisibility({ visibilityProperty: true, opacityProperty: true }); } catch (e) { /* older engine */ } }
      return false;
    }
    _tick() {
      this._raf = 0;
      if (this._hidden()) return;
      if (this.data && this.data.timed) this._sync();
      if (this.playing) this._raf = requestAnimationFrame(() => this._tick());
    }

    _sync() {
      if (!this.data || !this.data.timed || !this.items.length) return;
      const t = this.now() - this.offset;
      let lo = 0, hi = this.items.length - 1, idx = -1;
      while (lo <= hi) { const mid = (lo + hi) >> 1; if (this.items[mid].t <= t) { idx = mid; lo = mid + 1; } else hi = mid - 1; }
      if (idx !== this.active) { this._applyStates(idx, false); this.active = idx; if (!this.el.classList.contains('browsing')) this._scrollToActive(); }
      if (idx < 0) return;
      const it = this.items[idx];
      if (it.kind === 'dots') {
        const p = (t - it.t) / Math.max(0.5, it.end - it.t);
        it.dots.forEach((d, k) => d.classList.toggle('fill', p >= (k + 0.35) / 3));
        it.el.classList.toggle('ending', it.end - t < 0.45);
      } else if (it.words) {
        let nowEl = null;
        for (const w of it.words) {
          let p;
          if (t >= w.e) p = 100; else if (t <= w.s) p = 0; else p = ((t - w.s) / Math.max(0.08, w.e - w.s)) * 100;
          setFill(w.el, p);
          if (t >= w.s - 0.04 && t < w.e + 0.1) nowEl = w.el;
        }
        if (this._nowEl !== nowEl) { if (this._nowEl) this._nowEl.classList.remove('now'); if (nowEl) nowEl.classList.add('now'); this._nowEl = nowEl; }
      }
    }

    _applyStates(active, instant) {
      const timed = this.data && this.data.timed;
      const n = this.items.length;
      for (let i = 0; i < n; i++) {
        const it = this.items[i]; const el = it.el; const st = el.style;
        const d = active < 0 ? i + 1 : Math.abs(i - active);
        const past = active >= 0 && i < active;
        el.classList.toggle('on', i === active);
        el.classList.toggle('past', past);
        if (it.kind === 'dots' && i !== active) { it.dots.forEach((x) => x.classList.toggle('fill', past)); el.classList.remove('ending'); }
        if (it.words && i !== active) { for (const w of it.words) setFill(w.el, past ? 100 : 0); if (this._nowEl && this._nowEl.parentNode === el) { this._nowEl.classList.remove('now'); this._nowEl = null; } }
        if (!timed) { st.setProperty('--op', '1'); st.setProperty('--blur', '0px'); st.setProperty('--s', '1'); st.setProperty('--delay', '0s'); continue; }
        const dist = Math.min(d, 6);
        const op = i === active ? 1 : Math.max(0.2, 0.58 - dist * 0.075);
        const blur = i === active ? 0 : (d > 9 ? 0 : Math.min(2.6, 0.5 + dist * 0.42));
        st.setProperty('--delay', instant || active < 0 ? '0s' : `${Math.max(0, Math.min(i - active, 9)) * 0.032}s`);
        st.setProperty('--op', String(op));
        st.setProperty('--blur', `${blur.toFixed(2)}px`);
        st.setProperty('--s', i === active ? '1' : '0.96');
      }
    }

    // ---- scrolling
    _layout(snap) {
      const vh = this.el.clientHeight; if (!vh) return;
      const f = this.mode === 'full' ? 0.4 : 0.36;
      if (this.padTop) { this.padTop.style.height = `${Math.round(vh * f)}px`; this.padBot.style.height = `${Math.round(vh * (1 - f) + 40)}px`; }
      this.focus = vh * f;
      if (snap && this.active >= 0) this._applyScroll(this._targetFor(this.active), true);
    }
    _targetFor(i) {
      const it = this.items[i]; if (!it) return 0;
      const y = it.el.offsetTop + it.el.offsetHeight / 2 - this.focus;
      return Math.max(0, Math.min(y, this.inner.scrollHeight - this.el.clientHeight));
    }
    _scrollToActive() { if (this.active >= 0) this._applyScroll(this._targetFor(this.active), false); }
    _applyScroll(y, instant) {
      this.scrollY = y;
      if (instant) { this.el.classList.add('no-anim'); }
      this.inner.style.setProperty('--ty', `${(-y).toFixed(2)}px`);
      if (instant) { void this.inner.offsetHeight; requestAnimationFrame(() => this.el.classList.remove('no-anim')); }
    }
    _onWheel(e) {
      if (!this.data) return;
      e.preventDefault();
      const max = Math.max(0, this.inner.scrollHeight - this.el.clientHeight);
      this.el.classList.add('browsing');
      this._applyScroll(Math.max(0, Math.min(max, this.scrollY + e.deltaY)), false);
      clearTimeout(this.browseTimer);
      this.browseTimer = setTimeout(() => this._endBrowse(true), 3200);
    }
    _endBrowse(scrollBack) {
      clearTimeout(this.browseTimer);
      if (!this.el.classList.contains('browsing')) return;
      this.el.classList.remove('browsing');
      if (scrollBack) this._scrollToActive();
    }
  }

  window.Lyrics = { parseLRC, attachWords, LyricsView };
})();
