"""Train the A1 per-stop delay correction model.

Target: target_correction_seconds = actual - bt_predicted  (signed seconds)

Validation: 5-fold GroupKFold on trip_id (no within-trip leakage).
Abort if 5-fold CV MAE at 3-5 min horizon >= 94.3s (BT baseline), per the spec —
we still SAVE the model but mark it as baseline_passthrough in metadata so the
service falls back to passthrough + A2 route intercepts only.

Writes:
  models/a1_delay_correction.joblib      (one model trained on ALL data, for inference)
  models/a1_metadata.json                (CV metrics, feature importance, abort flag)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"

BT_HEADLINE_MAE = 94.3  # BT's MAE at 3-5 min horizon, from BASELINE_REPORT
ABORT_THRESHOLD = 94.3  # from spec

FEATURE_COLS = [
    "hour_of_day", "minute_of_hour", "day_of_week", "is_weekend",
    "route_id",
    "bt_trip_delay_seconds",
    "trip_progress_fraction", "stops_remaining",
    "prediction_horizon_seconds",
    "upstream_delay_trend_60s", "has_upstream_trend",
    "route_length_km", "average_stop_spacing_m",
]
CATEGORICAL_COLS = ["route_id"]
TARGET = "target_correction_seconds"


def metrics_row(y_true, y_pred) -> dict:
    err = y_pred - y_true  # signed prediction error
    ae = np.abs(err)
    return {
        "n": int(len(y_true)),
        "mae": float(ae.mean()),
        "median_ae": float(np.median(ae)),
        "rmse": float(math.sqrt(float((err ** 2).mean()))),
        "bias": float(err.mean()),
        "p10_err": float(np.quantile(err, 0.10)),
        "p90_err": float(np.quantile(err, 0.90)),
    }


def passthrough_mae(y_true) -> float:
    """Baseline: predict 0 correction (i.e. trust BT). MAE = mean(|target|)."""
    return float(np.abs(y_true).mean())


def main():
    df = pd.read_parquet(DATA / "training_rows.parquet")
    print(f"[train_a1] loaded {len(df):,} rows, {df['trip_id'].nunique()} unique trips, "
          f"{df['route_id'].nunique()} routes")

    # Encode route_id as category
    for c in CATEGORICAL_COLS:
        df[c] = df[c].astype("category")

    X = df[FEATURE_COLS]
    y = df[TARGET].astype(float).values
    groups = df["trip_id"].astype(str).values
    horizons = df["prediction_horizon_seconds"].astype(float).values
    routes = df["route_id"].astype(str).values
    confs = df["ground_truth_confidence"].astype(str).values

    # 5-fold GroupKFold
    gkf = GroupKFold(n_splits=5)
    fold_metrics = []
    fold_horizon_3_5 = []
    oof_pred = np.zeros_like(y, dtype=float)
    fold_idx = np.zeros_like(y, dtype=int)
    fold_feat_imp = []

    params = dict(
        objective="regression",
        metric="mae",
        learning_rate=0.05,
        num_leaves=31,
        min_data_in_leaf=30,
        feature_fraction=0.9,
        bagging_fraction=0.9,
        bagging_freq=3,
        lambda_l2=1.0,
        verbose=-1,
    )

    for fold, (tr, va) in enumerate(gkf.split(X, y, groups=groups)):
        dtr = lgb.Dataset(X.iloc[tr], label=y[tr], categorical_feature=CATEGORICAL_COLS)
        dva = lgb.Dataset(X.iloc[va], label=y[va], categorical_feature=CATEGORICAL_COLS, reference=dtr)
        booster = lgb.train(
            params, dtr, num_boost_round=2000, valid_sets=[dva],
            callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(0)],
        )
        pred = booster.predict(X.iloc[va], num_iteration=booster.best_iteration)
        oof_pred[va] = pred
        fold_idx[va] = fold
        fold_metrics.append({
            "fold": fold,
            "n_train_trips": int(pd.unique(groups[tr]).size),
            "n_val_trips": int(pd.unique(groups[va]).size),
            **metrics_row(y[va], pred),
            "passthrough_mae": passthrough_mae(y[va]),
        })
        # horizon 180-300 slice
        mask_h = (horizons[va] >= 180) & (horizons[va] <= 300)
        if mask_h.any():
            fold_horizon_3_5.append({
                "fold": fold,
                **metrics_row(y[va][mask_h], pred[mask_h]),
                "passthrough_mae": passthrough_mae(y[va][mask_h]),
            })
        fold_feat_imp.append(pd.Series(
            booster.feature_importance(importance_type="gain"),
            index=booster.feature_name(),
            name=f"fold_{fold}",
        ))

    # OOF overall / horizon slice
    overall = {
        **metrics_row(y, oof_pred),
        "passthrough_mae": passthrough_mae(y),
    }
    mask_h = (horizons >= 180) & (horizons <= 300)
    horizon_3_5 = {
        **metrics_row(y[mask_h], oof_pred[mask_h]),
        "passthrough_mae": passthrough_mae(y[mask_h]),
    } if mask_h.any() else None

    # Per-route OOF
    per_route = {}
    for r in pd.unique(routes):
        m = routes == r
        if m.sum() < 30:
            per_route[r] = {"n": int(m.sum()), "skipped_lt_30": True}
            continue
        per_route[r] = {
            **metrics_row(y[m], oof_pred[m]),
            "passthrough_mae": passthrough_mae(y[m]),
        }

    # Per-horizon bucket OOF
    horizon_buckets = [
        ("0-60", 0, 60),
        ("60-180", 60, 180),
        ("180-600", 180, 600),
        ("600-1800", 600, 1800),
        ("1800+", 1800, float("inf")),
    ]
    per_horizon = {}
    for name, lo, hi in horizon_buckets:
        m = (horizons >= lo) & (horizons < hi)
        if m.any():
            per_horizon[name] = {
                **metrics_row(y[m], oof_pred[m]),
                "passthrough_mae": passthrough_mae(y[m]),
            }

    # Feature importance (averaged across folds)
    feat_imp_df = pd.concat(fold_feat_imp, axis=1).fillna(0).mean(axis=1).sort_values(ascending=False)

    # Abort decision
    headline_cv_mae = horizon_3_5["mae"] if horizon_3_5 else overall["mae"]
    abort = headline_cv_mae >= ABORT_THRESHOLD
    model_source = "baseline_passthrough" if abort else "a1_lightgbm"

    # Train final model on ALL data (for inference)
    dall = lgb.Dataset(X, label=y, categorical_feature=CATEGORICAL_COLS)
    final_booster = lgb.train(params, dall, num_boost_round=600)
    # Save
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "booster": final_booster,
        "feature_cols": FEATURE_COLS,
        "categorical_cols": CATEGORICAL_COLS,
        "category_maps": {c: list(df[c].cat.categories) for c in CATEGORICAL_COLS},
    }, MODELS / "a1_delay_correction.joblib")

    # Metadata
    metadata = {
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_source": model_source,
        "aborted": abort,
        "abort_threshold_s": ABORT_THRESHOLD,
        "bt_headline_mae_s": BT_HEADLINE_MAE,
        "headline_cv_mae_s": headline_cv_mae,
        "improvement_vs_bt_headline_s": BT_HEADLINE_MAE - headline_cv_mae,
        "improvement_pct": (BT_HEADLINE_MAE - headline_cv_mae) / BT_HEADLINE_MAE * 100 if BT_HEADLINE_MAE else None,
        "feature_cols": FEATURE_COLS,
        "categorical_cols": CATEGORICAL_COLS,
        "lgbm_params": params,
        "label_counts_by_confidence": {
            k: int((confs == k).sum()) for k in ["high", "medium", "low"]
        },
        "n_rows": int(len(df)),
        "n_unique_trips": int(df["trip_id"].nunique()),
        "n_routes": int(df["route_id"].nunique()),
        "cv": {
            "per_fold": fold_metrics,
            "per_fold_3_5_min": fold_horizon_3_5,
            "oof_overall": overall,
            "oof_3_5_min": horizon_3_5,
            "oof_per_route": per_route,
            "oof_per_horizon": per_horizon,
        },
        "feature_importance_gain": {k: float(v) for k, v in feat_imp_df.items()},
    }
    (MODELS / "a1_metadata.json").write_text(json.dumps(metadata, indent=2, default=str))

    # Stdout digest
    print(f"\n[train_a1] passthrough (predict 0) overall MAE = {overall['passthrough_mae']:.1f}s   "
          f"3-5 min horizon = {horizon_3_5['passthrough_mae'] if horizon_3_5 else float('nan'):.1f}s")
    print(f"[train_a1] A1 OOF overall MAE             = {overall['mae']:.1f}s   "
          f"bias = {overall['bias']:+.1f}s   RMSE = {overall['rmse']:.1f}s")
    if horizon_3_5:
        print(f"[train_a1] A1 OOF 3-5 min horizon MAE      = {horizon_3_5['mae']:.1f}s   "
              f"bias = {horizon_3_5['bias']:+.1f}s   RMSE = {horizon_3_5['rmse']:.1f}s")
    print(f"[train_a1] BT headline (94.3s)  →  A1 headline ({headline_cv_mae:.1f}s)  "
          f"= {metadata['improvement_vs_bt_headline_s']:+.1f}s  "
          f"({metadata['improvement_pct']:+.1f}%)")
    print(f"[train_a1] ABORT FLAG = {abort}    model_source = {model_source}")
    print(f"\n[train_a1] top-5 features by gain:")
    for k, v in feat_imp_df.head(5).items():
        print(f"   {k:<30}  {v:>10.1f}")
    print(f"\n[train_a1] per-route MAE vs passthrough:")
    for r, m in per_route.items():
        if m.get("skipped_lt_30"):
            print(f"   route {r:<4} n={m['n']:<4}  [skipped, n<30]")
        else:
            imp = m["passthrough_mae"] - m["mae"]
            print(f"   route {r:<4} n={m['n']:<5} passthrough MAE={m['passthrough_mae']:.1f}s  "
                  f"A1 MAE={m['mae']:.1f}s  improvement={imp:+.1f}s  bias={m['bias']:+.1f}s")
    print(f"\n[train_a1] wrote {MODELS / 'a1_delay_correction.joblib'} + metadata JSON")


if __name__ == "__main__":
    main()
