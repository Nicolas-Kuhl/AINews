"""Tests for the short-summary backfill script's Claude batch."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from claude_fakes import FakeClaude

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backfill_short_summaries.py"
_spec = importlib.util.spec_from_file_location("backfill_short_summaries", _SCRIPT)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


def _rows():
    return [{"id": 101, "title": "A", "source": "S", "summary": "a"},
            {"id": 102, "title": "B", "source": "S", "summary": "b"},
            {"id": 103, "title": "C", "source": "S", "summary": "c"}]


class RunBatchTests(unittest.TestCase):
    def test_summaries_land_on_the_right_rows_when_one_is_skipped(self) -> None:
        # Model skipped item 1 and answered items 0 and 2 (thinking block first).
        reply = json.dumps([{"id": 0, "short_summary": "about A"},
                            {"id": 2, "short_summary": "about C"}])
        out = backfill._run_batch(FakeClaude(reply), "claude-sonnet-5-5", _rows())
        self.assertEqual(out, {101: "about A", 103: "about C"})


if __name__ == "__main__":
    unittest.main()
