(function () {
  'use strict';
  class VirtualList {
    constructor({ scroller, container, rowHeight = 56, overscan = 8, render, update, key }) {
      this.scroller = scroller;
      this.container = container;
      this.rowHeight = rowHeight;
      this.overscan = overscan;
      this.render = render;
      this.update = update;
      this.key = key || ((item) => item.id);
      this.items = [];
      this.pool = new Map();
      this.container.classList.add('vlist');
      this.container.style.position = 'relative';
      this._onScroll = () => this._schedule();
      this.scroller.addEventListener('scroll', this._onScroll, { passive: true });
      this._ro = new ResizeObserver(() => this._schedule());
      this._ro.observe(this.scroller);
      this._raf = 0;
      this._range = [0, 0];
    }
    setItems(items) {
      this.items = items || [];
      this.container.style.height = `${this.items.length * this.rowHeight}px`;
      this._range = [0, 0];
      this._schedule(true);
    }
    _schedule(force) {
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => { this._raf = 0; this._paint(force); });
    }
    _paint(force) {
      if (!this.container.isConnected) return;
      const top = this.container.offsetTop;
      const viewTop = this.scroller.scrollTop - top;
      const viewH = this.scroller.clientHeight;
      const first = Math.max(0, Math.floor(viewTop / this.rowHeight) - this.overscan);
      const last = Math.min(this.items.length, Math.ceil((viewTop + viewH) / this.rowHeight) + this.overscan);
      if (!force && first === this._range[0] && last === this._range[1]) return;
      this._range = [first, last];
      const keep = new Set();
      for (let i = first; i < last; i++) {
        const item = this.items[i]; const k = this.key(item);
        keep.add(k);
        let el = this.pool.get(k);
        if (!el) { el = this.render(item, i); el.style.position = 'absolute'; el.style.left = '0'; el.style.right = '0'; this.pool.set(k, el); this.container.appendChild(el); }
        else if (this.update) this.update(el, item, i);
        const y = i * this.rowHeight;
        if (el.__y !== y) { el.style.transform = `translateY(${y}px)`; el.__y = y; }
      }
      for (const [k, el] of this.pool) { if (!keep.has(k)) { el.remove(); this.pool.delete(k); } }
    }
    refresh() { for (const [k, el] of this.pool) { const i = this.items.findIndex((it) => this.key(it) === k); if (i >= 0 && this.update) this.update(el, this.items[i], i); } }
    elementFor(key) { return this.pool.get(key) || null; }
    scrollToIndex(i) {
      const y = this.container.offsetTop + i * this.rowHeight - this.scroller.clientHeight / 2 + this.rowHeight / 2;
      this.scroller.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
    }
    destroy() {
      this.scroller.removeEventListener('scroll', this._onScroll);
      this._ro.disconnect();
      if (this._raf) cancelAnimationFrame(this._raf);
      this.pool.clear();
      this.container.innerHTML = '';
    }
  }
  window.VirtualList = VirtualList;
})();
