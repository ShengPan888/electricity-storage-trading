"""Offline view: explicit feature contract, market-rule scope and real aggregates."""
import html
import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_guide(name):
    return json.loads((ROOT / "research" / name).read_text(encoding="utf-8"))


def illustrative_features():
    """Synthetic one-row transformation; not a forecast or competition data."""
    guide = load_guide("feature_dictionary.json")
    x = {f["name"]: v for f, v in zip(guide["features"][:7], [4., 1.2, -.1, .8, .4, .2, .4])}
    t = datetime(2025, 8, 1, 13, 15)
    x.update(hour=t.hour, minute=t.minute, dayofweek=t.weekday(), month=t.month, slot_id=t.hour * 4 + t.minute // 15)
    for name, value, period in [("slot", x["slot_id"], 96), ("weekday", x["dayofweek"], 7), ("month", x["month"] - 1, 12)]:
        x[name + "_sin"] = math.sin(2 * math.pi * value / period)
        x[name + "_cos"] = math.cos(2 * math.pi * value / period)
    x["renewable_ratio_candidate"] = x["风光总加预测值"] / x["系统负荷预测值"]
    return {f["name"]: x[f["name"]] for f in guide["features"]}


def render_report() -> str:
    data = load_guide("results.json")
    guide = load_guide("feature_dictionary.json")
    rules = load_guide("market_rules.json")
    esc = lambda value: html.escape(str(value), quote=True)
    feature_rows = []
    for f in guide["features"]:
        feature_rows.append(f'<tr data-feature-row data-group="{esc(f["group"])}"><td>{f["order"]}</td><td><code>{esc(f["name"])}</code><br><span class="pill">{esc(f["group_label"])}</span></td><td>{esc(f["formula"])}</td><td>{esc(f["meaning"])}</td><td>{esc(f["availability"])}<br><strong>{esc(f["unit"])}</strong><br>{esc(f["guard"])}</td></tr>')
    excluded = ''.join('<tr>' + ''.join(f'<td>{esc(r[k])}</td>' for k in ["name", "use", "reason"]) + '</tr>' for r in guide["excluded"])
    example = ''.join(f'<tr><td><code>{esc(k)}</code></td><td>{v:.8g}</td></tr>' for k, v in illustrative_features().items())
    rule_rows = []
    for r in rules["matrix"]:
        refs = ' '.join(f'<a href="#source-{esc(k)}">[{esc(k)}]</a>' for k in r["sources"])
        rule_rows.append(f'<tr><td><strong>{esc(r["id"])} {esc(r["topic"])}</strong></td><td>{esc(r["principle"])}<br>{refs}</td><td>{esc(r["implementation"])}</td><td><span class="pill amber">{esc(r["status"])}</span></td><td>{esc(r["missing"])}</td></tr>')
    sources = ''.join(f'<article class="source" id="source-{esc(r["id"])}"><h3>[{esc(r["id"])}] <a href="{esc(r["url"])}" target="_blank" rel="noopener noreferrer">{esc(r["title"])}</a></h3><p><span class="pill{(" amber" if r["id"] == "D1" else "")}">{esc(r["status"])}</span></p><p>范围：{esc(r["scope"])}｜定位：{esc(r["locator"])}</p><p class="small muted">{esc(r["note"])}</p></article>' for r in rules["sources"])
    flow = ''.join(f'<div class="flow-item"><strong>{i+1:02d} {esc(r["step"])}</strong><span class="pill">{esc(r["status"])}</span><div class="small">{esc(r["purpose"])}</div></div>' for i,r in enumerate(rules["workflow"]))
    formulas = ''.join(f'<details><summary>{esc(r["name"])}</summary><p class="formula">{esc(r["formula"])}</p><p>仍缺：{esc(r["missing"])}</p></details>' for r in rules["draft_formulas"])
    rows = []
    for r in data["models"]:
        cls = ' class="selected"' if r["selected"] else ""
        rows.append(f'<tr{cls}><td>{esc(r["label"])}</td><td>{r["r2"]:.6f}</td><td>{r["mae"]:.6f}</td><td>{r["rmse"]:.6f}</td><td>{r["mean_daily_profit"]:.2f}</td><td>{r["capture"]:.2%}</td></tr>')
    options = ''.join(f'<option value="{esc(r["id"])}">{esc(r["label"])}</option>' for r in data["models"])
    figure = (ROOT / "docs/assets/accuracy_profit.svg").read_text(encoding="utf-8")
    values = {"FEATURE_ROWS": ''.join(feature_rows), "EXCLUDED_ROWS": excluded, "EXAMPLE_ROWS": example,
              "RULE_ROWS": ''.join(rule_rows), "SOURCES": sources, "BUSINESS_FLOW": flow, "DRAFT_FORMULAS": formulas,
              "OPTIONS": options, "RESULT_ROWS": ''.join(rows), "FIGURE": figure[figure.index("<svg"):],
              "WORKFLOW": (ROOT / "docs/assets/project_workflow.svg").read_text(encoding="utf-8"),
              "PAYLOAD": json.dumps(data, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")}
    page = Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def build_report(output: Path) -> Path:
    if output.exists():
        raise FileExistsError("Choose a new directory to preserve previous reports")
    page = render_report()
    output.mkdir(parents=True, exist_ok=False)
    path = output / "index.html"
    path.write_text(page, encoding="utf-8")
    return path.resolve()
