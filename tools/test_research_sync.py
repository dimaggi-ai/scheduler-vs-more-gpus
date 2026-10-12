"""Regression checks for the missed paper update and rounding discrepancy."""
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from sync_research import ROOT, REVIEWED_FIGURE_ARTIFACTS, aggregate, blocks, load_rows, replace_block, synchronize


class PublicationConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".research-test-", dir=ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for relative in ("README.md", "paper/paper.md", "results/results.csv", "evidence.json", *REVIEWED_FIGURE_ARTIFACTS):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)

    def mutate_csv(self, change):
        path = self.root / "results/results.csv"
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            names = reader.fieldnames
            rows = list(reader)
        change(rows)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=names, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_committed_publication_is_consistent(self):
        self.assertEqual(synchronize(self.root), [])

    def test_round_once_from_unrounded_means(self):
        rendered = blocks(aggregate(load_rows(self.root / "results/results.csv")))
        self.assertIn("~64,267 modeled", rendered["headline"])
        self.assertIn("~89.3 continuously", rendered["headline"])
        self.assertNotIn("64,268", rendered["headline"])

    def test_missing_or_replaced_published_figure_refused(self):
        for relative in REVIEWED_FIGURE_ARTIFACTS[1:]:
            path = self.root / relative
            original = path.read_bytes()
            for replacement in (None, b"superseded plot"):
                if replacement is None:
                    path.unlink()
                else:
                    path.write_bytes(replacement)
                self.assertTrue(any(relative in error for error in synchronize(self.root)))
            path.write_bytes(original)
        self.assertEqual(synchronize(self.root), [])

    def test_figure_manifest_entry_cannot_be_removed_or_duplicated(self):
        path = self.root / "evidence.json"
        original = path.read_text()
        for relative in REVIEWED_FIGURE_ARTIFACTS:
            for duplicate in (False, True):
                data = json.loads(original)
                entry = next(a for a in data["artifacts"] if a["path"] == relative)
                if duplicate:
                    data["artifacts"].append(entry.copy())
                else:
                    data["artifacts"].remove(entry)
                path.write_text(json.dumps(data))
                self.assertTrue(any(relative in error for error in synchronize(self.root)))
        path.write_text(original)

    def test_changed_figure_generator_requires_reviewed_reseal(self):
        path = self.root / "sim/run.py"
        path.write_text(path.read_text().replace('"Stranded capacity, thousand GPU-hours / 30 days"', '"Different interpretation"'))
        manifest = (self.root / "evidence.json").read_bytes()
        self.assertTrue(any("sim/run.py" in error for error in synchronize(self.root, write=True)))
        self.assertEqual((self.root / "evidence.json").read_bytes(), manifest)

    def test_stale_whitepaper_fails_and_explicit_refresh_repairs(self):
        path = self.root / "paper/paper.md"
        path.write_text(path.read_text().replace("**83.7%**", "**85.8%**", 1))
        self.assertTrue(any("paper/paper.md" in error for error in synchronize(self.root)))
        self.assertEqual(synchronize(self.root, write=True), [])
        self.assertEqual(synchronize(self.root), [])

    def test_readme_table_and_findings_drift_is_detected(self):
        path = self.root / "README.md"
        path.write_text(path.read_text().replace("0.837", "0.858", 1).replace("~1,083 resizes", "~1,232 resizes", 1))
        self.assertTrue(any("README.md" in error for error in synchronize(self.root)))

    def test_changed_run_requires_all_publication_updates(self):
        def change(rows):
            for row in rows:
                if row["policy"] == "intent-closed-loop" and row["scenario"] == "S4-full":
                    row["productive_gpu_h"] = str(float(row["productive_gpu_h"]) + 100)
        self.mutate_csv(change)
        errors = synchronize(self.root)
        for expected in ("README.md", "paper/paper.md", "S4 productive difference"):
            self.assertTrue(any(expected in error for error in errors), errors)

    def test_stale_evidence_value_is_not_silently_rewritten(self):
        path = self.root / "evidence.json"
        data = json.loads(path.read_text())
        for row in data["results"]:
            if row["name"] == "S4 productive difference":
                row["value"] = 64268
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        self.assertTrue(any("S4 productive difference" in error for error in synchronize(self.root, write=True)))
        self.assertEqual(path.read_bytes(), before)

    def test_duplicate_or_missing_experiment_rows_refused(self):
        self.mutate_csv(lambda rows: rows.append(rows[0].copy()))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_rows(self.root / "results/results.csv")
        self.mutate_csv(lambda rows: rows.pop())
        self.mutate_csv(lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "incomplete"):
            load_rows(self.root / "results/results.csv")

    def test_nonfinite_metrics_refused(self):
        self.mutate_csv(lambda rows: rows[0].__setitem__("productive_gpu_h", "nan"))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            load_rows(self.root / "results/results.csv")

    def test_different_horizon_not_silently_labeled_30_days(self):
        self.mutate_csv(lambda rows: rows[0].__setitem__("nominal_gpu_h", "24576"))
        with self.assertRaisesRegex(ValueError, "30-day"):
            load_rows(self.root / "results/results.csv")

    def test_markers_cannot_be_missing_duplicate_or_reversed(self):
        for text in ("", "<!-- research:headline:begin -->" * 2 + "<!-- research:headline:end -->",
                     "<!-- research:headline:end --><!-- research:headline:begin -->"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                replace_block(text, "headline", "replacement")


if __name__ == "__main__":
    unittest.main()
