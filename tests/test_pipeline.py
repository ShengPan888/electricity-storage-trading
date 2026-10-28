"""Data-contract and information-boundary tests for the real-data pipeline."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

if any(importlib.util.find_spec(name) is None for name in ("numpy", "pandas", "lightgbm")):
    raise unittest.SkipTest("Install requirements-model.txt to run pipeline tests")

import numpy as np
import pandas as pd

from storage_trading.core import optimize_day
from storage_trading.pipeline import (FEATURES, TABLES, audit_data, build_features,
                                      fit_before, read_table, validate_submission)


def frame(days=2, start="2025-01-01"):
    times = pd.date_range(start, periods=96 * days, freq="15min")
    table = pd.DataFrame({"times": times})
    for i, name in enumerate(FEATURES):
        table[name] = 2 + i / 10 + np.sin(np.arange(len(times)) / (7 + i))
    table["A"] = 1 + np.cos(np.arange(len(times)) / 20)
    return table


class PipelineTests(unittest.TestCase):
    def test_features_ignore_truth_and_actual_boundary_columns(self):
        source = frame()
        original = build_features(source, "supply_shape")
        source["A"] = -999999
        source["系统负荷实际值"] = 999999
        pd.testing.assert_frame_equal(original, build_features(source, "supply_shape"))

    def test_later_day_does_not_change_previous_day_features(self):
        source = frame()
        original = build_features(source, "supply_shape").iloc[:96]
        source.loc[96:, FEATURES] = -999
        pd.testing.assert_frame_equal(original, build_features(source, "supply_shape").iloc[:96])

    def test_duplicate_timestamps_rejected(self):
        source = frame()
        source.loc[1, "times"] = source.loc[0, "times"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "duplicate.csv"
            source.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                read_table(path, FEATURES)

    def test_audit_excludes_incomplete_truth_without_filling(self):
        source, test = frame(), frame(1, "2025-01-03")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for key, relative in TABLES.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                table = source[["times", "A"]].iloc[1:] if key == "labels" else test if key == "test" else source.drop(columns="A")
                table.to_csv(path, index=False)
            joined, _, audit = audit_data(root, root)
            self.assertEqual(len(joined), 96)
            self.assertEqual(audit["excluded_labelled_dates"], ["2025-01-01"])
            self.assertEqual(set(joined.columns), set(["times", "A"] + FEATURES))

    def test_evaluation_labels_do_not_affect_fitted_model(self):
        source = frame(66)
        x = build_features(source, "official")
        config = {"seed": 2026, "num_threads": 2, "num_boost_round": 10,
                  "early_stopping_rounds": 2,
                  "lightgbm": {"objective": "regression", "metric": "rmse", "verbosity": -1}}
        start = pd.Timestamp("2025-03-01")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            one, first = fit_before(source, x, start, config, root / "one.txt")
            source.loc[source.times.ge(start), "A"] = 1e6
            two, second = fit_before(source, x, start, config, root / "two.txt")
            np.testing.assert_array_equal(one.predict(x), two.predict(x))
            self.assertEqual(first, second)
            self.assertLess(pd.Timestamp(first["refit_end"]), start)

    def test_submission_rejects_illegal_actions_and_missing_rows(self):
        test = frame(1)
        plan = optimize_day(list(range(96)))
        output = pd.DataFrame({"times": test.times, "实时价格": range(96), "power": plan.power})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "output.csv"
            output.to_csv(path, index=False)
            self.assertTrue(validate_submission(path, test)["all_days_legal"])
            output.loc[0, "power"] = 1000
            output.to_csv(path, index=False)
            with self.assertRaises(ValueError):
                validate_submission(path, test)
            output.iloc[:-1].to_csv(path, index=False)
            with self.assertRaises(ValueError):
                validate_submission(path, test)


if __name__ == "__main__":
    unittest.main()
