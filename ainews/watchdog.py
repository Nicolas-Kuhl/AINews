"""Hard time limit for a cron run.

Runs on the production box have hung for months inside Playwright (a trusted
fetch stuck since early July, an episode render stuck mid-screenshot). With
the single-instance run lock, one such hang would hold the lock forever and
silently stop every later run. The watchdog ends the process once it outlives
its limit; the OS then releases the lock, and Playwright's driver exits when
its parent's pipe closes.

``os._exit`` is deliberate: a hung thread can't be interrupted, and a clean
shutdown would wait on it. SQLite rolls back any open transaction on the
next connection.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Callable

logger = logging.getLogger(__name__)

EXIT_TIMED_OUT = 70  # EX_SOFTWARE


def start_watchdog(
    seconds: float,
    *,
    exit_fn: Callable[[int], None] = os._exit,
    label: str = "run",
) -> threading.Timer:
    """Exit the process with code 70 after ``seconds`` unless cancelled."""

    def expire() -> None:
        logger.error("%s exceeded its %.0fs time limit; terminating", label, seconds)
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:  # noqa: BLE001
                pass
        exit_fn(EXIT_TIMED_OUT)

    timer = threading.Timer(seconds, expire)
    timer.daemon = True
    timer.start()
    return timer
