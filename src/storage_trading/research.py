"""Public reproduction of the frozen Phase 2 specification, not an AutoML search.

Only supplied forecasts enter the 19-column feature matrix. This module uses
original point labels, including incomplete dates, and scores trading only on
complete dates. It never changes an existing experiment directory.
"""

import hashlib
import importlib.metadata
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .core import optimize_day, settle
from .pipeline import FEATURES, TABLES, locate_data, read_table, save_json

TIME = ["hour", "minute", "dayofweek", "month", "slot_id", "slot_sin", "slot_cos",
        "weekday_sin", "weekday_cos", "month_sin", "month_cos"]
COLUMNS = FEATURES + TIME + ["renewable_ratio_candidate"]


def frozen_features(frame):
    """Match the original Phase 2 column order and numeric operations exactly."""
    t = frame["times"]
    if t.dt.tz is not None or t.isna().any() or t.duplicated().any():
        raise ValueError("Expected unique naive Beijing timestamps")
    if ((t.dt.minute % 15 != 0) | (t.dt.second != 0) | (t.dt.microsecond != 0)).any():
        raise ValueError("Expected 15-minute grid")
    x = frame[FEATURES].copy()
    if not np.isfinite(x.to_numpy(dtype=float)).all():
        raise ValueError("Forecasts must be finite")
    x["hour"], x["minute"] = t.dt.hour, t.dt.minute
    x["dayofweek"], x["month"] = t.dt.dayofweek, t.dt.month
    x["slot_id"] = x.hour * 4 + x.minute // 15
    for name, values, period in [("slot", x.slot_id, 96),
                                 ("weekday", x.dayofweek, 7), ("month", x.month - 1, 12)]:
        x[name + "_sin"] = np.sin(2 * np.pi * values / period)
        x[name + "_cos"] = np.cos(2 * np.pi * values / period)
    load = x[FEATURES[0]]
    x["renewable_ratio_candidate"] = x[FEATURES[1]] / load.where(load.abs() > 1e-12)
    return x[COLUMNS].astype(float)


def chronological_masks(times, start, inner_days=14):
    outer = times < pd.Timestamp(start)
    if not outer.any():
        raise ValueError("No historical training data")
    cut = times[outer].max().normalize() - pd.Timedelta(days=inner_days - 1)
    train, tune = outer & (times < cut), outer & (times >= cut)
    if train.sum() < 96 * 7 or tune.sum() < 96:
        raise ValueError("Insufficient historical data for inner validation")
    return outer, train, tune


def fit_frozen(frame, future, destination, cfg):
    import lightgbm as lgb
    from catboost import CatBoostRegressor
    import joblib
    from sklearn.impute import SimpleImputer

    start = future.times.min()
    outer, train, tune = chronological_masks(frame.times, start, cfg["inner_validation_days"])
    x, xf = frozen_features(frame), frozen_features(future)
    y = frame.A
    destination.mkdir(parents=True, exist_ok=False)
    params = dict(cfg["lightgbm"], num_threads=cfg["num_threads"])
    history = {}
    trial = lgb.train(params, lgb.Dataset(x.loc[train], label=y.loc[train]),
                      num_boost_round=cfg["max_rounds"],
                      valid_sets=[lgb.Dataset(x.loc[tune], label=y.loc[tune])],
                      callbacks=[lgb.early_stopping(cfg["early_stopping_rounds"], verbose=False),
                                 lgb.record_evaluation(history)])
    rounds = trial.best_iteration or cfg["max_rounds"]
    model = lgb.train(params, lgb.Dataset(x.loc[outer], label=y.loc[outer]), num_boost_round=rounds)
    lp = model.predict(xf, num_threads=cfg["num_threads"])
    model.save_model(str(destination / "lightgbm.txt"))
    save_json(destination / "early_stopping_history.json", history)

    imputer = SimpleImputer(strategy="median", add_indicator=True)
    xa = imputer.fit_transform(x.loc[train])
    xb = imputer.transform(x.loc[tune])
    cp = dict(cfg["catboost"], thread_count=cfg["num_threads"])
    cat_trial = CatBoostRegressor(**cp)
    cat_trial.fit(xa, y.loc[train].to_numpy(), eval_set=(xb, y.loc[tune].to_numpy()),
                  early_stopping_rounds=cfg["early_stopping_rounds"])
    cat_rounds = max(1, int(cat_trial.get_best_iteration() + 1))
    cp["iterations"] = cat_rounds
    imputer = SimpleImputer(strategy="median", add_indicator=True)
    xx = imputer.fit_transform(x.loc[outer])
    cat = CatBoostRegressor(**cp).fit(xx, y.loc[outer].to_numpy())
    pred = .5 * lp + .5 * cat.predict(imputer.transform(xf))
    cat.save_model(str(destination / "catboost.cbm"))
    joblib.dump(imputer, destination / "imputer.joblib")
    save_json(destination / "fit.json", {
        "columns": COLUMNS, "weights": [.5, .5], "lightgbm": params, "catboost": cp,
        "lightgbm_rounds": int(rounds), "catboost_rounds": cat_rounds,
        "inner_train_end": str(frame.loc[train, "times"].max()),
        "inner_validation_start": str(frame.loc[tune, "times"].min()),
        "outer_train_end": str(frame.loc[outer, "times"].max()),
        "evaluation_start": str(start), "outer_used_for_early_stopping": False})
    return pred


def evaluate(frame, prediction, training_labels):
    table = frame[["times", "A"]].copy()
    table["pred_price"] = prediction
    err = table.pred_price.to_numpy() - table.A.to_numpy()
    denom = float(np.sum((table.A - table.A.mean()) ** 2))
    high = float(np.quantile(training_labels, .95))
    truth, positive = table.A.to_numpy() >= high, prediction >= high
    tp, fp, fn = int((truth & positive).sum()), int((~truth & positive).sum()), int((truth & ~positive).sum())
    daily, actions = [], []
    for date, day in table.groupby(table.times.dt.date, sort=True):
        if len(day) != 96:
            continue
        plan = optimize_day(day.pred_price)
        actual, oracle = settle(day.A, plan.power), optimize_day(day.A).predicted_profit
        daily.append({"date": str(date), "profit": actual, "oracle_profit": oracle,
                      "regret": oracle - actual, "charge_start": plan.charge_start,
                      "discharge_start": plan.discharge_start})
        actions.extend({"times": str(t), "power": p} for t, p in zip(day.times, plan.power))
    days = pd.DataFrame(daily)
    if days.empty:
        raise ValueError("No complete dates for trading evaluation")
    metrics = {"rows": len(frame), "complete_days": len(days),
               "r2": 1 - float(np.sum(err ** 2)) / denom if denom > 0 else None,
               "mae": float(abs(err).mean()), "rmse": float(np.sqrt((err ** 2).mean())),
               "mean_daily_profit": float(days.profit.mean()),
               "oracle": float(days.oracle_profit.mean()),
               "capture": float(days.profit.sum() / days.oracle_profit.sum()) if days.oracle_profit.sum() > 0 else None,
               "regret": float(days.regret.mean()), "negative_days": int(days.profit.lt(0).sum()),
               "high_threshold_from_training": high, "high_support": int(truth.sum()),
               "high_precision": tp / (tp + fp) if tp + fp else None,
               "high_recall": tp / (tp + fn) if tp + fn else None,
               "high_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}
    return metrics, days, pd.DataFrame(actions)


def reproduce(folder: Path, output: Path):
    if output.exists():
        raise FileExistsError("Choose a new output directory; existing runs are protected")
    cfg_path = Path(__file__).resolve().parents[2] / "configs/phase2_frozen.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    data = locate_data(folder)
    boundary = read_table(data / TABLES["features"], FEATURES)
    labels = read_table(data / TABLES["labels"], ["A"])
    frame = boundary[["times"] + FEATURES].merge(labels[["times", "A"]], on="times", validate="one_to_one")
    frame = frame.sort_values("times").reset_index(drop=True)
    output.mkdir(parents=True, exist_ok=False)
    save_json(output / "config.json", cfg)
    save_json(output / "provenance.json", {
        "inputs": {Path(name).name: hashlib.sha256((data / name).read_bytes()).hexdigest()
                   for name in (TABLES["features"], TABLES["labels"])},
        "packages": {p: importlib.metadata.version(p) for p in
                     ["numpy", "pandas", "lightgbm", "catboost", "scikit-learn", "joblib"]},
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "Internal development estimate; no official hidden-test scores"})
    records, predictions, profits = [], [], []
    for fold in cfg["folds"]:
        start, end = pd.Timestamp(fold["start"]), pd.Timestamp(fold["end"]) + pd.Timedelta(days=1)
        valid = frame[frame.times.ge(start) & frame.times.lt(end)].copy()
        if valid.empty:
            raise ValueError("Missing configured validation month")
        dest = output / fold["name"]
        pred = fit_frozen(frame, valid, dest, cfg)
        metrics, daily, actions = evaluate(valid, pred, frame.loc[frame.times.lt(start), "A"].to_numpy())
        metrics["fold"] = fold["name"]
        save_json(dest / "metrics.json", metrics)
        points = valid[["times", "A"]].copy()
        points["pred_price"] = pred
        points.to_csv(dest / "predictions.csv", index=False)
        daily.to_csv(dest / "daily.csv", index=False)
        actions.to_csv(dest / "actions.csv", index=False)
        predictions.append(points)
        profits.append(daily)
        records.append(metrics)
        print(json.dumps(metrics, ensure_ascii=False), flush=True)
    pooled, days = pd.concat(predictions, ignore_index=True), pd.concat(profits, ignore_index=True)
    error = pooled.pred_price.to_numpy() - pooled.A.to_numpy()
    summary = {"r2": 1 - float(np.sum(error ** 2)) / float(np.sum((pooled.A - pooled.A.mean()) ** 2)),
               "mae": float(abs(error).mean()), "rmse": float(np.sqrt((error ** 2).mean())),
               "mean_daily_profit": float(days.profit.mean()), "oracle": float(days.oracle_profit.mean()),
               "capture": float(days.profit.sum() / days.oracle_profit.sum()),
               "regret": float(days.regret.mean()), "rows": len(pooled), "days": len(days)}
    save_json(output / "summary.json", summary)
    save_json(output / "fold_metrics.json", records)
    print("POOLED " + json.dumps(summary, ensure_ascii=False), flush=True)
    return summary
