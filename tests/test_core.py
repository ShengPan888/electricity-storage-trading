import csv
import math
import random
import tempfile
import unittest
from pathlib import Path

from storage_trading.cli import process, read_days, write_csv
from storage_trading.core import optimize_day, settle, validate_power


class StorageTests(unittest.TestCase):
    def test_first_and_last_windows_and_exact_profit(self):
        prices = [200.0] * 96
        prices[:8] = [100.0] * 8
        prices[88:] = [300.0] * 8
        plan = optimize_day(prices)
        self.assertEqual((plan.charge_start, plan.discharge_start), (0, 88))
        self.assertEqual(settle(prices, plan.power), 1_600_000)

    def test_flat_and_decreasing_choose_no_trade(self):
        for prices in ([50] * 96, [0.1] * 96, [-0.1] * 96, list(range(96, 0, -1))):
            self.assertEqual(optimize_day(prices).power, (0,) * 96)

    def test_arbitrage_when_both_windows_have_negative_prices(self):
        plan = optimize_day([-100] * 8 + [-20] * 88)
        self.assertEqual((plan.charge_start, plan.discharge_start), (0, 8))
        self.assertEqual(plan.predicted_profit, 640_000)

    def test_optimizer_matches_independent_linear_scan(self):
        rng = random.Random(2026)
        for _ in range(30):
            prices = [rng.uniform(-100, 800) for _ in range(96)]
            windows = [sum(prices[s:s + 8]) for s in range(89)]
            cheapest, best = math.inf, 0.0
            for d in range(8, 89):
                cheapest = min(cheapest, windows[d - 8])
                best = max(best, 1000 * (windows[d] - cheapest))
            self.assertAlmostEqual(optimize_day(prices).predicted_profit, best, places=6)

    def test_invalid_cycles_are_rejected(self):
        bad = [
            [1000] * 8 + [-1000] * 8 + [0] * 80,
            [-1000] * 4 + [0] + [-1000] * 4 + [1000] * 8 + [0] * 79,
            [-1000] * 16 + [1000] * 16 + [0] * 64,
            [-1000] * 8 + [0] * 88,
        ]
        for actions in bad:
            with self.assertRaises(ValueError):
                validate_power(actions)

    def test_soc_stays_within_bounds_and_returns_to_zero(self):
        power = optimize_day(list(range(96))).power
        soc = 0
        for action in power:
            soc -= action
            self.assertTrue(0 <= soc <= 8000)
        self.assertEqual(soc, 0)

    def test_invalid_prices_rejected(self):
        for prices in ([1] * 95, [float("nan")] * 96, [float("inf")] * 96):
            with self.assertRaises(ValueError):
                optimize_day(prices)

    def test_truth_cannot_change_scheduled_actions(self):
        from datetime import datetime, timedelta
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [{"times": str(datetime(2026, 1, 1) + timedelta(minutes=15 * i)),
                     "pred_price": i, "true_price": -i} for i in range(96)]
            source = root / "forecast.csv"
            write_csv(source, ["times", "pred_price", "true_price"], rows)
            result = process(source, root / "one", evaluate=True)
            first = (root / "one/output.csv").read_text(encoding="utf-8-sig")
            for row in rows:
                row["true_price"] = 999
            write_csv(source, ["times", "pred_price", "true_price"], rows)
            process(source, root / "two", evaluate=True)
            second = (root / "two/output.csv").read_text(encoding="utf-8-sig")
            self.assertEqual(first, second)
            self.assertLess(result["mean_daily_profit"], 0)
            self.assertGreaterEqual(result["mean_regret"], 0)
            with (root / "two/output.csv").open(encoding="utf-8-sig") as stream:
                self.assertEqual(csv.DictReader(stream).fieldnames, ["times", "实时价格", "power"])

    def test_incomplete_day_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "missing.csv"
            write_csv(path, ["times", "pred_price"], [{"times": "2026-01-01 00:00:00", "pred_price": 100}])
            with self.assertRaises(ValueError):
                read_days(path, require_truth=False)


if __name__ == "__main__":
    unittest.main()
