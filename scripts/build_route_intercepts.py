"""A2 - per-route intercept correction.

For each route_id, compute median(target_correction_seconds) = median(actual - predicted).
Routes with fewer than MIN_SAMPLES get intercept = 0 to avoid noise.

Adjusted BT prediction = bt_predicted + intercept_for_route.

Writes models/route_intercepts.json.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODELS = ROOT / "models"
MIN_SAMPLES = 30


def main():
    df = pd.read_parquet(DATA / "training_rows.parquet")
    # target_correction_seconds = actual - bt_predicted
    grouped = df.groupby("route_id")["target_correction_seconds"]
    intercepts = {}
    sample_counts = {}
    raw_medians = {}
    raw_means = {}
    for route_id, series in grouped:
        n = int(len(series))
        sample_counts[str(route_id)] = n
        med = float(series.median())
        mean = float(series.mean())
        raw_medians[str(route_id)] = med
        raw_means[str(route_id)] = mean
        intercepts[str(route_id)] = med if n >= MIN_SAMPLES else 0.0

    out = {
        "computed_at_utc": datetime.now(timezone.utc).isoformat(),
        "method": "median of (actual - bt_predicted) per route",
        "min_samples": MIN_SAMPLES,
        "route_intercepts_seconds": intercepts,
        "computed_from_samples": sample_counts,
        "raw_medians_seconds": raw_medians,
        "raw_means_seconds": raw_means,
    }
    MODELS.mkdir(parents=True, exist_ok=True)
    (MODELS / "route_intercepts.json").write_text(json.dumps(out, indent=2))

    print(f"[a2] wrote {MODELS / 'route_intercepts.json'}")
    print(f"[a2] routes: {len(intercepts)}")
    print(f"[a2] per-route intercepts (signed seconds to add to BT's prediction):")
    for r in sorted(intercepts, key=lambda k: -abs(intercepts[k])):
        n = sample_counts[r]
        med = raw_medians[r]
        applied = intercepts[r]
        note = "" if n >= MIN_SAMPLES else " [SKIPPED: n<30]"
        print(f"   route {r:<4}  n={n:<5}  median_correction={med:+7.1f}s   applied={applied:+7.1f}s{note}")


if __name__ == "__main__":
    main()
