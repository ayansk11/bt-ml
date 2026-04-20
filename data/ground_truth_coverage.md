# Ground-Truth Coverage Report

_Generated 2026-04-20T02:29:28.166529+00:00_


## Window

- Positions snapshots scanned: 13530
- First pos_ts observed: 2026-04-18T00:34:10+00:00
- Last pos_ts observed:  2026-04-20T02:28:54+00:00
- Distinct `(trip_id, vehicle_id)` instances: 487
- Trip-level exclusions: 17 ({'gap_over_3min': 17})

## Label counts by confidence

| Confidence | Method            | Count | % of total |
|------------|-------------------|------:|-----------:|
| **high**   | `stopped_at`      |  2063 | 18.3% |
| **medium** | `midpoint`        |  6003 | 53.2% |
| **low**    | `excluded`        |  3217 | 28.5% |
| **TOTAL**  |                   | 11283 | 100% |

### :warning: HIGH-CONFIDENCE RATE IS BELOW 50%

- **Only 18.3% of `(trip, stop)` pairs received a HIGH-confidence label.**
- 71.5% are USABLE (high + medium). 28.5% are excluded.
- Primary reason for exclusion: `no_signal` — the vehicle had not yet reached that stop within the observation window, so no samples exist at that stop_sequence or at the neighbouring N-1 / N+1.
- Mechanically, HIGH confidence requires catching the vehicle in the `STOPPED_AT` state at that stop. With a 30 s per-vehicle cadence and typical dwell times of 10–30 s, we miss many stops purely due to sampling.
- Keep the logger running — each additional hour of data materially increases HIGH-confidence coverage of any stops that ARE visited in that time.

## Distribution of `(inferred_actual - scheduled)` delay

Sanity-check: for ground truth to be plausible, this should be roughly centred near 0–60 s (a typical slight lateness) with a long positive tail, not bimodal or centred far from zero.


| Subset | n | mean | median | p10 | p90 | p99 | min | max |
|--------|---:|-----:|-------:|----:|----:|----:|----:|----:|
| **overall (high+medium)** | 8066 | 112.1s | 80.5s | -90.8s | 319.0s | 1121.0s | -1199.0s | 2041.0s |
| `high` only | 2063 | 93.3s | 60.0s | -95.0s | 293.0s | 1168.1s | -1199.0s | 2014.0s |
| `medium` only | 6003 | 118.5s | 85.5s | -87.9s | 328.5s | 1106.5s | -657.0s | 2041.0s |

## Per-route label counts

| route_id | high | medium | low | total |
|----------|-----:|-------:|----:|------:|
| `1` | 129 | 367 | 0 | 496 |
| `11` | 55 | 140 | 0 | 195 |
| `2S` | 91 | 256 | 0 | 347 |
| `2W` | 112 | 346 | 0 | 458 |
| `3E` | 302 | 1025 | 0 | 1327 |
| `3W` | 284 | 812 | 0 | 1096 |
| `4S` | 122 | 360 | 0 | 482 |
| `4W` | 148 | 349 | 0 | 497 |
| `5` | 126 | 351 | 0 | 477 |
| `6` | 173 | 520 | 0 | 693 |
| `7` | 280 | 786 | 0 | 1066 |
| `9` | 241 | 691 | 0 | 932 |

## Stop-level exclusion reasons

| Reason | Count |
|--------|------:|
| `no_signal` | 3217 |

## Known edge cases handled

- GTFS `arrival_time` allows `HH >= 24` for overnight wrap; we modulo by 24 and add days.
- Scheduled local time is interpreted in `America/New_York` per `agency.txt` and converted to UTC.
- `service_date` is derived from the LOCAL date of the first observed position sample for each (trip, vehicle) instance. This is imperfect if a trip starts late — documented as a known assumption.
- Trip-level exclusion on ANY > 3 min gap is strict. The earlier 24-min gap between 01:22Z and 01:47Z caused `gap_over_3min` exclusions.
- Backward `current_stop_sequence` triggers trip-level exclusion (none observed so far).
- A stop at the end of a trip has no `seq+1` samples, so the midpoint fallback is unavailable for the final stop — these often fall to `low`.
