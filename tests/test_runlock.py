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

    def test_lock_released_when_body_raises(self) -> None:
        with self.assertRaises(ValueError):
            with run_lock(self.path):
                raise ValueError("stage failed")
        with run_lock(self.path):
            pass


if __name__ == "__main__":
    unittest.main()
