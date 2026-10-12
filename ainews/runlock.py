"""Single-instance lock for the cron entry points.

The 15-minute trusted run, the daily open run, the dashboard's "Run Pipeline"
button and a manual retry can all start while another run is still going.
Overlapping runs double-pay for Claude scoring and fight over SQLite, so each
entry point takes an exclusive, non-blocking OS file lock and exits quietly
when another run holds it. The OS drops the lock if the process dies, so a
crash never leaves a stale lock behind.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union


class RunLockBusy(RuntimeError):
    """Another process holds the lock."""


if os.name == "nt":
    import msvcrt

    def _try_lock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _try_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def run_lock(path: Union[str, Path]) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` for the duration of the block.

    Raises ``RunLockBusy`` immediately (never waits) if another process — or
    another handle in this process — already holds it.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            _try_lock(fd)
        except OSError as exc:
            raise RunLockBusy(f"{path} is held by another run") from exc
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
