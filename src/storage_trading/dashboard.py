"""Build a self-contained local HTML dashboard; no remote scripts or services."""

import json
from pathlib import Path

import pandas as pd


def collect_days(folder: Path) -> list[dict]:
    slots = pd.read_csv(folder / "slot_details.csv", encoding="utf-8-sig")
    daily = pd.read_csv(folder / "daily.csv", encoding="utf-8-sig").fillna("")
    days = []
    for _, row in daily.iterrows():
        date = row["date"]
        selected = slots[slots.times.str.startswith(date)]
        truth = None if selected.true_price.isna().all() else selected.true_price.to_list()
        power = selected.power.astype(int).to_list()
        days.append({"date": date, "pred": selected.pred_price.to_list(), "actual": truth,
                     "power": power, "soc": [0] + selected.soc_after.astype(int).to_list(),
                     "charge": next((i for i, value in enumerate(power) if value < 0), None),
                     "discharge": next((i for i, value in enumerate(power) if value > 0), None),
                     "predictedProfit": float(row.predicted_profit),
                     "actualProfit": None if truth is None else float(row.actual_profit),
                     "oracleProfit": None if truth is None else float(row.oracle_profit)})
    return days


def create_dashboard(output: Path, summary: dict) -> None:
    payload = {
        "selected": summary["selected_model"],
        "audit": summary["data_audit"],
        "developmentComparison": summary["development_comparison"],
        "holdoutComparison": summary["holdout_comparison"],
        "sections": [
            {"label": "开发回测 · 2025.10—11", "kind": "development", "days": collect_days(output / "development")},
            {"label": "独立留出 · 2025.12", "kind": "holdout", "days": collect_days(output / "holdout")},
            {"label": "测试策略 · 2026.01—02", "kind": "submission", "days": collect_days(output / "submission")},
        ],
    }
    template = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace("</", "<\\/")
    (output / "index.html").write_text(template.replace("__DEMO_DATA__", data), encoding="utf-8")
