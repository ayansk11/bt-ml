# bt-ml

ML inference service for **BT Transit** - a Bloomington Transit Android replacement built at the IU Luddy Hackathon (3rd place, Bombay Boys).

**Result: 64.8 s MAE at the 3-5 min prediction horizon vs. the official BT app's 94.3 s - a 31% improvement**, measured on 3,862 labelled predictions with 5-fold GroupKFold CV grouped on `trip_id`.

The full Android app lives at [`ChiragDodia36/BT_transit_App`](https://github.com/ChiragDodia36/BT_transit_App). This repo is the FastAPI + LightGBM service the app talks to.

---

## What's here

- **`service/`** - FastAPI inference service (endpoints listed below).
- **`features/`** - feature engineering that joins labels with live GTFS-Realtime snapshots and static GTFS.
- **`scripts/`** - training / evaluation / intercept-build scripts.
- **`models/`** - trained artifacts (`a1_delay_correction.joblib`, `route_intercepts.json`, metadata JSON).
- **`data/`** - parquet labels and summaries derived from live GTFS snapshots.
- **`huggingface/`** - model card + dataset card + manual push script.
- **`notebooks/`** - training reports and analysis.

---

## Service endpoints

FastAPI service in `service/app/main.py`. Dockerised, deployed on Railway (see [`DEPLOY.md`](./DEPLOY.md)).

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Health + model-source indicator |
| `GET /predictions?stop_id=…` | Per-stop arrival predictions (Scheduled / BT / Ours with confidence tier) |
| `GET /trip_eta?trip_id=…` | Adjusted ETAs across the remaining stops of a trip |
| `GET /detections/bunching` | Buses of the same route within 200 m |
| `GET /stats` | Live BT vs. Ours MAE, fleet size, stale-vehicle count |
| `GET /nlq?q=…` | Natural-language query (regex-first, LLM fallback) |
| `GET /plan?origin_lat=…&dest_lat=…` | Google Directions transit routes enriched with A1+A2 boarding ETAs |

---

## Methodology - A1 per-stop delay correction

We learn the **residual** between BT's published trip-level delay and the inferred actual arrival: `y = actual_arrival - bt_predicted_arrival` in seconds. Modelling the residual (not arrival time directly) is data-efficient and keeps BT's scheduling baked in.

**Features** (designed to generalise across days of the week):

- Temporal (derived from `snapshot_ts_utc`, not `service_id`): `hour_of_day`, `minute_of_hour`, `day_of_week`, `is_weekend`
- Route: `route_id` (categorical)
- Trip state: `bt_trip_delay_seconds`, `trip_progress_fraction` (`stop_sequence / total_stops_on_trip`), `stops_remaining`
- Horizon: `prediction_horizon_seconds`
- Trend: `upstream_delay_trend_60s` (Δ in BT trip delay over the prior 60 s)
- Static route geometry: `route_length_km`, `average_stop_spacing_m`

**Explicitly forbidden**: `service_id`, calendar date, anything that memorises weekday identity.

**Validation**: 5-fold GroupKFold with `trip_id` as the group key (prevents within-trip leakage). Report MAE, signed bias, and per-route breakdown. Compare against the BT baseline (94.3 s MAE at 3-5 min horizon, measured on 3,862 labelled predictions).

**Model**: LightGBM regressor, 8-12 features, mild regularisation. Trains in <5 min on laptop CPU - no Colab / GPU needed.

**Abort criterion**: if 5-fold CV MAE ≥ 94.3 s, we ship the joblib anyway but flip the service to `model_source="baseline_passthrough"` and rely on A2 route intercepts alone.

---

## Methodology - A2 per-route intercept

Per-route median signed error from `data/bt_prediction_error.parquet`. Routes with <30 samples get intercept `0` to avoid overfitting to noise. Route 6 was the primary target: observed bias +222 s, MAE 245 s before correction.

Applied *additively* on top of A1, or as the sole correction when A1 aborts.

---

## Running the service

```bash
cd service
./run.sh                                  # starts uvicorn on :8000
curl http://localhost:8000/healthz
```

---

## Training loop

```bash
.venv/bin/python features/build_dataset.py           # → data/training_rows.parquet
.venv/bin/python scripts/train_a1.py                 # → models/a1_delay_correction.joblib + metadata
.venv/bin/python scripts/build_route_intercepts.py   # → models/route_intercepts.json
```

---

## Deploy

See [`DEPLOY.md`](./DEPLOY.md) for Railway setup, env vars, verification curls, and key-rotation notes.
