"""Tests for the single-instance run lock used by the cron entry points."""

from __future__ import annotations

import os
import tempfile
import unittest

from ainews.runlock import RunLockBusy, run_lock


class RunLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = os.path.join(tempfile.mkdtemp(), "pipeline.lock")

    def test_second_holder_is_refused_while_first_holds_lock(self) -> None:
        with run_lock(self.path):
            with self.assertRaises(RunLockBusy):
                with run_lock(self.path):
                    pass

    def test_lock_is_reusable_after_release(self) -> None:
        with run_lock(self.path):
            pass
        with run_lock(self.path):
            pass  # no RunLockBusy

    def test_waiting_acquire_gets_the_lock_once_the_holder_finishes(self) -> None:
        import threading
        import time

        held = threading.Event()

        def holder():
            with run_lock(self.path):
                held.set()
                time.sleep(0.3)

        t = threading.Thread(target=holder)
        t.start()
        held.wait(2)
        start = time.monotonic()
        with run_lock(self.path, wait_seconds=5, poll_seconds=0.05):
            waited = time.monotonic() - start
        t.join()
        self.assertGreater(waited, 0.1)
        self.assertLess(waited, 3)

    def test_waiting_acquire_gives_up_after_the_deadline(self) -> None:
        import time

        with run_lock(self.path):
            start = time.monotonic()
            with self.assertRaises(RunLockBusy):
                with run_lock(self.path, wait_seconds=0.3, poll_seconds=0.05):
                    pass
            self.assertGreaterEqual(time.monotonic() - start, 0.25)

    def test_lock_released_when_body_raises(self) -> None:
        with self.assertRaises(ValueError):
            with run_lock(self.path):
                raise ValueError("stage failed")
        with run_lock(self.path):
            pass


if __name__ == "__main__":
    unittest.main()
