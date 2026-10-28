"""Audited official-data demo: time-separated learning, dispatch, and settlement.

All model inputs are supplied forecast columns and calendar variables. Actual
boundary conditions never enter features. Price labels are used only in the
training partition or, after scheduling, for evaluation.
"""

import hashlib
import importlib.metadata
import json
import platform
import zipfile
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from .cli import process, write_csv
from .core import optimize_day, settle, validate_power

FEATURES = ["系统负荷预测值", "风光总加预测值", "联络线预测值", "风电预测值",
            "光伏预测值", "水电预测值", "非市场化机组预测值"]
TABLES = {"features": "train/mengxi_boundary_anon_filtered.csv",
          "labels": "train/mengxi_node_price_selected.csv",
          "test": "test/test_in_feature_ori.csv"}
ROOT = Path(__file__).resolve().parents[2]


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def locate_data(folder: Path) -> Path:
    for candidate in (folder, folder / "to_sais_new", folder / "extracted/to_sais_new"):
        if all((candidate / name).is_file() for name in TABLES.values()):
            return candidate
    archive = folder / "to_sais_new.zip"
    if not archive.is_file():
        raise FileNotFoundError("Supply the official archive folder or extracted data root")
    destination = folder / "extracted"
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        for relative in TABLES.values():
            name = "to_sais_new/" + relative
            target = (destination / name).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Archive path escaped destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zipped.read(name))
    return destination / "to_sais_new"


def read_table(path: Path, expected: list[str]) -> pd.DataFrame:
    table = pd.read_csv(path, encoding="utf-8-sig")
    missing = set(["times"] + expected) - set(table.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)}")
    table["times"] = pd.to_datetime(table["times"], format="mixed", errors="raise")
    ts = table["times"]
    if ts.isna().any() or ts.dt.tz is not None:
        raise ValueError("Expected valid naive Beijing timestamps")
    if ts.duplicated().any():
        raise ValueError(f"{path.name}: duplicate timestamps")
    if ((ts.dt.minute % 15 != 0) | (ts.dt.second != 0) | (ts.dt.microsecond != 0)).any():
        raise ValueError("Timestamps must lie on the 15-minute grid")
    for col in expected:
        table[col] = pd.to_numeric(table[col], errors="raise")
        if not np.isfinite(table[col].to_numpy(dtype=float)).all():
            raise ValueError(f"{path.name}: non-finite values in {col}")
    return table.sort_values("times").reset_index(drop=True)


def complete_dates(table: pd.DataFrame) -> set:
    counts = table.groupby(table["times"].dt.date).size()
    # Unique aligned timestamps plus exactly 96 slots imply full calendar coverage.
    return set(counts[counts.eq(96)].index)


def audit_data(data: Path, output: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    frames = {key: read_table(data / name, ["A"] if key == "labels" else FEATURES)
              for key, name in TABLES.items()}
    info = {}
    for key, table in frames.items():
        counts = table.groupby(table["times"].dt.date).size()
        info[key] = {
            "file": TABLES[key], "sha256": hashlib.sha256((data / TABLES[key]).read_bytes()).hexdigest(),
            "rows": len(table), "columns": table.columns.tolist(),
            "start": str(table.times.min()), "end": str(table.times.max()),
            "complete_days": len(complete_dates(table)),
            "incomplete_days": {str(k): int(v) for k, v in counts[counts.ne(96)].items()},
            "null_counts": {str(k): int(v) for k, v in table.isna().sum().items()},
        }
    # Explicitly exclude actual boundary columns at the earliest possible step.
    joined = frames["features"][["times"] + FEATURES].merge(
        frames["labels"][["times", "A"]], on="times", validate="one_to_one")
    valid_dates = complete_dates(joined)
    excluded = sorted(set(joined.times.dt.date) - valid_dates)
    joined = joined[joined.times.dt.date.isin(valid_dates)].reset_index(drop=True)
    test = frames["test"][["times"] + FEATURES].copy()
    if len(complete_dates(test)) * 96 != len(test):
        raise ValueError("Test data contain incomplete days; refusing to fabricate input rows")
    if joined.times.max() >= test.times.min():
        raise ValueError("Test period must strictly follow all training labels")
    price = frames["labels"]["A"]
    info.update({
        "complete_labelled_days_used": len(valid_dates), "labelled_rows_used": len(joined),
        "excluded_labelled_dates": [str(date) for date in excluded],
        "price_min": float(price.min()), "price_max": float(price.max()),
        "negative_price_fraction": float(price.lt(0).mean()),
        "wind_solar_additivity_max_abs_error": float((frames["features"][FEATURES[1]] - frames["features"][FEATURES[3]] - frames["features"][FEATURES[4]]).abs().max()),
        "units": "Official processed/anonymized values; no conversion to RMB or MW",
        "forecast_availability": "Using the same seven forecast columns as official baseline; exact original publication cutoffs are not provided",
        "weather_used": False,
    })
    save_json(output / "data_audit.json", info)
    text = ["# Official data audit", "", "No actual boundary columns or weather variables enter this demo.",
            "Incomplete labelled days are excluded from both training and evaluation; no labels are imputed.",
            "", f"Complete labelled days used: {len(valid_dates)}; excluded: {', '.join(map(str, excluded))}.",
            "", "Numbers use the competition's processed units, not RMB/MW.", "",
            "| Table | Rows | First timestamp | Last timestamp | Full days |", "|---|---:|---|---|---:|"]
    for key in TABLES:
        row = info[key]
        text.append(f"| {key} | {row['rows']} | {row['start']} | {row['end']} | {row['complete_days']} |")
    (output / "data_audit.md").write_text("\n".join(text), encoding="utf-8")
    return joined, test, info


def build_features(table: pd.DataFrame, mode: str) -> pd.DataFrame:
    ts = table["times"]
    x = table[FEATURES].astype(float).copy()
    x["hour"], x["minute"] = ts.dt.hour, ts.dt.minute
    x["dayofweek"], x["month"] = ts.dt.dayofweek, ts.dt.month
    if mode == "official":
        return x
    if mode != "supply_shape":
        raise ValueError(f"Unknown feature mode: {mode}")
    slot = ts.dt.hour * 4 + ts.dt.minute // 15
    x["slot_sin"] = np.sin(2 * np.pi * slot / 96)
    x["slot_cos"] = np.cos(2 * np.pi * slot / 96)
    load, renewable, tie, wind, solar, hydro, fixed = (x[col] for col in FEATURES)
    x["net_load_proxy"] = load - renewable
    x["renewable_load_ratio_proxy"] = renewable / load.replace(0, np.nan)
    x["solar_wind_ratio_proxy"] = solar / wind.replace(0, np.nan)
    residual = load - renewable - hydro - fixed
    # Tie-line direction and anonymization scales are not documented. These are
    # numerical candidate proxies, not asserted physical balances or true shares.
    x["residual_minus_tie_proxy"] = residual - tie
    x["residual_plus_tie_proxy"] = residual + tie
    dates = ts.dt.date
    for col in FEATURES + ["net_load_proxy"]:
        group = x[col].groupby(dates)
        x[col + "_day_mean"] = group.transform("mean")
        x[col + "_day_range"] = group.transform("max") - group.transform("min")
        x[col + "_vs_day_mean"] = x[col] - group.transform("mean")
        x[col + "_change_1h"] = x[col] - group.shift(4)
        x[col + "_next_1h_change"] = group.shift(-4) - x[col]
    return x.replace([np.inf, -np.inf], np.nan)


def month_bounds(month: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(month + "-01")
    return start, start + pd.offsets.MonthBegin(1)


def fit_before(frame: pd.DataFrame, x: pd.DataFrame, start: pd.Timestamp,
               config: dict, save_path: Path) -> tuple[lgb.Booster, dict]:
    tuning_start = start - pd.offsets.MonthBegin(1)
    train_mask = frame.times.lt(tuning_start)
    tuning_mask = frame.times.ge(tuning_start) & frame.times.lt(start)
    refit_mask = frame.times.lt(start)
    if train_mask.sum() < 96 * 30 or tuning_mask.sum() < 96 * 7:
        raise ValueError("Need at least 30 training and 7 tuning days before evaluation")
    params = dict(config["lightgbm"], seed=config["seed"], num_threads=config["num_threads"],
                  deterministic=True, force_col_wise=True)
    train_set = lgb.Dataset(x.loc[train_mask], label=frame.loc[train_mask, "A"])
    tune_set = lgb.Dataset(x.loc[tuning_mask], label=frame.loc[tuning_mask, "A"], reference=train_set)
    trial = lgb.train(params, train_set, num_boost_round=config["num_boost_round"],
                      valid_sets=[tune_set], callbacks=[lgb.early_stopping(config["early_stopping_rounds"], verbose=False)])
    rounds = trial.best_iteration or config["num_boost_round"]
    model = lgb.train(params, lgb.Dataset(x.loc[refit_mask], label=frame.loc[refit_mask, "A"]),
                      num_boost_round=rounds)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(save_path))
    record = {
        "early_stop_train_end": str(frame.loc[train_mask, "times"].max()),
        "tuning_start": str(tuning_start), "tuning_end": str(frame.loc[tuning_mask, "times"].max()),
        "refit_end": str(frame.loc[refit_mask, "times"].max()),
        "evaluation_start": str(start), "rounds": int(rounds), "features": list(x.columns),
        "refit_rows": int(refit_mask.sum()), "params": params,
    }
    assert pd.Timestamp(record["refit_end"]) < start
    save_json(save_path.with_suffix(".json"), record)
    return model, record


def evaluate_predictions(frame: pd.DataFrame, prediction: np.ndarray, name: str) -> tuple[dict, pd.DataFrame]:
    scored = frame[["times", "A"]].copy()
    scored["pred_price"] = prediction
    records = []
    for date, day in scored.groupby(scored.times.dt.date, sort=True):
        plan = optimize_day(day.pred_price.to_list())
        truth = day.A.to_list()
        actual = settle(truth, plan.power)
        oracle = optimize_day(truth).predicted_profit
        records.append({"date": str(date), "model": name, "actual_profit": actual,
                        "predicted_profit": plan.predicted_profit, "oracle_profit": oracle,
                        "regret": oracle - actual, "charge_slot": plan.charge_start,
                        "discharge_slot": plan.discharge_start, "traded": plan.charge_start is not None})
    daily = pd.DataFrame(records)
    error = scored.pred_price.to_numpy() - scored.A.to_numpy()
    metrics = {"model": name, "days": len(daily),
               "mean_daily_profit": float(daily.actual_profit.mean()),
               "loss_day_fraction": float(daily.actual_profit.lt(0).mean()),
               "worst_daily_profit": float(daily.actual_profit.min()),
               "mean_oracle_profit": float(daily.oracle_profit.mean()),
               "mae": float(np.mean(np.abs(error))), "rmse": float(np.sqrt(np.mean(error ** 2)))}
    return metrics, daily


def reference_predictions(history: pd.DataFrame, future: pd.DataFrame) -> np.ndarray:
    slot = history.times.dt.hour * 4 + history.times.dt.minute // 15
    profile = history.groupby(slot).A.mean()
    future_slot = future.times.dt.hour * 4 + future.times.dt.minute // 15
    return future_slot.map(profile).to_numpy()


def validation_export(table: pd.DataFrame, prediction: np.ndarray, output: Path) -> dict:
    artifact = table[["times", "A"]].rename(columns={"A": "true_price"}).copy()
    artifact["pred_price"] = prediction
    source = output / "predictions.csv"
    source.parent.mkdir(parents=True, exist_ok=True)
    artifact[["times", "pred_price", "true_price"]].to_csv(source, index=False, encoding="utf-8-sig")
    return process(source, output, evaluate=True)


def validate_submission(path: Path, test: pd.DataFrame, official_demo: Path | None = None) -> dict:
    table = pd.read_csv(path, encoding="utf-8-sig")
    if list(table.columns) != ["times", "实时价格", "power"]:
        raise ValueError("Submission column names/order do not match official format")
    ts = pd.to_datetime(table.times, format="mixed")
    if not ts.reset_index(drop=True).equals(test.times.reset_index(drop=True)):
        raise ValueError("Submission timestamps differ from input")
    if not np.isfinite(table[["实时价格", "power"]].to_numpy(dtype=float)).all():
        raise ValueError("Submission contains non-finite values")
    for _, day in table.groupby(ts.dt.date):
        validate_power(day.power.to_list())
    matched_demo = None
    if official_demo is not None and official_demo.is_file():
        demo = pd.read_csv(official_demo, encoding="utf-8-sig")
        matched_demo = list(demo.columns) == list(table.columns) and pd.to_datetime(demo.times, format="mixed").equals(ts)
        if not matched_demo:
            raise ValueError("Official output_demo timestamps/schema do not match generated output")
    return {"rows": len(table), "days": len(complete_dates(test)), "all_days_legal": True,
            "matches_official_demo": matched_demo, "test_profit": None,
            "reason": "Test labels are not provided; no test profit is claimed"}


def run_real_demo(folder: Path, output: Path, config_path: Path | None = None) -> dict:
    from .dashboard import create_dashboard
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if config_path is None:
        repository_config = ROOT / "configs/demo.json"
        config_path = repository_config if repository_config.is_file() else Path(__file__).with_name("demo_config.json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    package = Path(__file__).resolve().parent
    source_files = sorted(package.glob("*.py")) + sorted(package.glob("*.html"))
    source_files += [path for path in (ROOT / "run.py", ROOT / "requirements-model.txt", config_path) if path.is_file()]
    source_manifest = {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else path.name:
                       hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    save_json(output / "source_manifest.json", source_manifest)
    (output / "config.json").write_bytes(config_path.read_bytes())
    data = locate_data(folder)
    frame, test, audit = audit_data(data, output)
    print(f"Audit complete: {len(frame) // 96} training days; {len(test) // 96} test days", flush=True)
    columns = {mode: build_features(frame, mode) for mode in config["candidates"]}
    predictions, development_parts, model_records = {}, [], []
    reference_parts = []
    for month in config["development_months"]:
        start, end = month_bounds(month)
        mask = frame.times.ge(start) & frame.times.lt(end)
        valid = frame.loc[mask].copy()
        if valid.empty:
            raise ValueError(f"No data for configured development month {month}")
        reference_parts.append(pd.Series(reference_predictions(frame[frame.times.lt(start)], valid), index=valid.index))
        for mode in config["candidates"]:
            print(f"Training {mode} for development {month} (earlier-month tuning only)", flush=True)
            model, record = fit_before(frame, columns[mode], start, config, output / "models" / f"{mode}_{month}.txt")
            model_records.append(dict(record, mode=mode, phase="development", month=month))
            predictions.setdefault(mode, []).append(pd.Series(model.predict(columns[mode].loc[mask]), index=valid.index))
        development_parts.append(valid)
    development = pd.concat(development_parts).sort_values("times")
    comparisons, daily_tables = [], []
    dev_predictions = {}
    for mode in config["candidates"]:
        pred = pd.concat(predictions[mode]).reindex(development.index).to_numpy()
        dev_predictions[mode] = pred
        metrics, daily = evaluate_predictions(development, pred, mode)
        comparisons.append(metrics)
        daily_tables.append(daily)
    selected = max(comparisons, key=lambda row: row["mean_daily_profit"])["model"]
    # Freeze selection before the final holdout is evaluated. Ties retain official.
    decision = {"selected": selected, "selection_periods": config["development_months"],
                "metric": config["selection_metric"], "candidate_metrics": [dict(row) for row in comparisons],
                "config_sha256": config_hash,
                "holdout_used_for_selection": False}
    save_json(output / "selection.json", decision)
    print(f"Selection frozen using development only: {selected}", flush=True)
    ref_pred = pd.concat(reference_parts).reindex(development.index).to_numpy()
    ref_metrics, ref_daily = evaluate_predictions(development, ref_pred, "fixed_training_profile")
    comparisons.append(ref_metrics)
    daily_tables.append(ref_daily)
    pd.concat(daily_tables).to_csv(output / "development_comparison_daily.csv", index=False)
    pd.DataFrame(comparisons).to_csv(output / "development_comparison.csv", index=False)
    development_summary = validation_export(development, dev_predictions[selected], output / "development")
    no_trade = {"model": "no_trade", "days": len(development) // 96, "mean_daily_profit": 0.0,
                "loss_day_fraction": 0.0, "worst_daily_profit": 0.0, "mae": None, "rmse": None}
    comparisons.append(no_trade)
    hold_start, hold_end = month_bounds(config["holdout_month"])
    if development.times.max() >= hold_start:
        raise ValueError("Final holdout must strictly follow development months")
    hold_mask = frame.times.ge(hold_start) & frame.times.lt(hold_end)
    holdout = frame.loc[hold_mask].copy()
    if holdout.empty:
        raise ValueError("Final holdout is empty")
    hold_comparisons, hold_pred = [], None
    for mode in dict.fromkeys(["official", selected]):
        print(f"Evaluating frozen {mode} on final holdout {config['holdout_month']}", flush=True)
        model, record = fit_before(frame, columns[mode], hold_start, config, output / "models" / f"{mode}_holdout.txt")
        model_records.append(dict(record, mode=mode, phase="holdout"))
        pred = model.predict(columns[mode].loc[hold_mask])
        metric, daily = evaluate_predictions(holdout, pred, mode)
        hold_comparisons.append(metric)
        daily.to_csv(output / f"holdout_{mode}_daily.csv", index=False)
        if mode == selected:
            hold_pred = pred
    hold_ref = reference_predictions(frame[frame.times.lt(hold_start)], holdout)
    metric, _ = evaluate_predictions(holdout, hold_ref, "fixed_training_profile")
    hold_comparisons.extend([metric, dict(no_trade, days=len(holdout) // 96)])
    holdout_summary = validation_export(holdout, hold_pred, output / "holdout")
    # Deployment may now train on all supplied 2025 labels; test truth is absent.
    test_start = test.times.min().normalize()
    print(f"Refitting {selected} on all available historical labels for 59-day test inference", flush=True)
    model, record = fit_before(frame, columns[selected], test_start, config, output / "models/deployment.txt")
    model_records.append(dict(record, mode=selected, phase="deployment"))
    test_pred = model.predict(build_features(test, selected))
    test_source = output / "test_predictions.csv"
    pd.DataFrame({"times": test.times, "pred_price": test_pred}).to_csv(test_source, index=False, encoding="utf-8-sig")
    process(test_source, output / "submission", evaluate=False)
    demo_path = folder / "output_demo.csv"
    submission = validate_submission(output / "submission/output.csv", test, demo_path)
    save_json(output / "submission/validation.json", submission)
    versions = {name: importlib.metadata.version(name) for name in ("numpy", "pandas", "lightgbm")}
    versions["python"] = platform.python_version()
    summary = {"selected_model": selected, "data_audit": audit,
               "development": development_summary, "holdout": holdout_summary,
               "development_comparison": comparisons, "holdout_comparison": hold_comparisons,
               "submission": submission, "models": model_records, "versions": versions,
               "selection": decision, "config_sha256": config_hash,
               "source_sha256": source_manifest}
    save_json(output / "experiment.json", summary)
    create_dashboard(output, summary)
    print(json.dumps({"selected_model": selected, "development_mean_daily_profit": development_summary["mean_daily_profit"],
                      "holdout_mean_daily_profit": holdout_summary["mean_daily_profit"],
                      "test_days": submission["days"], "dashboard": str(output / "index.html")}, ensure_ascii=True), flush=True)
    return summary
