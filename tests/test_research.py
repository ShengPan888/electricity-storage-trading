"""Contracts for published aggregates and the newly exposed frozen specification."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from storage_trading.research_report import build_report

ROOT = Path(__file__).resolve().parents[1]


class PublicResearchTests(unittest.TestCase):
    def test_aggregate_provenance_and_selection(self):
        provenance = json.loads((ROOT / "research/provenance.json").read_text(encoding="utf-8"))
        for source in provenance["source_files"]:
            self.assertEqual(hashlib.sha256((ROOT / "research" / source["public_file"]).read_bytes()).hexdigest(), source["sha256"])
        data = json.loads((ROOT / "research/results.json").read_text(encoding="utf-8"))
        self.assertEqual(data["complete_days"], 92)
        self.assertEqual(data["rows"], 8832)
        self.assertIsNone(data["official_test_metrics"])
        self.assertEqual([r["id"] for r in data["models"] if r["selected"]], ["phase2_frozen"])
        self.assertTrue(all(r["high_recall"] == 0 and r["high_precision"] is None for r in data["models"]))

    def test_figures_are_valid_svg_and_report_runs_offline(self):
        for name in ["project_workflow.svg", "accuracy_profit.svg"]:
            ET.parse(ROOT / "docs/assets" / name)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "new"
            page = build_report(output).read_text(encoding="utf-8")
            self.assertIn("112", page)
            self.assertIn("7021.77", page)
            self.assertIn('id="model"', page)
            self.assertNotIn('<script src=', page)
            self.assertNotIn('<img src="http', page)
            with self.assertRaises(FileExistsError):
                build_report(output)


@unittest.skipIf(any(importlib.util.find_spec(n) is None for n in ["pandas", "numpy", "lightgbm"]),
                     "Install requirements-model.txt to run feature checks")
class FrozenContractTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        import pandas as pd
        from storage_trading.research import FEATURES
        self.frame = pd.DataFrame({"times": pd.date_range("2025-01-01", periods=96 * 40, freq="15min")})
        for i, name in enumerate(FEATURES):
            self.frame[name] = 2 + i / 10 + np.sin(np.arange(len(self.frame)) / 37)
        self.frame["A"] = 1.0

    def test_19_columns_ignore_actuals_and_zero_division(self):
        import numpy as np
        import pandas as pd
        from storage_trading.research import COLUMNS, FEATURES, frozen_features
        initial = frozen_features(self.frame)
        self.frame["A"] = -1e9
        for name in FEATURES:
            self.frame[name.replace("预测", "实际")] = 1e9
        pd.testing.assert_frame_equal(initial, frozen_features(self.frame))
        self.assertEqual(list(initial), COLUMNS)
        self.assertEqual(len(COLUMNS), 19)
        self.frame.loc[0, FEATURES[0]] = 0
        self.assertTrue(np.isnan(frozen_features(self.frame).loc[0, "renewable_ratio_candidate"]))

    def test_chronology_stays_in_training(self):
        import pandas as pd
        from storage_trading.research import chronological_masks
        start = pd.Timestamp("2025-02-01")
        outer, train, tune = chronological_masks(self.frame.times, start)
        self.assertLess(self.frame.loc[train, "times"].max(), self.frame.loc[tune, "times"].min())
        self.assertLess(self.frame.loc[tune, "times"].max(), start)
        self.assertTrue((outer == (train | tune)).all())

    def test_incomplete_prices_kept_for_accuracy_not_profit(self):
        import numpy as np
        from storage_trading.research import evaluate, frozen_features
        frame = self.frame.iloc[:191].copy()
        metrics, daily, actions = evaluate(frame, np.ones(len(frame)), np.ones(96))
        self.assertEqual(metrics["rows"], 191)
        self.assertEqual(metrics["complete_days"], 1)
        self.assertEqual(len(daily), 1)
        self.assertEqual(len(actions), 96)
        frame.loc[1, "times"] = frame.loc[0, "times"]
        with self.assertRaises(ValueError):
            frozen_features(frame)
