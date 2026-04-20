"""Build the A1 training dataset.

Input:  data/bt_prediction_error.parquet (per-prediction rows with BT delay + inferred actual)
        data/gtfs_static/{trips,stop_times,shapes,routes}.txt
Output: data/training_rows.parquet with engineered features + target.

Features (all designed to generalise weekday->Saturday):
  hour_of_day, minute_of_hour, day_of_week, is_weekend      (derived from snapshot_ts, America/New_York)
  route_id (categorical)
  bt_trip_delay_seconds                                      (per-prediction BT delay)
  trip_progress_fraction, stops_remaining                    (per-trip static)
  prediction_horizon_seconds                                 (already in input)
  upstream_delay_trend_60s                                   (Δ BT trip delay over prior 60 s)
  route_length_km, average_stop_spacing_m                    (static per route)

Target:
  target_correction_seconds = inferred_actual - bt_predicted  (signed)

Idempotent; re-runnable whenever bt_prediction_error.parquet refreshes.
"""
from __future__ import annotations

import math
from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATIC = DATA / "gtfs_static"
AGENCY_TZ = ZoneInfo("America/New_York")


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def load_static() -> dict:
    trips = pd.read_csv(STATIC / "trips.txt", dtype=str, keep_default_na=False, na_values=[""])
    stop_times = pd.read_csv(STATIC / "stop_times.txt", dtype=str, keep_default_na=False, na_values=[""])
    shapes = pd.read_csv(STATIC / "shapes.txt", dtype=str, keep_default_na=False, na_values=[""])
    routes = pd.read_csv(STATIC / "routes.txt", dtype=str, keep_default_na=False, na_values=[""])
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    shapes["shape_pt_sequence"] = shapes["shape_pt_sequence"].astype(int)
    shapes["shape_pt_lat"] = shapes["shape_pt_lat"].astype(float)
    shapes["shape_pt_lon"] = shapes["shape_pt_lon"].astype(float)
    return {"trips": trips, "stop_times": stop_times, "shapes": shapes, "routes": routes}


def shape_length_km(shape_df: pd.DataFrame) -> float:
    """Polyline length of one shape in km."""
    s = shape_df.sort_values("shape_pt_sequence").reset_index(drop=True)
    if len(s) < 2:
        return 0.0
    lat = s["shape_pt_lat"].values
    lon = s["shape_pt_lon"].values
    meters = haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:]).sum()
    return float(meters) / 1000.0


def compute_per_trip_static(static: dict) -> pd.DataFrame:
    """Produce per-trip_id: total_stops, route_length_km, route_id."""
    trips = static["trips"]
    stop_times = static["stop_times"]
    shapes = static["shapes"]

    # Total stops per trip
    stops_per_trip = stop_times.groupby("trip_id")["stop_sequence"].max().rename("total_stops")
    # GTFS stop_sequence is 1-based; use max rather than count in case of gaps
    # Attach route_id, shape_id
    out = trips.set_index("trip_id")[["route_id", "shape_id"]].copy()
    out = out.join(stops_per_trip)

    # Per-shape length
    shape_lengths = shapes.groupby("shape_id").apply(shape_length_km).rename("route_length_km")
    out = out.reset_index().merge(shape_lengths.reset_index(), on="shape_id", how="left")
    out["route_length_km"] = out["route_length_km"].fillna(0.0)

    # avg stop spacing (m) = length / stops
    out["average_stop_spacing_m"] = np.where(
        out["total_stops"].fillna(0) > 1,
        (out["route_length_km"] * 1000.0) / out["total_stops"].replace(0, np.nan),
        np.nan,
    )
    return out


def add_time_features(df: pd.DataFrame, ts_col: str = "snapshot_ts_utc") -> pd.DataFrame:
    ts = pd.to_datetime(df[ts_col], utc=True).dt.tz_convert(AGENCY_TZ)
    df["hour_of_day"] = ts.dt.hour.astype(int)
    df["minute_of_hour"] = ts.dt.minute.astype(int)
    df["day_of_week"] = ts.dt.dayofweek.astype(int)  # 0=Mon, 6=Sun
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
    return df


def add_upstream_trend(df: pd.DataFrame) -> pd.DataFrame:
    """For each (trip_id, snapshot), compute (bt_trip_delay_now - bt_trip_delay_60s_ago).

    BT delays are trip-level (≈91 % homogeneous), so we approximate the trip delay at
    a snapshot as the median bt_delay across its stops. Then, for each row, we look up
    this trip-level delay at snapshot_ts and at snapshot_ts - 60 s.
    """
    # Trip-level delay time series
    trip_snap = (
        df.groupby(["trip_id", "snapshot_epoch"])
        ["bt_delay_seconds"].median().reset_index().rename(columns={"bt_delay_seconds": "trip_delay_s"})
    )
    trip_snap = trip_snap.sort_values(["trip_id", "snapshot_epoch"]).reset_index(drop=True)

    # For each (trip_id, snapshot_epoch) row, find the most recent (trip_id, snapshot_epoch - 60) value
    # via asof-merge.
    lag_key = trip_snap.copy()
    lag_key["snapshot_epoch"] = lag_key["snapshot_epoch"] + 60  # shift forward 60s => matches "now"
    lag_key = lag_key.rename(columns={"trip_delay_s": "trip_delay_60s_ago"})

    merged = pd.merge_asof(
        trip_snap.sort_values("snapshot_epoch"),
        lag_key[["trip_id", "snapshot_epoch", "trip_delay_60s_ago"]].sort_values("snapshot_epoch"),
        on="snapshot_epoch", by="trip_id",
        direction="backward",
        tolerance=90,  # accept up to 90s old, since publish cadence ~10s but we want a 60s lag
    )
    merged["upstream_delay_trend_60s"] = (
        merged["trip_delay_s"] - merged["trip_delay_60s_ago"]
    ).astype(float)
    # If we don't have a prior sample, trend = 0 (safer than NaN for tree boosters; mark with a feature)
    merged["has_upstream_trend"] = merged["upstream_delay_trend_60s"].notna().astype(int)
    merged["upstream_delay_trend_60s"] = merged["upstream_delay_trend_60s"].fillna(0.0)

    # Merge back into df per (trip_id, snapshot_epoch)
    df = df.merge(
        merged[["trip_id", "snapshot_epoch", "upstream_delay_trend_60s", "has_upstream_trend"]],
        on=["trip_id", "snapshot_epoch"], how="left",
    )
    df["upstream_delay_trend_60s"] = df["upstream_delay_trend_60s"].fillna(0.0)
    df["has_upstream_trend"] = df["has_upstream_trend"].fillna(0).astype(int)
    return df


def build() -> pd.DataFrame:
    pe = pd.read_parquet(DATA / "bt_prediction_error.parquet")
    pe = pe.copy()

    # target
    pe["target_correction_seconds"] = (-pe["error_seconds"]).astype(float)
    # rename for clarity
    pe = pe.rename(columns={
        "bt_delay_seconds": "bt_trip_delay_seconds",
        "horizon_seconds": "prediction_horizon_seconds",
    })

    # time features
    pe = add_time_features(pe, "snapshot_ts_utc")

    # per-trip static
    static = load_static()
    trip_static = compute_per_trip_static(static).set_index("trip_id")

    # join
    pe["trip_id"] = pe["trip_id"].astype(str)
    pe = pe.join(trip_static[["total_stops", "route_length_km", "average_stop_spacing_m"]], on="trip_id")
    # stops remaining
    pe["stop_sequence"] = pe["stop_sequence"].astype(int)
    pe["stops_remaining"] = (pe["total_stops"].fillna(0).astype(int) - pe["stop_sequence"]).clip(lower=0)
    pe["trip_progress_fraction"] = np.where(
        pe["total_stops"].fillna(0).astype(int) > 0,
        pe["stop_sequence"].astype(float) / pe["total_stops"].astype(float),
        np.nan,
    )

    # upstream trend (requires bt_trip_delay_seconds column, which we renamed above - rebuild trip_level under original name)
    tmp = pe.rename(columns={"bt_trip_delay_seconds": "bt_delay_seconds"})
    tmp = add_upstream_trend(tmp)
    pe["upstream_delay_trend_60s"] = tmp["upstream_delay_trend_60s"]
    pe["has_upstream_trend"] = tmp["has_upstream_trend"]

    # final column set for training
    feature_cols = [
        "hour_of_day", "minute_of_hour", "day_of_week", "is_weekend",
        "route_id",  # categorical
        "bt_trip_delay_seconds",
        "trip_progress_fraction", "stops_remaining",
        "prediction_horizon_seconds",
        "upstream_delay_trend_60s", "has_upstream_trend",
        "route_length_km", "average_stop_spacing_m",
    ]
    meta_cols = [
        "trip_id", "stop_id", "stop_sequence", "service_id",
        "ground_truth_confidence", "snapshot_epoch", "target_correction_seconds",
        # also keep the baseline BT prediction for evaluation
        "error_seconds", "horizon_bucket",
    ]

    out = pe[feature_cols + meta_cols].copy()
    # Drop rows where essential fields are missing
    before = len(out)
    out = out.dropna(subset=["bt_trip_delay_seconds", "target_correction_seconds", "prediction_horizon_seconds"])
    after = len(out)
    print(f"[build_dataset] dropped {before - after} rows with missing essentials; {after} remain")

    # Fill remaining nans with 0 for numeric tree features; categorical stays as-is
    num_cols = [c for c in feature_cols if c != "route_id"]
    for c in num_cols:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float).fillna(0.0)
    out["route_id"] = out["route_id"].astype(str)

    out.to_parquet(DATA / "training_rows.parquet", index=False)
    print(f"[build_dataset] wrote {DATA / 'training_rows.parquet'} rows={len(out)}")
    print(f"[build_dataset] target stats: mean={out['target_correction_seconds'].mean():.1f}s  "
          f"median={out['target_correction_seconds'].median():.1f}s  "
          f"|mean_abs|={out['target_correction_seconds'].abs().mean():.1f}s")
    print(f"[build_dataset] per-route row counts:")
    print(out.groupby('route_id').size().sort_values(ascending=False).to_string())
    return out


if __name__ == "__main__":
    build()
