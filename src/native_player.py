"""QMediaPlayer-backed fallback engine for formats Chromium cannot decode (AAC/M4A) or when HTML5 audio fails."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

log = logging.getLogger("999player.native")


class NativePlayer(QObject):
    position = Signal(int, int)       # pos_ms, dur_ms
    state = Signal(str)               # playing | paused | stopped | loading | buffering | ended | error
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.out = QAudioOutput(self)
        self.player.setAudioOutput(self.out)
        self.player.playbackStateChanged.connect(self._on_pb)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(self._on_error)
        self._tick = QTimer(self)
        self._tick.setInterval(200)
        self._tick.timeout.connect(self._emit_pos)
        self._active = False

    def _emit_pos(self) -> None:
        if self._active:
            self.position.emit(int(self.player.position()), int(self.player.duration()))

    def _on_pb(self, st) -> None:
        if not self._active:
            return
        if st == QMediaPlayer.PlaybackState.PlayingState:
            self.state.emit("playing")
            self._tick.start()
        elif st == QMediaPlayer.PlaybackState.PausedState:
            self.state.emit("paused")
            self._emit_pos()
        else:
            self._tick.stop()
            self.state.emit("stopped")

    def _on_status(self, st) -> None:
        if not self._active:
            return
        S = QMediaPlayer.MediaStatus
        if st == S.EndOfMedia:
            self._tick.stop()
            self.state.emit("ended")
        elif st in (S.LoadingMedia, S.StalledMedia):
            self.state.emit("buffering")
        elif st == S.InvalidMedia:
            self.state.emit("error")
            self.error.emit("Invalid media")
        elif st in (S.LoadedMedia, S.BufferedMedia):
            self._emit_pos()

    def _on_error(self, err, msg: str) -> None:
        if not self._active:
            return
        log.warning("native player error %s: %s", err, msg)
        self.state.emit("error")
        self.error.emit(msg or str(err))

    @Slot(str, bool)
    def load(self, url: str, autoplay: bool = True) -> None:
        self._active = True
        self.player.stop()
        self.player.setSource(QUrl(url))
        if autoplay:
            self.player.play()
        self.state.emit("loading")

    @Slot()
    def play(self) -> None:
        self._active = True
        self.player.play()

    @Slot()
    def pause(self) -> None:
        self.player.pause()

    @Slot()
    def stop(self) -> None:
        self._active = False
        self._tick.stop()
        self.player.stop()
        self.player.setSource(QUrl())

    @Slot(int)
    def seek(self, ms: int) -> None:
        self.player.setPosition(max(0, int(ms)))

    @Slot(float)
    def set_volume(self, v: float) -> None:
        self.out.setVolume(max(0.0, min(1.0, float(v))))

    @Slot(bool)
    def set_muted(self, m: bool) -> None:
        self.out.setMuted(bool(m))
