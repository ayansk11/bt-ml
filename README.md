# bt-ml — Bloomington Transit AI/ML Workspace

ML training + inference service for the IU Luddy Hacks Bloomington Transit submission.

## What's here

- **`data/`** — parquet labels and summaries copied from the data workspace (live logger stays separate).
- **`features/`** — feature engineering code that joins labels with live RT snapshots and static GTFS.
- **`models/`** — trained model artifacts (`a1_delay_correction.joblib`, `route_intercepts.json`, metadata JSONs).
- **`scripts/`** — one-off training / evaluation scripts.
- **`service/`** — FastAPI inference service (see `service/run.sh`).
- **`notebooks/`** — training reports and analysis.
- **`huggingface/`** — model-card + dataset-card + manual push script.

## Methodology — A1 per-stop delay correction

We learn the **residual** between BT's published trip-level delay and the inferred actual arrival: `y = actual_arrival - bt_predicted_arrival` in seconds. Modelling the residual (not arrival time directly) is data-efficient and keeps BT's scheduling baked in.

**Features** (designed to generalise from weekday training data to Saturday demo):

- Temporal (derived from `snapshot_ts_utc`, not `service_id`): `hour_of_day`, `minute_of_hour`, `day_of_week`, `is_weekend`
- Route: `route_id` (categorical)
- Trip state: `bt_trip_delay_seconds`, `trip_progress_fraction` (`stop_sequence / total_stops_on_trip`), `stops_remaining`
- Horizon: `prediction_horizon_seconds`
- Trend: `upstream_delay_trend_60s` (Δ in BT trip delay over the prior 60 s)
- Static route geometry: `route_length_km`, `average_stop_spacing_m`

**Explicitly forbidden**: `service_id`, calendar date, anything that memorises weekday identity.

**Validation**: 5-fold GroupKFold with `trip_id` as the group key (prevents within-trip leakage). Report MAE, signed bias, and per-route breakdown. Compare against the BT baseline (94.3 s MAE at 3–5 min horizon, measured on 3,862 labelled predictions).

**Model**: LightGBM regressor, 8–12 features, mild regularisation. Trains in <5 min on laptop CPU — no Colab/GPU needed.

**Abort criterion**: if 5-fold CV MAE ≥ 94.3 s, we ship the joblib anyway but flip the service to `model_source="baseline_passthrough"` and rely on A2 route intercepts alone.

## Methodology — A2 per-route intercept

Per-route median signed error from `data/bt_prediction_error.parquet`. Routes with <30 samples get intercept `0` to avoid overfitting to noise. Route 6 is the primary target: observed bias +222 s, MAE 245 s.

Applied *additively* on top of A1, or as the sole correction when A1 aborts.

## Running the service

```bash
cd service
./run.sh                 # starts uvicorn on :8000
# ...
curl http://localhost:8000/healthz
```

See `service/app/main.py` for the endpoint surface. Contract shapes live in `SERVICE_CONTRACT.md` when generated.

## Training loop

```bash
.venv/bin/python features/build_dataset.py   # produces data/training_rows.parquet
.venv/bin/python scripts/train_a1.py         # produces models/a1_delay_correction.joblib + metadata
.venv/bin/python scripts/build_route_intercepts.py  # produces models/route_intercepts.json
```

## Git

Local-only repo. **No remote. Never push.** Branch: `main` (local).

## Hackathon context

Submission: 2026-04-18 16:00 EDT. This workspace is one of two — the other (`Bloomington Transit App/`) runs the live GTFS logger and houses `DATA_REPORT.md` / `BASELINE_REPORT.md`. The Android client lives at `Luddy_hackathon_Case3/`.
