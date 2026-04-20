---
license: mit
language:
  - en
task_categories:
  - tabular-regression
tags:
  - gtfs
  - transit
  - etas
  - bloomington
  - hackathon
size_categories:
  - 10K<n<100K
---

# bt-gtfs-rt-labels-2026-04-18

Ground-truth arrival labels inferred from Bloomington Transit's public GTFS-RT feed, for evaluating delay prediction quality at a small agency that publishes only **trip-level** delays.

## Rows

Two parquet files:

1. **`ground_truth_arrivals.parquet`** - 11,283 rows. One row per `(trip_id, stop_sequence)`. Columns:
   - `trip_id`, `route_id`, `stop_id`, `stop_sequence`, `vehicle_id`, `service_id`, `service_date_local`
   - `scheduled_arrival_utc` (ISO UTC)
   - `inferred_actual_arrival_utc` (ISO UTC, null if `confidence == low`)
   - `inference_method` ∈ {`stopped_at`, `midpoint`, `excluded`}
   - `confidence` ∈ {`high`, `medium`, `low`}
   - `excluded_reason` (empty for high/medium)
   - `first_pos_sample_utc`, `last_pos_sample_utc`

2. **`bt_prediction_error.parquet`** - 693,648 rows. One row per prediction (per snapshot, per labelled `(trip_id, stop_sequence)`). Columns:
   - `trip_id`, `route_id`, `stop_id`, `stop_sequence`, `service_id`, `ground_truth_confidence`
   - `snapshot_ts_utc`, `snapshot_epoch`
   - `bt_delay_seconds` (BT's published trip-level delay at the snapshot)
   - `bt_predicted_arrival_utc`, `inferred_actual_arrival_utc`
   - `error_seconds = bt_predicted − inferred_actual` (signed; positive = BT late)
   - `horizon_seconds = inferred_actual − snapshot_ts`
   - `horizon_bucket` ∈ {`0-60`, `60-180`, `180-600`, `600-1800`, `1800+`}

## Data collection

Logger polls `position_updates.pb` + `trip_updates.pb` + `alerts.pb` every 10 s. Raw `.pb` snapshots are **not** in this dataset (refreshable from S3) but the derived labels are.

Window: 2026-04-17 through 2026-04-19 (~50 h, spanning Friday evening, Saturday full day, and Sunday).

## Inference method for actuals

Per `(trip_id, vehicle_id)`:

1. Exclude the trip if consecutive `current_stop_sequence` values go backwards, OR gap > 3 min between samples.
2. For each scheduled stop on that trip:
   - **HIGH**: first sample with `current_stop_sequence == N` AND `current_status == STOPPED_AT` -> that `vehicle.timestamp` is the actual arrival.
   - **MEDIUM**: midpoint between last sample at `N−1` and first sample at `N+1`.
   - **LOW / excluded**: neither condition satisfied.
3. Scheduled arrival from static `stop_times.txt` (HH:MM:SS, HH≥24 allowed for overnight wrap), combined with `service_date = local_date(first_pos_sample)`, localised in `America/New_York` and converted to UTC.

Label quality: 18.3 % high, 53.2 % medium, 28.5 % low (excluded).

## Known limitations

- **Temporal coverage**: ~50 h across 2026-04-17 to 2026-04-19 (Friday evening + Saturday + Sunday). No Mon-Thu coverage; no holiday / severe-weather windows.
- **Route coverage**: 12 of BT's 16 routes have labels; routes 12 / 13 / 14 / 122927 are unobserved.
- **460 unique trips** contributed labels across 487 `(trip, vehicle)` instances.
- **Timezone note**: BT's `agency.txt` declares `America/New_York` (not the canonical `America/Indiana/Indianapolis`). Both have the same UTC offset in 2026 but use with care.

## Licence

MIT. The underlying GTFS-RT feed is publicly available from ETA Transit Systems at `s3.amazonaws.com/etatransit.gtfs/bloomingtontransit.etaspot.net/`. Their terms of service govern redistribution of raw bytes; the labels derived here are a transformation and are released under MIT.

## Citation

```
@misc{btgtfslabels2026,
  title  = {bt-gtfs-rt-labels-2026-04-18: inferred arrival-time labels for Bloomington Transit},
  author = {Sk, Ayan and Dodia, Chirag and Patel, Omkar and <Naishal>},
  year   = 2026,
  url    = {https://huggingface.co/datasets/Ayansk11/bt-gtfs-rt-labels-2026-04-18}
}
```
