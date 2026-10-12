"""The episode orchestrator fixes the edition date once and hands it to
every stage, so a retry after midnight UTC finishes the right episode."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import generate_episode


class OrchestratorDateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.cmds: list[list[str]] = []
        self.timeouts: dict = {}

    def _fake_stage(self, name, cmd, *_, **kwargs):
        self.cmds.append(cmd)
        self.timeouts[name] = kwargs.get("timeout")
        if name == "script":
            scripts = self.root / "data" / "video_scripts"
            scripts.mkdir(parents=True, exist_ok=True)
            (scripts / "2026-10-12.json").write_text("{}", encoding="utf-8")
        return True

    def _run(self, argv):
        with mock.patch.object(generate_episode, "PROJECT_ROOT", self.root), \
             mock.patch.object(generate_episode, "_stage", side_effect=self._fake_stage), \
             mock.patch.object(sys, "argv", ["generate_episode.py", *argv]):
            generate_episode.main()

    def test_every_stage_gets_the_same_edition_date(self) -> None:
        self._run(["--date", "2026-10-12"])
        script_cmd, voice_cmd, video_cmd = self.cmds
        self.assertIn("--edition-date", script_cmd)
        self.assertEqual(script_cmd[script_cmd.index("--edition-date") + 1], "2026-10-12")
        voice_script = Path(voice_cmd[voice_cmd.index("--script") + 1])
        self.assertEqual(voice_script.name, "2026-10-12.json")
        self.assertEqual(video_cmd[video_cmd.index("--date") + 1], "2026-10-12")

    def _existing(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        return path

    def _stages_run(self) -> list[str]:
        return [Path(cmd[1]).stem for cmd in self.cmds]

    def test_retry_after_render_failure_reuses_script_and_voiceover(self) -> None:
        import os
        import time
        script = self._existing("data/video_scripts/2026-10-12.json")
        manifest = self._existing("data/video_audio/2026-10-12/manifest.json")
        later = time.time() + 5
        os.utime(manifest, (later, later))
        self._run(["--date", "2026-10-12"])
        self.assertEqual(self._stages_run(), ["generate_video"])
        self.assertTrue(script.exists())

    def test_retry_after_voiceover_failure_reuses_the_script(self) -> None:
        self._existing("data/video_scripts/2026-10-12.json")
        self._run(["--date", "2026-10-12"])
        self.assertEqual(self._stages_run(), ["generate_voiceover", "generate_video"])

    def test_force_reruns_every_stage(self) -> None:
        self._existing("data/video_scripts/2026-10-12.json")
        self._existing("data/video_audio/2026-10-12/manifest.json")
        self._run(["--date", "2026-10-12", "--force"])
        self.assertEqual(self._stages_run(),
                         ["generate_video_script", "generate_voiceover", "generate_video"])

    def test_retry_command_in_alert_pins_the_date(self) -> None:
        cmd = generate_episode._retry_command("2026-10-12")
        self.assertIn("generate_episode.py --date 2026-10-12", cmd)

    def test_second_run_is_skipped_while_first_holds_the_lock(self) -> None:
        from ainews.runlock import run_lock

        with run_lock(self.root / "data" / ".episode.lock"):
            self._run(["--date", "2026-10-12"])
        self.assertEqual(self.cmds, [])


class StageTimeoutTests(unittest.TestCase):
    def test_every_stage_runs_with_a_time_limit(self) -> None:
        t = OrchestratorDateTests("test_every_stage_gets_the_same_edition_date")
        t.setUp()
        t._run(["--date", "2026-10-12"])
        self.assertEqual(set(t.timeouts), {"script", "voiceover", "render + feed"})
        # Longest seen in production: script 128s, voiceover 75s, render 242s.
        self.assertGreaterEqual(t.timeouts["script"], 600)
        self.assertGreaterEqual(t.timeouts["voiceover"], 600)
        self.assertGreaterEqual(t.timeouts["render + feed"], 1800)

    def test_hung_stage_is_killed_and_alerted(self) -> None:
        import time
        alerts = []
        with mock.patch.object(generate_episode, "_alert",
                               side_effect=lambda subject, msg: alerts.append(subject)):
            start = time.monotonic()
            ok = generate_episode._stage(
                "render + feed", [sys.executable, "-c", "import time; time.sleep(60)"],
                "2026-10-12", timeout=0.5,
            )
        self.assertFalse(ok)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(len(alerts), 1)
        self.assertIn("timed out", alerts[0])

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_hung_stage_grandchildren_are_killed_too(self) -> None:
        """The July hang was a Chromium tree under the render stage; killing
        only the direct child would orphan it."""
        import os
        import time
        pidfile = Path(tempfile.mkdtemp()) / "grandchild.pid"
        spawn = "\n".join([
            "import subprocess, sys, time",
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])",
            f"open({str(pidfile)!r}, 'w').write(str(p.pid))",
            "time.sleep(60)",
        ])
        with mock.patch.object(generate_episode, "_alert"):
            generate_episode._stage("render + feed", [sys.executable, "-c", spawn],
                                    "2026-10-12", timeout=1.5)
        grandchild = int(pidfile.read_text())
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(grandchild, 0)


if __name__ == "__main__":
    unittest.main()
