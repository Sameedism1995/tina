"""wake_monitor.py — macOS sleep/wake detection via wall-clock delta.

The system clock (datetime.now) keeps running during sleep; time.monotonic
pauses. So if our 5-second background tick sees a wall-clock gap much larger
than expected, the OS must have slept and just woken.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Optional


class WakeMonitor:
    _TICK      = 5.0    # seconds between checks
    _THRESHOLD = 20.0   # extra gap that signals a wake

    def __init__(self, on_wake: Callable[[float], None]) -> None:
        """
        on_wake(elapsed_seconds) — called on the monitor thread when a
        sleep/wake cycle is detected; elapsed_seconds is approximate sleep time.
        Dispatch to the main thread yourself (e.g. root.after(0, ...)).
        """
        self._on_wake  = on_wake
        self._stop     = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="tina-wake", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        last = datetime.now().timestamp()
        while not self._stop.wait(self._TICK):
            now = datetime.now().timestamp()
            gap = now - last
            if gap > self._TICK + self._THRESHOLD:
                try:
                    self._on_wake(gap - self._TICK)
                except Exception as exc:
                    print(f"[TINA] wake callback error: {exc}")
            last = now
