"""The run watchdog hard-exits a process that outlives its time limit, so a
hung run can't hold the pipeline lock forever."""

from __future__ import annotations

import threading
import time
import unittest

from ainews.watchdog import start_watchdog


class WatchdogTests(unittest.TestCase):
    def test_exits_the_process_once_the_limit_passes(self) -> None:
        fired = threading.Event()
        codes = []

        def fake_exit(code):
            codes.append(code)
            fired.set()

        start_watchdog(0.1, exit_fn=fake_exit)
        self.assertTrue(fired.wait(2))
        self.assertEqual(codes, [70])

    def test_cancelled_watchdog_never_fires(self) -> None:
        codes = []
        dog = start_watchdog(0.1, exit_fn=codes.append)
        dog.cancel()
        time.sleep(0.3)
        self.assertEqual(codes, [])

    def test_watchdog_does_not_keep_the_interpreter_alive(self) -> None:
        dog = start_watchdog(3600, exit_fn=lambda code: None)
        try:
            self.assertTrue(dog.daemon)
        finally:
            dog.cancel()


class HungRunReleasesLockTests(unittest.TestCase):
    def test_hung_process_is_killed_and_its_lock_released(self) -> None:
        import os
        import subprocess
        import sys
        import tempfile

        from ainews.runlock import run_lock

        lock = os.path.join(tempfile.mkdtemp(), "pipeline.lock")
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        hung_run = (
            "import sys, time\n"
            f"sys.path.insert(0, {repo!r})\n"
            "from ainews.runlock import run_lock\n"
            "from ainews.watchdog import start_watchdog\n"
            f"with run_lock({lock!r}):\n"
            "    print('locked', flush=True)\n"
            "    start_watchdog(0.5)\n"
            "    time.sleep(60)  # the hang\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", hung_run], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "locked")
            start = time.monotonic()
            with run_lock(lock, wait_seconds=10, poll_seconds=0.1):
                waited = time.monotonic() - start
            self.assertLess(waited, 5)
            self.assertEqual(proc.wait(5), 70)
        finally:
            if proc.poll() is None:
                proc.kill()


if __name__ == "__main__":
    unittest.main()
