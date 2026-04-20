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

- **Distribution shift**: training data spans 2026-04-17 Friday evening through 2026-04-19 Sunday night (~50 h, mixed weekday / weekend). The feature set excludes `service_id` and calendar date to encourage generalisation across days; Mon-Thu coverage is absent.
- **Sample size**: 460 unique trips across 12 of BT's 16 routes; routes 12, 13, 14, 122927 are unseen.
- **Label noise**: 74 % of usable training labels come from `midpoint` inference (±15 s noise floor); the remaining 26 % are high-confidence `STOPPED_AT` observations.
- **No holiday / severe weather handling.**

## Training data

Labels derived from live GTFS-RT snapshots of BT's `position_updates.pb` and `trip_updates.pb`, collected at 10 s cadence from 2026-04-17 through 2026-04-19 (~50 h window covering Friday evening, Saturday full day, and Sunday).

- `ground_truth_arrivals.parquet` - 11,283 (trip, stop) labels; 2,063 high + 6,003 medium + 3,217 excluded (no signal in window).
- `bt_prediction_error.parquet` - 693,648 BT predictions scored against those labels; target used for training is `actual - bt_predicted` (signed seconds).

See the companion dataset card.

## Features (13)

All derived from timestamps or static GTFS - **no `service_id`, no calendar date, no feature that memorises weekday identity**.

| Feature | Source |
|---|---|
| `hour_of_day`, `minute_of_hour`, `day_of_week`, `is_weekend` | `snapshot_ts_utc` -> `America/New_York` |
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

Against BT's own published-delay passthrough at the 3-5 min prediction horizon (the most decision-relevant horizon for riders), 5-fold GroupKFold OOF on `trip_id`.

| Metric | BT passthrough | A1 (ours) | Δ |
|---|---:|---:|---:|
| MAE @ 3-5 min horizon (s) | 82.3 | **50.2** | -32.1 (-39.0 %) |
| MAE overall (s) | 136.7 | **72.5** | -64.2 (-47.0 %) |
| Bias @ 3-5 min (s) | - | +0.1 | - |
| RMSE @ 3-5 min (s) | - | 69.9 | - |

Per-route (OOF MAE vs passthrough):

| Route | n | Passthrough | A1 | Δ |
|---|---:|---:|---:|---:|
| 3W | 108,920 | 134.0 | 82.3 | -51.7 |
| 3E | 104,775 |  92.9 | 61.9 | -31.0 |
| 7  |  91,211 | 101.1 | 62.0 | -39.1 |
| 9  |  88,530 | 107.0 | 53.1 | -53.9 |
| 6  |  82,852 | 338.5 | 162.3 | -176.2 |
| 4W |  50,200 | 110.3 | 52.2 | -58.1 |
| 5  |  49,137 | 100.8 | 44.3 | -56.5 |
| 1  |  40,477 | 120.1 | 58.0 | -62.0 |
| 4S |  34,372 | 112.4 | 46.8 | -65.5 |
| 2W |  21,556 | 103.8 | 52.6 | -51.1 |
| 2S |  13,387 |  99.9 | 53.3 | -46.6 |
| 11 |   8,231 | 116.2 | 50.9 | -65.3 |

A1 improves every route. Route 6 has the largest absolute gain (-176 s MAE) and is the hardest residual; routes 1, 4S, 11 show the largest relative improvements.

## Top features by gain

1. `prediction_horizon_seconds`
2. `bt_trip_delay_seconds`
3. `route_id`
4. `trip_progress_fraction`
5. `hour_of_day`

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

Repositories: https://github.com/ayansk11/bt-ml (this ML service) and https://github.com/ChiragDodia36/BT_transit_App (Android client).
