"""Minimal Discord Rich Presence client over Discord's local IPC pipe (no third-party dependency).

Sends a "listening" activity (type 2) so Discord renders the Spotify-style card:
title / artist / album, cover art, and a progress bar driven by start/end timestamps.

Windows serializes I/O on a synchronous pipe handle, so the protocol is strictly
request/response on one background thread: write a frame, then read the reply.

Every Discord client on the pc (stable, ptb, canary, a second account) opens its own pipe
(discord-ipc-0, -1, -2 …); the presence goes to all of them so it shows no matter which one a friend uses.
"""
from __future__ import annotations

import json
import logging
import os
import struct
import threading
import time
import uuid

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger("999player.discord")

OP_HANDSHAKE, OP_FRAME, OP_CLOSE, OP_PING, OP_PONG = 0, 1, 2, 3, 4
MIN_INTERVAL = 1.2  # seconds between SET_ACTIVITY calls (Discord allows ~5 per 20 s)


def _clip(s: str, limit: int = 128) -> str:
    s = (s or "").strip()
    if len(s) < 2:
        s = (s + " ·").strip() if s else "· ·"
    return s[:limit]


def build_activity(p: dict) -> dict:
    """p: {title, artist, album, image, pos (s), dur (s), playing}."""
    act = {
        "type": 2,
        "details": _clip(p.get("title") or "untitled"),
        "state": _clip(p.get("artist") or "juice wrld"),
        "assets": {"large_text": _clip(p.get("album") or "999 player")},
        "instance": False,
    }
    image = (p.get("image") or "")[:256]
    if image.startswith("http"):
        act["assets"]["large_image"] = image
    try:
        dur = float(p.get("dur") or 0)
        pos = max(0.0, float(p.get("pos") or 0))
    except (TypeError, ValueError):
        dur, pos = 0.0, 0.0
    if p.get("playing") and dur > 0:
        start = int((time.time() - pos) * 1000)
        act["timestamps"] = {"start": start, "end": start + int(dur * 1000)}
    else:
        # paused: say so instead of leaving a timer that looks like listening time
        act["state"] = _clip("paused · " + (p.get("artist") or "juice wrld"))
        act["assets"]["small_text"] = "paused"
    return act


class DiscordRPC(QObject):
    status = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.client_id = ""
        self.enabled = False
        self.pipes: dict[int, object] = {}      # pipe index -> open handle, one per running discord client
        self._sent: dict[int, int] = {}         # pipe index -> last activity seq delivered to it
        self._io = threading.RLock()
        self._state = "off"
        self._pending: dict | None = None
        self._pending_seq = 0
        self._last_sent = 0.0
        self._delayed = False
        self._fatal = False
        self._timer = QTimer(self)
        self._timer.setInterval(20000)
        self._timer.timeout.connect(self._tick)

    # ---- public
    @property
    def state(self) -> str:
        return self._state

    @property
    def pipe(self):
        """first open pipe (kept for callers that only ask "is it connected")"""
        return next(iter(self.pipes.values()), None)

    def configure(self, client_id: str, enabled: bool) -> None:
        client_id = (client_id or "").strip()
        changed = client_id != self.client_id
        self.client_id, self.enabled = client_id, bool(enabled)
        self._fatal = False
        if not self.enabled:
            self._timer.stop()
            threading.Thread(target=self._bg_close, args=("off",), daemon=True).start()
            return
        if not client_id.isdigit():
            self._timer.stop()
            threading.Thread(target=self._bg_close, args=("waiting for an application id",), daemon=True).start()
            return
        if changed:
            threading.Thread(target=self._bg_close, args=("connecting…",), daemon=True).start()
        self._timer.start()
        threading.Thread(target=self._bg_flush, daemon=True).start()

    def set_activity(self, activity: dict | None) -> None:
        self._pending = activity
        self._pending_seq += 1
        if not self.enabled or not self.client_id.isdigit() or self._fatal:
            return
        wait = MIN_INTERVAL - (time.time() - self._last_sent)
        if wait > 0:
            if not self._delayed:
                self._delayed = True
                QTimer.singleShot(int(wait * 1000) + 30, self._schedule_flush)
            return
        self._schedule_flush()

    def close(self, state: str = "off") -> None:
        """Synchronous close of every pipe (main thread on shutdown)."""
        pipes, self.pipes = self.pipes, {}
        self._sent = {}
        for pipe in pipes.values():
            try:
                pipe.close()
            except Exception:
                pass
        self._set_state(state)

    # ---- internals (background threads only beyond this line, except _set_state)
    def _set_state(self, s: str) -> None:
        if s != self._state:
            self._state = s
            self.status.emit(s)

    def _connected_state(self) -> str:
        n = len(self.pipes)
        return "connected" if n <= 1 else f"connected · {n} discord clients"

    def _tick(self) -> None:
        # every 20 s: reconnect if nothing is attached, and look for clients opened since (a second discord)
        if self.enabled and not self._fatal:
            threading.Thread(target=self._bg_flush, daemon=True).start()

    def _schedule_flush(self) -> None:
        self._delayed = False
        self._last_sent = time.time()
        threading.Thread(target=self._bg_flush, daemon=True).start()

    def _bg_close(self, state: str) -> None:
        with self._io:
            self.close(state)

    def _drop(self, i: int, state: str | None = None) -> None:
        pipe = self.pipes.pop(i, None)
        self._sent.pop(i, None)
        if pipe:
            try:
                pipe.close()
            except Exception:
                pass
        if state is not None:
            self._set_state(state)
        elif not self.pipes:
            self._set_state("disconnected")
        else:
            self._set_state(self._connected_state())

    def _bg_flush(self) -> None:
        with self._io:
            if not self._connect():
                return
            seq, act = self._pending_seq, self._pending
            if seq == 0:
                return
            for i in list(self.pipes):
                if self._sent.get(i) == seq:
                    continue
                pipe = self.pipes[i]
                try:
                    self._send(pipe, OP_FRAME, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": act}, "nonce": str(uuid.uuid4())})
                    reply = self._read_reply(pipe)
                except OSError as e:
                    self._drop(i, f"error: {e}".lower() if len(self.pipes) <= 1 else None)
                    continue
                if reply is None:
                    self._drop(i)
                    continue
                if reply.get("evt") == "ERROR":
                    d = reply.get("data") or {}
                    self._handle_error(d.get("code"), d.get("message"))
                    if self._fatal:
                        self.close(self._state)
                        return
                else:
                    self._sent[i] = seq

    def _connect(self) -> bool:
        """Attaches to every discord pipe that is not attached yet. True if at least one client is connected."""
        if self._fatal or not self.enabled or not self.client_id.isdigit():
            return False
        for i in range(10):
            if i in self.pipes:
                continue
            try:
                pipe = open(rf"\\?\pipe\discord-ipc-{i}", "r+b", buffering=0)
            except OSError:
                continue
            try:
                self._send(pipe, OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
                reply = self._read_reply(pipe)
            except OSError as e:
                try:
                    pipe.close()
                except Exception:
                    pass
                if not self.pipes:
                    self._set_state(f"error: {e}".lower())
                continue
            if reply and reply.get("cmd") == "DISPATCH" and reply.get("evt") == "READY":
                self.pipes[i] = pipe
                log.info("discord rpc: attached to client on pipe %d (%d total)", i, len(self.pipes))
                continue
            try:
                pipe.close()
            except Exception:
                pass
            if self._fatal:  # the client answered the handshake with a close frame (bad application id)
                self.close(self._state)
                return False
            if reply and (reply.get("evt") == "ERROR" or "code" in reply):
                d = reply.get("data") or reply
                self._handle_error(d.get("code"), d.get("message"))
                if self._fatal:
                    self.close(self._state)
                    return False
            elif not self.pipes:
                self._set_state("discord didn't answer")
        if self.pipes:
            self._set_state(self._connected_state())
            return True
        if self._state in ("off", "connecting…", "connected") or self._state.startswith("connected"):
            self._set_state("discord isn't running")
        return False

    def _send(self, pipe, op: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        pipe.write(struct.pack("<II", op, len(data)) + data)

    def _read_frame(self, pipe):
        hdr = b""
        while len(hdr) < 8:
            chunk = pipe.read(8 - len(hdr))
            if not chunk:
                return None, None
            hdr += chunk
        op, ln = struct.unpack("<II", hdr)
        raw = b""
        while len(raw) < ln:
            chunk = pipe.read(ln - len(raw))
            if not chunk:
                return None, None
            raw += chunk
        try:
            return op, (json.loads(raw.decode("utf-8")) if raw else {})
        except Exception:
            return op, {}

    def _read_reply(self, pipe):
        """Reads frames until a command reply/event arrives; answers pings; None if the pipe closed."""
        for _ in range(8):
            op, msg = self._read_frame(pipe)
            if op is None:
                return None
            if op == OP_PING:
                self._send(pipe, OP_PONG, msg or {})
                continue
            if op == OP_CLOSE:
                self._handle_error((msg or {}).get("code"), (msg or {}).get("message"))
                return None
            return msg or {}
        return {}

    def _handle_error(self, code, message) -> None:
        log.warning("discord rpc error %s: %s", code, message)
        if code in (4000, 1003) or (message and "client id" in str(message).lower()):
            self._fatal = True
            self._set_state("invalid application id")
        elif message:
            self._set_state(f"error: {str(message).lower()}")
