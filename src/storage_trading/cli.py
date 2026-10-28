"""Runnable demo, prediction-to-submission conversion, and offline evaluation."""

import argparse
import csv
import html
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

from .core import checked_prices, optimize_day, settle


def read_days(path: Path, *, require_truth: bool) -> list[tuple[list[str], list[float], list[float] | None]]:
    """Read a strict forecast artifact; timestamps are naive Beijing local time.

    The forecasting pipeline must provide times,pred_price and optionally true_price.
    No date sorting, gap filling, timezone guessing, or duplicate removal is hidden.
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        needed = {"times", "pred_price"}
        if require_truth:
            needed.add("true_price")
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError(f"Required columns: {sorted(needed)}")
        rows = list(reader)
    if not rows:
        raise ValueError("Forecast CSV is empty")
    groups = {}
    previous = None
    for row in rows:
        timestamp = datetime.fromisoformat(row["times"])
        if timestamp.tzinfo is not None:
            raise ValueError("Expected naive Beijing timestamps; align timezones upstream")
        if previous is not None and timestamp <= previous:
            raise ValueError("Timestamps must be strictly increasing without duplicates")
        previous = timestamp
        groups.setdefault(timestamp.date(), []).append((timestamp, row))
    days = []
    for date, records in groups.items():
        midnight = datetime.combine(date, datetime.min.time())
        expected = [midnight + timedelta(minutes=15 * i) for i in range(96)]
        if [record[0] for record in records] != expected:
            raise ValueError(f"{date}: expected all 96 timestamps from 00:00 to 23:45")
        times = [record[0].isoformat(sep=" ") for record in records]
        pred = list(checked_prices(record[1]["pred_price"] for record in records))
        truth = None
        if require_truth:
            truth = list(checked_prices(record[1]["true_price"] for record in records))
        days.append((times, pred, truth))
    return days


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def process(path: Path, output: Path, *, evaluate: bool, synthetic: bool = False) -> dict:
    days = read_days(path, require_truth=evaluate)
    output.mkdir(parents=True, exist_ok=True)
    submissions, diagnostics, details = [], [], []
    for times, prediction, truth in days:
        schedule = optimize_day(prediction)
        # True prices do not enter scheduling. Oracle is computed only afterwards.
        actual_profit = settle(truth, schedule.power) if truth is not None else None
        oracle = optimize_day(truth) if truth is not None else None
        diagnostics.append({
            "date": times[0][:10],
            "charge_start": times[schedule.charge_start] if schedule.charge_start is not None else "",
            "discharge_start": times[schedule.discharge_start] if schedule.discharge_start is not None else "",
            "predicted_profit": schedule.predicted_profit,
            "actual_profit": actual_profit,
            "oracle_profit": oracle.predicted_profit if oracle else None,
            "regret": oracle.predicted_profit - actual_profit if oracle else None,
            "traded": schedule.charge_start is not None,
        })
        soc = 0
        for i, timestamp in enumerate(times):
            soc -= schedule.power[i]
            submissions.append({"times": timestamp, "实时价格": prediction[i], "power": schedule.power[i]})
            details.append({"times": timestamp, "pred_price": prediction[i],
                            "true_price": truth[i] if truth is not None else None,
                            "power": schedule.power[i], "soc_after": soc})
    write_csv(output / "output.csv", ["times", "实时价格", "power"], submissions)
    write_csv(output / "daily.csv", list(diagnostics[0]), diagnostics)
    write_csv(output / "slot_details.csv", list(details[0]), details)
    summary = {
        "synthetic_demo": synthetic,
        "days": len(days),
        "trading_days": sum(row["traded"] for row in diagnostics),
        "price_source": str(path.resolve()),
        "settlement": "sum(true_price * power); no additional 0.25 multiplier",
    }
    if evaluate:
        profits = [row["actual_profit"] for row in diagnostics]
        summary.update({
            "mean_daily_profit": sum(profits) / len(profits),
            "loss_day_fraction": sum(value < 0 for value in profits) / len(profits),
            "worst_daily_profit": min(profits),
            "mean_oracle_profit": sum(row["oracle_profit"] for row in diagnostics) / len(days),
            "mean_regret": sum(row["regret"] for row in diagnostics) / len(days),
        })
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if evaluate:
        write_report(output / "report.html", details, diagnostics, summary)
    return summary


def plot_svg(series: list[tuple[str, str, list[float]]], title: str) -> str:
    width, height, left, top = 940, 200, 65, 30
    plot_w, plot_h = 850, 130
    all_values = [value for _, _, values in series for value in values]
    low, high = min(all_values), max(all_values)
    span = high - low or 1
    result = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">',
              f'<text x="{left}" y="18">{html.escape(title)}</text>',
              f'<text x="3" y="{top + 12}">{high:.0f}</text>',
              f'<text x="3" y="{top + plot_h}">{low:.0f}</text>']
    for slot in (0, 24, 48, 72, 95):
        x = left + plot_w * slot / 95
        result.append(f'<line x1="{x}" y1="{top}" x2="{x}" y2="{top + plot_h}" stroke="#e5e7eb"/>')
        result.append(f'<text x="{x - 15}" y="185">{slot // 4:02d}:{slot % 4 * 15:02d}</text>')
    for index, (name, color, values) in enumerate(series):
        points = " ".join(f"{left + plot_w * i / 95:.2f},{top + plot_h * (high - v) / span:.2f}" for i, v in enumerate(values))
        result.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{points}"/>')
        result.append(f'<text x="{left + 300 + index * 170}" y="18" fill="{color}">{html.escape(name)}</text>')
    return "".join(result) + "</svg>"


def write_report(path: Path, details: list[dict], daily: list[dict], summary: dict) -> None:
    label = "合成数据演示：不代表比赛收益或真实市场规律" if summary["synthetic_demo"] else "离线回测：策略仅使用预测价格，真实价格仅用于结算及事后上限"
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<title>储能交易复盘</title><style>body{font:16px system-ui;max-width:1080px;margin:32px auto;padding:0 20px;color:#172033}svg{width:100%;background:#fafbfc;margin:8px 0}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}.notice{padding:16px;background:#fff3cd}section{margin:30px 0}pre{white-space:pre-wrap}</style>',
             '<h1>储能交易：预测 → 决策 → SOC → 收益</h1>',
             f'<p class="notice">{label}</p>',
             '<p>价格为赛题价格单位；power 按赛题定义为每时段 ±1000，SOC 为该时段操作后的状态。所有时间均为北京时间。</p>',
             '<table><tr><th>日期</th><th>充电开始</th><th>放电开始</th><th>预测收益</th><th>实际收益</th><th>事后最优收益</th></tr>']
    for row in daily:
        parts.append('<tr>' + ''.join(f'<td>{html.escape(str(row[key]))}</td>' for key in
                     ("date", "charge_start", "discharge_start", "predicted_profit", "actual_profit", "oracle_profit")) + '</tr>')
    parts.append('</table><p>事后最优使用真实价格计算，仅用于诊断，不能作为可提交策略。收益直接按赛题公式计算。</p>')
    for index, row in enumerate(daily):
        slots = details[index * 96:(index + 1) * 96]
        parts.append(f'<section><h2>{html.escape(row["date"])}</h2>')
        parts.append(plot_svg([("预测价格", "#2563eb", [s["pred_price"] for s in slots]),
                               ("真实价格", "#f97316", [s["true_price"] for s in slots])], "价格曲线"))
        parts.append(plot_svg([("正为放电，负为充电", "#059669", [s["power"] for s in slots])], "充放电动作"))
        parts.append(plot_svg([("操作后 SOC", "#7c3aed", [s["soc_after"] for s in slots])], "SOC（初始为 0）"))
        parts.append('</section>')
    parts.append('</html>')
    path.write_text("\n".join(parts), encoding="utf-8")


def demo(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    start = datetime(2026, 1, 1)
    for i in range(96):
        truth = 220 + 30 * math.sin(i * math.pi / 48)
        if 40 <= i < 48:
            truth = -40
        elif 72 <= i < 80:
            truth = 450
        prediction = truth + 12 * math.sin(i * math.pi / 12) + 15
        rows.append({"times": (start + timedelta(minutes=15 * i)).isoformat(sep=" "),
                     "pred_price": prediction, "true_price": truth})
    source = output / "synthetic_predictions.csv"
    write_csv(source, ["times", "pred_price", "true_price"], rows)
    return process(source, output, evaluate=True, synthetic=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Storage competition scheduling and settlement")
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo", help="Run a clearly labelled synthetic example")
    demo_parser.add_argument("--output", type=Path, default=Path("outputs/demo"))
    real = commands.add_parser("real-demo", help="Train and evaluate using official local competition files")
    real.add_argument("--data-dir", type=Path, required=True)
    real.add_argument("--output", type=Path, default=Path("outputs/real_demo"))
    real.add_argument("--config", type=Path)
    for name in ("backtest", "submit"):
        command = commands.add_parser(name)
        command.add_argument("--predictions", type=Path, required=True)
        command.add_argument("--output", type=Path, default=Path("outputs") / name)
    args = parser.parse_args()
    if args.command == "real-demo":
        from .pipeline import run_real_demo
        run_real_demo(args.data_dir, args.output, args.config)
        return
    if args.command == "demo":
        result = demo(args.output)
    else:
        result = process(args.predictions, args.output, evaluate=args.command == "backtest")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
