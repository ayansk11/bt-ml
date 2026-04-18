# Ground-Truth Coverage Report

_Generated 2026-04-18T01:50:54.132955+00:00_


## Window

- Positions snapshots scanned: 271
- First pos_ts observed: 2026-04-18T00:34:10+00:00
- Last pos_ts observed:  2026-04-18T01:49:57+00:00
- Distinct `(trip_id, vehicle_id)` instances: 42
- Trip-level exclusions: 2 ({'gap_over_3min': 2})

## Label counts by confidence

| Confidence | Method            | Count | % of total |
|------------|-------------------|------:|-----------:|
| **high**   | `stopped_at`      |   112 | 11.3% |
| **medium** | `midpoint`        |   323 | 32.5% |
| **low**    | `excluded`        |   559 | 56.2% |
| **TOTAL**  |                   |   994 | 100% |

### :warning: HIGH-CONFIDENCE RATE IS BELOW 50%

- **Only 11.3% of `(trip, stop)` pairs received a HIGH-confidence label.**
- 43.8% are USABLE (high + medium). 56.2% are excluded.
- Primary reason for exclusion: `no_signal` — the vehicle had not yet reached that stop within the observation window, so no samples exist at that stop_sequence or at the neighbouring N-1 / N+1.
- Mechanically, HIGH confidence requires catching the vehicle in the `STOPPED_AT` state at that stop. With a 30 s per-vehicle cadence and typical dwell times of 10–30 s, we miss many stops purely due to sampling.
- Keep the logger running — each additional hour of data materially increases HIGH-confidence coverage of any stops that ARE visited in that time.

## Distribution of `(inferred_actual - scheduled)` delay

Sanity-check: for ground truth to be plausible, this should be roughly centred near 0–60 s (a typical slight lateness) with a long positive tail, not bimodal or centred far from zero.


| Subset | n | mean | median | p10 | p90 | p99 | min | max |
|--------|---:|-----:|-------:|----:|----:|----:|----:|----:|
| **overall (high+medium)** | 435 | 131.7s | 94.0s | -63.2s | 424.6s | 790.4s | -1199.0s | 847.5s |
| `high` only | 112 | 90.0s | 44.5s | -113.3s | 312.8s | 760.9s | -1199.0s | 810.0s |
| `medium` only | 323 | 146.2s | 115.0s | -49.9s | 444.2s | 791.7s | -480.0s | 847.5s |

## Per-route label counts

| route_id | high | medium | low | total |
|----------|-----:|-------:|----:|------:|
| `1` | 7 | 27 | 0 | 34 |
| `11` | 3 | 9 | 0 | 12 |
| `2S` | 6 | 14 | 0 | 20 |
| `2W` | 4 | 9 | 0 | 13 |
| `3E` | 16 | 61 | 0 | 77 |
| `3W` | 11 | 48 | 0 | 59 |
| `4S` | 8 | 28 | 0 | 36 |
| `4W` | 12 | 21 | 0 | 33 |
| `5` | 6 | 17 | 0 | 23 |
| `6` | 10 | 26 | 0 | 36 |
| `7` | 16 | 28 | 0 | 44 |
| `9` | 13 | 35 | 0 | 48 |

## Stop-level exclusion reasons

| Reason | Count |
|--------|------:|
| `no_signal` | 559 |

## Known edge cases handled

- GTFS `arrival_time` allows `HH >= 24` for overnight wrap; we modulo by 24 and add days.
- Scheduled local time is interpreted in `America/New_York` per `agency.txt` and converted to UTC.
- `service_date` is derived from the LOCAL date of the first observed position sample for each (trip, vehicle) instance. This is imperfect if a trip starts late — documented as a known assumption.
- Trip-level exclusion on ANY > 3 min gap is strict. The earlier 24-min gap between 01:22Z and 01:47Z caused `gap_over_3min` exclusions.
- Backward `current_stop_sequence` triggers trip-level exclusion (none observed so far).
- A stop at the end of a trip has no `seq+1` samples, so the midpoint fallback is unavailable for the final stop — these often fall to `low`.
