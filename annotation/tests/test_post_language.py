import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "src/prepare_normalized_dataset.py"


class SelectionTests(unittest.TestCase):
    def run_selection(self, pending=False, policy="reviewed"):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        audit = root / "audit"
        audit.mkdir()
        rows = [{"assigned_id": f"TT_{i}", "file_path": "fixture.mp4", "category": "Comedy",
                 "category_conflict": "False", "media_status": "full_video_decode_passed",
                 "language_status": "target_language_candidate", "orientation": "horizontal" if i < 50 else "vertical",
                 "split": "original_pilot" if i < 5 else "unassigned", "audit_selection_status": "target_language_candidate"}
                for i in range(100)]
        rows[-1]["language_status"] = "pending" if pending else "review_mixed_language"
        with (audit / "validation_manifest.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        output = root / "selected"
        result = subprocess.run([sys.executable, str(SCRIPT), "select", "--audit", str(audit), "--output", str(output), "--policy", policy], capture_output=True, text=True)
        return result, output

    def test_cap_preserves_pilot_and_keeps_review_pending(self):
        result, output = self.run_selection()
        self.assertEqual(result.returncode, 0, result.stderr)
        with (output / "selected_metadata.csv").open() as handle:
            selected = list(csv.DictReader(handle))
        self.assertLessEqual(sum(r["orientation"] == "horizontal" for r in selected) / len(selected), .3)
        self.assertTrue({f"TT_{i}" for i in range(5)} <= {r["assigned_id"] for r in selected})
        self.assertNotIn("TT_99", {r["assigned_id"] for r in selected})

    def test_incomplete_audit_cannot_be_frozen(self):
        result, output = self.run_selection(pending=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_non_target_only_policy_retains_mixed_language(self):
        result, output = self.run_selection(policy="non_target_only")
        self.assertEqual(result.returncode, 0, result.stderr)
        with (output / "selected_metadata.csv").open() as handle:
            selected = list(csv.DictReader(handle))
        self.assertIn("TT_99", {r["assigned_id"] for r in selected})


if __name__ == "__main__":
    unittest.main()
