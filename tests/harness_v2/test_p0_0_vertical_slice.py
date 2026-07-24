import json
import tempfile
import unittest
from pathlib import Path

from harness.v2.p0_0_vertical_slice import run_slice


def make_manifest() -> dict:
    return {
        "req_ids": [f"REQ-P0-{index:03d}" for index in range(1, 91)],
        "phase": "P0",
    }


def write_manifest(workspace: Path) -> None:
    path = workspace / "split_manifest.json"
    path.write_text(json.dumps(make_manifest()), encoding="utf-8")


class P00VerticalSliceTests(unittest.TestCase):
    def test_success_projects_manifest_and_replays_journal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_manifest(workspace)

            checkpoint = run_slice(workspace)

            self.assertEqual(checkpoint["status"], "PASS")
            self.assertEqual(checkpoint["task_id"], "P0.0")
            registry = json.loads(
                (workspace / "harness" / "v2" / "requirements_registry.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(registry["req_count"], 90)
            journal = (workspace / "harness" / "v2" / "journal.jsonl").read_text(encoding="utf-8")
            self.assertIn('"event": "TASK_STARTED"', journal)

    def test_injected_failure_is_not_projected_to_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            write_manifest(workspace)

            checkpoint = run_slice(workspace, failure_injection=True)

            self.assertEqual(checkpoint["status"], "BLOCKED")
            self.assertTrue(checkpoint["blocker"])
            state = json.loads(
                (workspace / "harness" / "v2" / "state" / "current.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["status"], "BLOCKED")
            self.assertNotEqual(state["status"], "PASS")

    def test_manifest_count_mismatch_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "split_manifest.json").write_text(
                json.dumps({"req_ids": ["REQ-P0-001"]}), encoding="utf-8"
            )

            checkpoint = run_slice(workspace)

            self.assertEqual(checkpoint["status"], "BLOCKED")
            self.assertIn("exactly 90", " ".join(checkpoint["blocker"]))


if __name__ == "__main__":
    unittest.main()
