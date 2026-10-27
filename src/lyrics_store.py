"""Offline lyrics: every vault song's LRC + word timing saved as plain files, so lyrics survive the site going away.

Two locations are read, user first:
  %LOCALAPPDATA%\\999player\\lyrics\\   written by "download all lyrics" in settings
  <bundle>\\assets\\lyrics\\              shipped inside the build (populated with `py lyrics_store.py`)

Per song:  <id>.lrc   portable LRC with [id:] [ti:] [ar:] [al:] header tags
           <id>.json  normalized detail the app consumes (lyrics, words, offsetMs, …)
Plus index.json listing every saved song (id → title / artist / era / has words).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from appdata import BUNDLE_DIR, DATA_DIR

log = logging.getLogger("999player.lyrics")

USER_DIR = DATA_DIR / "lyrics"
BUNDLED_DIR = BUNDLE_DIR / "assets" / "lyrics"
PAGE = 300
SYNC_SELECT = "id,title,author,era,duration_seconds,lyrics,source_metadata"
SYNC_FILTER = "lyrics=not.is.null&lyrics=neq.&order=id.asc"
KEEP = ("lyrics", "words", "offsetMs", "estimated", "startSec", "lyricsSource", "layoutSource")


def _count(d: Path) -> int:
    try:
        return sum(1 for p in d.glob("*.json") if p.stem.isdigit()) if d.is_dir() else 0
    except Exception:
        return 0


def _index(d: Path) -> dict[str, Any]:
    try:
        return json.loads((d / "index.json").read_text("utf-8"))
    except Exception:
        return {}


def status() -> dict[str, Any]:
    user, bundled = _index(USER_DIR), _index(BUNDLED_DIR)
    return {
        "user": _count(USER_DIR),
        "bundled": _count(BUNDLED_DIR),
        "synced": user.get("synced") or None,
        "bundledAt": bundled.get("synced") or None,
        "dir": str(USER_DIR),
    }


def get(song_id: int) -> dict[str, Any] | None:
    """Saved lyric detail for a song (user copy wins over the bundled one), or None."""
    for d in (USER_DIR, BUNDLED_DIR):
        p = d / f"{int(song_id)}.json"
        if p.exists():
            try:
                return json.loads(p.read_text("utf-8"))
            except Exception as e:
                log.warning("unreadable lyric file %s: %s", p, e)
    return None


def has(song_id: int) -> bool:
    return any((d / f"{int(song_id)}.json").exists() for d in (USER_DIR, BUNDLED_DIR))


def index_bytes() -> bytes:
    """Every saved song (bundled + user, user wins) as JSON for the UI: {songs: {id: {t, a, e, d, w}}}."""
    songs: dict[str, Any] = {}
    for d in (BUNDLED_DIR, USER_DIR):
        songs.update(_index(d).get("songs") or {})
    return json.dumps({"count": len(songs), "songs": songs}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _lrc_text(row: dict[str, Any], det: dict[str, Any]) -> str:
    body = (det.get("lyrics") or "").strip()
    head = [f"[id:{int(row.get('id') or 0)}]", f"[ti:{(row.get('title') or '').strip()}]",
            f"[ar:{(row.get('author') or 'Juice WRLD').strip()}]"]
    if row.get("era"):
        head.append(f"[al:{str(row['era']).strip()}]")
    dur = int(row.get("duration_seconds") or 0)
    if dur:
        head.append(f"[length:{dur // 60:02d}:{dur % 60:02d}]")
    if det.get("offsetMs"):
        head.append(f"[offset:{int(det['offsetMs'])}]")
    head.append("[re:999 player]")
    return "\n".join(head) + "\n\n" + body + "\n"


def sync(catalog, dest: Path | None = None, progress: Callable[[int, int], None] | None = None) -> int:
    """Blocking: downloads every song that has lyrics into `dest` (default: the user folder). Returns the count."""
    from catalog import normalize_detail  # local import: catalog imports nothing from here, avoid cycles at module load

    dest = dest or USER_DIR
    dest.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    index: dict[str, Any] = {}
    off, total, n = 0, -1, 0
    while True:
        r = catalog._get(f"select={SYNC_SELECT}&{SYNC_FILTER}",
                         {"Range-Unit": "items", "Range": f"{off}-{off + PAGE - 1}", "Prefer": "count=exact"})
        rows = r.json()
        rng = r.headers.get("Content-Range", "")
        tail = rng.rsplit("/", 1)[-1] if "/" in rng else ""
        total = int(tail) if tail.isdigit() else total
        for row in rows:
            det = normalize_detail(row)
            if not det.get("lyrics"):
                continue
            sid = int(row.get("id") or 0)
            slim = {k: det.get(k) for k in KEEP}
            slim.update({"id": sid, "title": (row.get("title") or "").strip(), "author": (row.get("author") or "Juice WRLD").strip(),
                         "era": (row.get("era") or None), "dur": int(row.get("duration_seconds") or 0), "saved": int(time.time())})
            try:
                (dest / f"{sid}.json").write_text(json.dumps(slim, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
                (dest / f"{sid}.lrc").write_text(_lrc_text(row, det), encoding="utf-8")
            except Exception as e:
                log.warning("could not write lyrics for %s: %s", sid, e)
                continue
            index[str(sid)] = {"t": slim["title"], "a": slim["author"], "e": slim["era"], "d": slim["dur"], "w": bool(slim.get("words"))}
            n += 1
        if progress:
            progress(min(off + len(rows), total if total > 0 else off + len(rows)), total)
        if not rows or len(rows) < PAGE or (total >= 0 and off + len(rows) >= total):
            break
        off += len(rows)
    (dest / "index.json").write_text(json.dumps({"synced": int(time.time()), "count": n, "songs": index}, ensure_ascii=False, indent=0),
                                     encoding="utf-8")
    log.info("lyrics synced: %d songs -> %s in %.1fs", n, dest, time.time() - t0)
    return n


if __name__ == "__main__":  # `py lyrics_store.py [dest]` — fills assets\lyrics for the build
    import sys
    from catalog import Catalog

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else BUNDLED_DIR
    count = sync(Catalog(), target, progress=lambda a, b: print(f"  {a}/{b}", flush=True))
    print(f"saved {count} songs -> {target}")
