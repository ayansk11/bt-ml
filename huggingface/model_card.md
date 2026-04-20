---
license: mit
language:
  - en
pipeline_tag: tabular-regression
library_name: lightgbm
tags:
  - gtfs
  - transit
  - etas
  - bloomington
  - hackathon
---

# bt-eta-correction-a1

LightGBM regressor that predicts a **residual correction** to Bloomington Transit's live GTFS-RT arrival delays, measured against inferred actual arrival times.

Produced at the IU Luddy Hacks hackathon (2026-04-18).

## Why a residual model?

BT's GTFS-RT feed publishes **one trip-level delay per trip**, applied identically to every remaining stop (~91 % of trip-snapshots in our audit). There is no `arrival.time` field and no per-stop refinement. We learned the gap between BT's predictions and ground truth, then ADD that correction to BT's prediction to produce an adjusted ETA.

## Intended use

- Live ETA display in a Bloomington Transit client app (see companion Android repo).
- Baseline research reference for other small/medium US transit agencies whose GTFS-RT publishes only trip-level delays.

## Out-of-scope / limitations

- **Distribution shift**: training data is weekday evening only (service_ids 109 + 49, Friday 20:00-21:00 EDT window). Saturday demo runs under service_ids 26/28. The feature set excludes `service_id` to encourage generalisation, but transfer across weekday/weekend is not validated.
- **Sample size**: only 37 unique trip-instances contributed labels. 12 of BT's 16 routes are represented; routes 12, 13, 14, 122927 are unseen.
- **Label noise**: 74 % of training rows use `midpoint` inference for the actual (±15 s noise floor). The remaining 26 % (`STOPPED_AT` observation) are high-confidence.
- **No holiday / severe weather handling.**

## Training data

Labels derived from live GTFS-RT snapshots of BT's `position_updates.pb` and `trip_updates.pb`, collected at 10 s cadence on 2026-04-18 between 00:35 and 01:22 UTC (≈46 min window after logger restarts).

- `ground_truth_arrivals.parquet` - 994 (trip, stop) labels; 112 high + 323 medium + 559 excluded (no signal in window).
- `bt_prediction_error.parquet` - 28,658 BT predictions scored against those labels; target used for training is `actual - bt_predicted` (signed seconds).

See the companion dataset card.

## Features (13)

All derived from timestamps or static GTFS - **no `service_id`, no calendar date, no feature that memorises weekday identity**.

| Feature | Source |
|---|---|
| `hour_of_day`, `minute_of_hour`, `day_of_week`, `is_weekend` | `snapshot_ts_utc` → `America/New_York` |
| `route_id` (categorical) | `trips.txt` via `trip_id` |
| `bt_trip_delay_seconds` | `trip_updates.pb` current stop_time_update.arrival.delay |
| `trip_progress_fraction` | `stop_sequence / total_stops_on_trip` |
| `stops_remaining` | `total_stops_on_trip − stop_sequence` |
| `prediction_horizon_seconds` | `actual_arrival_utc − snapshot_ts_utc` |
| `upstream_delay_trend_60s`, `has_upstream_trend` | Δ BT trip delay over prior 60 s |
| `route_length_km` | average shape polyline length per route |
| `average_stop_spacing_m` | `route_length_km * 1000 / avg_stops_per_trip` |

## Model

- **Architecture**: LightGBM regressor
- **Params**: `learning_rate=0.05, num_leaves=31, min_data_in_leaf=30, feature_fraction=0.9, bagging_fraction=0.9, bagging_freq=3, lambda_l2=1.0, num_boost_round=600 (final), early stop 50`
- **Target**: `target_correction_seconds = inferred_actual - bt_predicted` (signed seconds)
- **Validation**: 5-fold `GroupKFold` with `trip_id` as the group key (prevents within-trip leakage).

## Evaluation

Against BT's own published-delay passthrough at the 3-5 min prediction horizon (the most decision-relevant horizon for riders).

| Metric | BT passthrough | A1 (ours) | Δ |
|---|---:|---:|---:|
| MAE @ 3-5 min horizon (s) | 94.3 | **84.1** | −10.2 (−10.8 %) |
| MAE overall (s) | 116.0 | **91.7** | −24.3 (−20.9 %) |
| Bias @ 3-5 min (s) | +21.3 avg across buckets | +0.4 | - |
| RMSE @ 3-5 min (s) | - | 120.6 | - |

Per-route (OOF MAE vs passthrough):

| Route | n | Passthrough | A1 | Δ |
|---|---:|---:|---:|---:|
| 1 | 2036 | 109.4 | 67.4 | −42.1 |
| 2S | 610 | 75.7 | 87.6 | +11.9 |
| 2W | 834 | 138.7 | 113.9 | −24.7 |
| 3E | 5091 | 114.7 | 92.2 | −22.6 |
| 3W | 4716 | 115.8 | 83.3 | −32.5 |
| 4S | 2085 | 82.5 | 83.4 | +0.9 |
| 4W | 2885 | 86.5 | 87.2 | +0.7 |
| 5 | 1828 | 42.9 | 38.5 | −4.4 |
| 6 | 2220 | 245.4 | 192.1 | −53.3 |
| 7 | 2733 | 169.1 | 128.9 | −40.2 |
| 9 | 3208 | 75.2 | 50.4 | −24.8 |
| 11 | 412 | 149.7 | 103.8 | −45.9 |

The biggest wins are on routes BT handles worst (6 / 7 / 1 / 11). A few routes (2S, 4S, 4W) regress slightly within the noise floor.

## Top features by gain

1. `trip_progress_fraction`
2. `route_id`
3. `bt_trip_delay_seconds`
4. `route_length_km`
5. `average_stop_spacing_m`

## Companion artifact - A2 per-route intercepts

`route_intercepts.json` holds a simple `median(actual − bt_predicted)` per route for 12 routes (≥30 samples each). The inference service applies the intercept instead of A1 when the route is unseen by A1, and applies the intercept on top of zero when A1 aborts (falls back to passthrough).

## How to use

```python
import joblib, pandas as pd
bundle = joblib.load("a1_delay_correction.joblib")
booster = bundle["booster"]
# build a single-row DataFrame with the 13 feature columns above
# Important: set route_id as pandas.Categorical with categories from bundle["category_maps"]
row = pd.DataFrame([{
  "hour_of_day": 17, "minute_of_hour": 32, "day_of_week": 4, "is_weekend": 0,
  "route_id": "6",
  "bt_trip_delay_seconds": 240.0,
  "trip_progress_fraction": 0.5, "stops_remaining": 12,
  "prediction_horizon_seconds": 240, "upstream_delay_trend_60s": 0, "has_upstream_trend": 0,
  "route_length_km": 14.3, "average_stop_spacing_m": 420.0,
}])
row["route_id"] = pd.Categorical(row["route_id"], categories=bundle["category_maps"]["route_id"])
correction_s = float(booster.predict(row[bundle["feature_cols"]])[0])
adjusted_eta_s = bt_scheduled_epoch_s + bt_trip_delay_s + correction_s
```

## Citation

If this model is useful to you:

```
@misc{btetacorrection2026,
  title  = {bt-eta-correction-a1: residual LightGBM for small-agency GTFS-RT ETAs},
  author = {Sk, Ayan and Dodia, Chirag and Patel, Omkar and <Naishal>},
  year   = 2026,
  url    = {https://huggingface.co/Ayansk11/bt-eta-correction-a1},
  note   = {IU Luddy Hacks submission}
}
```

## Contact

Repository: https://github.com/ChiragDodia36/Luddy_hackathon_Case3 (Android client) and local training repo `bt-ml`.
