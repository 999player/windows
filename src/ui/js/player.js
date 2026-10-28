(function () {
  'use strict';
  const NATIVE_EXT = new Set(['m4a', 'mp4', 'aac']);

  class Engine extends EventTarget {
    constructor() {
      super();
      this.a = this._mk();
      this.b = this._mk();
      this.cur = this.a;
      this.mode = 'html5';
      this.song = null;
      this.url = '';
      this.volume = 0.8;
      this.muted = false;
      this.state = 'idle';
      this._nativeDur = 0;
      this._nativePos = 0;
      this._triedNative = false;
      this._loadTimer = null;
      this._wire(this.a); this._wire(this.b);
      Bridge.bus.on('nativePosition', (pos, dur) => {
        if (this.mode !== 'native') return;
        this._nativePos = pos / 1000; this._nativeDur = dur / 1000;
        this._emit('time');
      });
      Bridge.bus.on('nativeState', (st) => {
        if (this.mode !== 'native') return;
        if (st === 'playing') this._set('playing');
        else if (st === 'paused') this._set('paused');
        else if (st === 'buffering' || st === 'loading') this._set('loading');
        else if (st === 'ended') { this._set('ended'); this._emit('ended'); }
        else if (st === 'error') this._fail('Native playback error');
      });
      Bridge.bus.on('nativeError', (msg) => { if (this.mode === 'native') this._fail(msg || 'Native playback error'); });
    }

    _mk() { const el = new Audio(); el.preload = 'auto'; el.volume = 0.8; return el; }

    _wire(el) {
      const only = (fn) => (e) => { if (el === this.cur && this.mode === 'html5') fn(e); };
      el.addEventListener('timeupdate', only(() => this._emit('time')));
      el.addEventListener('durationchange', only(() => this._emit('time')));
      el.addEventListener('playing', only(() => { this._clearLoadTimer(); this._set('playing'); }));
      el.addEventListener('play', only(() => { if (this.state !== 'playing') this._set('loading'); }));
      el.addEventListener('pause', only(() => { if (!el.ended && this.state !== 'idle') this._set('paused'); }));
      el.addEventListener('waiting', only(() => this._set('loading')));
      el.addEventListener('canplay', only(() => { if (!el.paused) this._set('playing'); }));
      el.addEventListener('ended', only(() => { this._set('ended'); this._emit('ended'); }));
      el.addEventListener('error', only(() => {
        const code = el.error && el.error.code;
        if (!this._triedNative && this.url) { this._triedNative = true; this._switchToNative(true); }
        else this._fail('Playback failed' + (code ? ` (code ${code})` : ''));
      }));
      el.addEventListener('stalled', only(() => this._set('loading')));
    }

    _emit(type, detail) { this.dispatchEvent(new CustomEvent(type, { detail })); }
    _set(state) { if (this.state !== state) { this.state = state; this._emit('state', state); } }
    _fail(msg) { this._clearLoadTimer(); this._set('error'); this._emit('error', msg); }
    _clearLoadTimer() { if (this._loadTimer) { clearTimeout(this._loadTimer); this._loadTimer = null; } }

    get currentTime() { return this.mode === 'native' ? this._nativePos : (this.cur.currentTime || 0); }
    get duration() {
      if (this.mode === 'native') return this._nativeDur || (this.song && this.song.dur) || 0;
      const d = this.cur.duration;
      return isFinite(d) && d > 0 ? d : (this.song && this.song.dur) || 0;
    }
    get paused() { return this.state !== 'playing' && this.state !== 'loading'; }

    load(song, { autoplay = true, startAt = 0 } = {}) {
      this._clearLoadTimer();
      this.song = song;
      this.url = U.audioUrl(song);
      this._triedNative = false;
      const wantNative = NATIVE_EXT.has(U.ext(song));
      if (this.mode === 'native') Bridge.fire('nativeStop');
      if (wantNative) { this._switchToNative(autoplay, startAt); return; }
      this.mode = 'html5';
      this._nativePos = 0; this._nativeDur = 0;
      const other = this.cur === this.a ? this.b : this.a;
      if (other.src === this.url) { this.cur.pause(); this.cur = other; }
      else { this.cur.pause(); this.cur.src = this.url; this.cur.load(); }
      other.removeAttribute('src'); if (other !== this.cur) { try { other.load(); } catch (e) {  } }
      this.cur.volume = this.muted ? 0 : this.volume;
      if (startAt) { try { this.cur.currentTime = startAt; } catch (e) {  this.cur.addEventListener('loadedmetadata', () => { this.cur.currentTime = startAt; }, { once: true }); } }
      this._set('loading');
      this._emit('time');
      if (autoplay) {
        const p = this.cur.play();
        if (p && p.catch) p.catch((e) => { if (e && e.name !== 'AbortError') console.warn('play() rejected', e); });
        this._loadTimer = setTimeout(() => {
          if (this.state === 'loading' && this.mode === 'html5' && !this._triedNative) { this._triedNative = true; this._switchToNative(true, this.cur.currentTime || 0); }
        }, 25000);
      } else this._set('paused');
    }

    _switchToNative(autoplay, startAt) {
      this._clearLoadTimer();
      this.mode = 'native';
      try { this.cur.pause(); this.cur.removeAttribute('src'); this.cur.load(); } catch (e) {  }
      this._nativePos = startAt || 0; this._nativeDur = (this.song && this.song.dur) || 0;
      Bridge.fire('nativeVolume', this.volume);
      Bridge.fire('nativeMuted', this.muted);
      Bridge.fire('nativeLoad', (this.song && this.song.nativeUrl) || this.url, !!autoplay);
      if (startAt) setTimeout(() => Bridge.fire('nativeSeek', Math.round(startAt * 1000)), 400);
      this._set(autoplay ? 'loading' : 'paused');
      this._emit('engine', 'native');
    }

    preload(song) {
      if (!song || NATIVE_EXT.has(U.ext(song))) return;
      const url = U.audioUrl(song);
      const other = this.cur === this.a ? this.b : this.a;
      if (other.src !== url) { other.src = url; try { other.load(); } catch (e) {  } }
    }

    play() {
      if (!this.song) return;
      if (this.mode === 'native') { Bridge.fire('nativePlay'); this._set('loading'); return; }
      if (this.state === 'ended') { try { this.cur.currentTime = 0; } catch (e) {  } }
      const p = this.cur.play(); if (p && p.catch) p.catch(() => {});
    }
    pause() {
      if (this.mode === 'native') { Bridge.fire('nativePause'); return; }
      this.cur.pause();
    }
    toggle() { if (this.state === 'playing' || this.state === 'loading') this.pause(); else this.play(); }
    stop() {
      this._clearLoadTimer();
      if (this.mode === 'native') Bridge.fire('nativeStop');
      try { this.cur.pause(); this.cur.removeAttribute('src'); this.cur.load(); } catch (e) {  }
      this.song = null; this.url = ''; this._set('idle'); this._emit('time');
    }
    seek(sec) {
      sec = Math.max(0, Math.min(sec, this.duration || sec));
      if (this.mode === 'native') { this._nativePos = sec; Bridge.fire('nativeSeek', Math.round(sec * 1000)); this._emit('time'); return; }
      try { this.cur.currentTime = sec; } catch (e) {  }
      this._emit('time');
    }
    setVolume(v) {
      this.volume = U.clamp(v, 0, 1);
      this.a.volume = this.b.volume = this.muted ? 0 : this.volume;
      Bridge.fire('nativeVolume', this.volume);
      this._emit('volume');
    }
    setMuted(m) {
      this.muted = !!m;
      this.a.volume = this.b.volume = this.muted ? 0 : this.volume;
      Bridge.fire('nativeMuted', this.muted);
      this._emit('volume');
    }
    canPlay() {
      const el = document.createElement('audio');
      return { mp3: el.canPlayType('audio/mpeg'), wav: el.canPlayType('audio/wav'), flac: el.canPlayType('audio/flac'), opus: el.canPlayType('audio/ogg; codecs=opus'), aac: el.canPlayType('audio/mp4; codecs="mp4a.40.2"') };
    }
  }
  window.Engine = Engine;
})();
