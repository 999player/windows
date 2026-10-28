(function () {
  'use strict';

  const listeners = new Map();
  const bus = {
    on(ev, fn) { if (!listeners.has(ev)) listeners.set(ev, new Set()); listeners.get(ev).add(fn); return () => listeners.get(ev).delete(fn); },
    emit(ev, ...args) { const s = listeners.get(ev); if (s) for (const fn of Array.from(s)) { try { fn(...args); } catch (e) { console.error('bus handler error', ev, e); } } },
  };

  const SIGNALS = ['updateStatus', 'init', 'catalogChanged', 'catalogError', 'catalogProgress', 'detail', 'detailError', 'downloadProgress',
    'downloadDone', 'downloadsChanged', 'settingChanged', 'winState', 'mediaKey', 'nativePosition', 'nativeState', 'nativeError', 'toast', 'discordStatus', 'accent', 'lastfmStatus', 'localChanged', 'lyricsStatus'];

  let obj = null;
  let readyResolve;
  const ready = new Promise((r) => { readyResolve = r; });

  function connect() {
    if (typeof QWebChannel === 'undefined' || typeof qt === 'undefined' || !qt.webChannelTransport) {
      console.warn('QWebChannel transport not available; running without bridge');
      readyResolve(null);
      return;
    }
    new QWebChannel(qt.webChannelTransport, (channel) => {
      obj = channel.objects.bridge;
      for (const sig of SIGNALS) {
        if (obj[sig] && obj[sig].connect) obj[sig].connect((...args) => bus.emit(sig, ...args));
      }
      readyResolve(obj);
    });
  }

  function call(name, ...args) {
    return new Promise((resolve, reject) => {
      if (!obj) return reject(new Error('bridge not connected'));
      const fn = obj[name];
      if (typeof fn !== 'function') return reject(new Error('no bridge method ' + name));
      try {
        fn.call(obj, ...args, (result) => resolve(result));
      } catch (e) { reject(e); }
    });
  }
  function fire(name, ...args) {
    if (!obj) return;
    const fn = obj[name];
    if (typeof fn === 'function') { try { fn.call(obj, ...args); } catch (e) { console.error('bridge call failed', name, e); } }
  }

  window.Bridge = {
    bus, ready, connect, call, fire,
    get connected() { return !!obj; },
    log(level, msg) { fire('log', level, String(msg)); },
  };
})();
