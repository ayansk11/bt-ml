"""Convert Google Directions payload → compact TripPlan response, with AI enrichment.

Design goals (in order):
  1. Low latency. Reuse cached static maps, do no DB/network calls inside the
     per-step loop.
  2. Small wire shape. Strip Google's chatty legs/steps into just what the
     Android UI renders.
  3. AI enrichment is best-effort. If matching fails for a step, we quietly
     fall back to Google's own times.

Matching policy:
  - Map Google's `transit_details.line.short_name` (e.g. "6", "3E") to our
    BT `route_id` via case-insensitive equality. BT route_id *is* the short name.
  - Snap Google's `departure_stop.location` to the nearest BT stop within
    80 m (one block). Beyond that, no AI adjustment — would be a different
    stop altogether.
  - AI correction uses `predictor.predict_correction` + `combine_correction`
    on a feature row built from the matched BT stop_sequence within the
    resolved trip.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from ..services.predictor import combine_correction, confidence_tier
from ..services.gtfs_helpers import time_features_from
from ..services.static_cache import StaticCache

EARTH_RADIUS_M = 6371000.0
MAX_STOP_SNAP_M = 80.0


def _hav(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


@dataclass
class _StopSnapIndex:
    """Pre-built on StaticCache load: a flat list we can linear-scan (512 stops).
    For 512 stops this is faster than building a KD-tree given our call volume."""
    stops: list[tuple[str, float, float]]

    @classmethod
    def from_cache(cls, sc: StaticCache) -> "_StopSnapIndex":
        return cls([(s.stop_id, s.lat, s.lon) for s in sc.stops_by_id.values()])

    def nearest(self, lat: float, lon: float, max_m: float = MAX_STOP_SNAP_M) -> Optional[tuple[str, float]]:
        best_id: Optional[str] = None
        best_d = max_m
        for sid, slat, slon in self.stops:
            d = _hav(lat, lon, slat, slon)
            if d < best_d:
                best_d = d
                best_id = sid
        return (best_id, best_d) if best_id else None


def _compact_walk_step(step: dict) -> dict:
    return {
        "mode": "WALK",
        "duration_s": int(step.get("duration", {}).get("value", 0)),
        "distance_m": int(step.get("distance", {}).get("value", 0)),
        "html_instructions": step.get("html_instructions", ""),
        "start_location": step.get("start_location"),
        "end_location": step.get("end_location"),
        "polyline": step.get("polyline", {}).get("points"),
    }


def _compact_transit_step(step: dict, sc: StaticCache, snap: _StopSnapIndex,
                          predictor, intercepts) -> dict:
    td = step.get("transit_details", {})
    line = td.get("line", {}) or {}
    short_name = str(line.get("short_name") or line.get("name") or "").strip()
    # Snap to BT route_id (BT uses short_name as route_id)
    bt_route_id = short_name.upper() if short_name else None
    if bt_route_id and bt_route_id not in sc.routes_by_id:
        # try exact-case first
        if short_name in sc.routes_by_id:
            bt_route_id = short_name
        else:
            bt_route_id = None

    dep = td.get("departure_stop", {}) or {}
    arr = td.get("arrival_stop", {}) or {}
    dep_loc = dep.get("location") or {}
    arr_loc = arr.get("location") or {}

    dep_snap = None
    arr_snap = None
    if isinstance(dep_loc.get("lat"), (int, float)) and isinstance(dep_loc.get("lng"), (int, float)):
        dep_snap = snap.nearest(dep_loc["lat"], dep_loc["lng"])
    if isinstance(arr_loc.get("lat"), (int, float)) and isinstance(arr_loc.get("lng"), (int, float)):
        arr_snap = snap.nearest(arr_loc["lat"], arr_loc["lng"])

    dep_time_text = td.get("departure_time", {}).get("text")
    dep_time_value = td.get("departure_time", {}).get("value")  # epoch seconds
    arr_time_text = td.get("arrival_time", {}).get("text")
    arr_time_value = td.get("arrival_time", {}).get("value")

    # AI correction on boarding ETA — best effort
    ai_adjusted_departure_ts: Optional[int] = None
    ai_correction_s: Optional[float] = None
    confidence: Optional[str] = None
    if bt_route_id and dep_snap and dep_time_value:
        dep_stop_id, _ = dep_snap
        # Use route_stops membership to find a plausible stop_sequence: first stop_time
        # of any trip on this route that touches this stop_id.
        seq_guess: Optional[int] = None
        total_stops_guess: int = 0
        for (tid, rid, *_rest) in _trips_for_route(sc, bt_route_id):
            for row in sc.stop_times_by_trip.get(tid, []):
                if row.stop_id == dep_stop_id:
                    seq_guess = row.stop_sequence
                    total_stops_guess = sc.total_stops_per_trip.get(tid, 0) or 0
                    break
            if seq_guess is not None:
                break
        if seq_guess is not None and total_stops_guess > 0:
            dep_dt = datetime.fromtimestamp(int(dep_time_value), tz=timezone.utc)
            feat = time_features_from(dep_dt)
            feature_row = {
                **feat,
                "route_id": bt_route_id,
                "bt_trip_delay_seconds": 0.0,  # Google's time is already BT-ish; treat delta from Google as our correction
                "trip_progress_fraction": seq_guess / max(1, total_stops_guess),
                "stops_remaining": float(max(0, total_stops_guess - seq_guess)),
                "prediction_horizon_seconds": max(0.0, float(int(dep_time_value) - int(datetime.now(timezone.utc).timestamp()))),
                "upstream_delay_trend_60s": 0.0,
                "has_upstream_trend": 0,
                "route_length_km": float(sc.route_length_km_by_route.get(bt_route_id, 0.0)),
                "average_stop_spacing_m": float(sc.avg_stop_spacing_m_by_route.get(bt_route_id, 0.0)),
            }
            a1 = predictor.predict_correction(feature_row)
            correction, src = combine_correction(predictor, intercepts, bt_route_id, a1)
            ai_adjusted_departure_ts = int(dep_time_value) + int(round(correction))
            ai_correction_s = round(float(correction), 1)
            horizon_s = max(0.0, float(int(dep_time_value) - int(datetime.now(timezone.utc).timestamp())))
            confidence = confidence_tier(predictor, bt_route_id, horizon_s, has_upstream_trend=False, used_model_source=src)

    color = line.get("color") or "#2E7D32"
    return {
        "mode": "TRANSIT",
        "duration_s": int(step.get("duration", {}).get("value", 0)),
        "distance_m": int(step.get("distance", {}).get("value", 0)),
        "html_instructions": step.get("html_instructions", ""),
        "line_short_name": short_name,
        "line_color": color,
        "line_name": line.get("name"),
        "bt_route_id": bt_route_id,
        "headsign": td.get("headsign"),
        "num_stops": int(td.get("num_stops", 0)),
        "departure_stop": {
            "name": dep.get("name"),
            "location": dep_loc,
            "bt_stop_id": dep_snap[0] if dep_snap else None,
            "bt_snap_distance_m": round(dep_snap[1], 1) if dep_snap else None,
            "time_text": dep_time_text,
            "time_value": dep_time_value,
            "ai_adjusted_time_value": ai_adjusted_departure_ts,
            "ai_correction_seconds": ai_correction_s,
            "confidence": confidence,
        },
        "arrival_stop": {
            "name": arr.get("name"),
            "location": arr_loc,
            "bt_stop_id": arr_snap[0] if arr_snap else None,
            "time_text": arr_time_text,
            "time_value": arr_time_value,
        },
        "polyline": step.get("polyline", {}).get("points"),
    }


def _trips_for_route(sc: StaticCache, route_id: str):
    """Lazy generator — stops the search early once seq is found."""
    for tid, trip in sc.trips_by_id.items():
        if trip.route_id == route_id:
            yield (tid, route_id)


def build_trip_plan(directions_payload: dict, sc: StaticCache, predictor, intercepts) -> dict:
    """Top-level transform from Google response → our wire format."""
    status = directions_payload.get("status", "ERROR")
    routes_out = []
    snap = _StopSnapIndex.from_cache(sc)
    for route in directions_payload.get("routes", []):
        legs = route.get("legs", [])
        if not legs:
            continue
        leg = legs[0]
        steps: list[dict] = []
        for step in leg.get("steps", []):
            if step.get("travel_mode") == "TRANSIT":
                steps.append(_compact_transit_step(step, sc, snap, predictor, intercepts))
            else:
                steps.append(_compact_walk_step(step))
        routes_out.append({
            "summary": route.get("summary"),
            "duration_s": int(leg.get("duration", {}).get("value", 0)),
            "distance_m": int(leg.get("distance", {}).get("value", 0)),
            "departure_time_value": leg.get("departure_time", {}).get("value"),
            "departure_time_text": leg.get("departure_time", {}).get("text"),
            "arrival_time_value": leg.get("arrival_time", {}).get("value"),
            "arrival_time_text": leg.get("arrival_time", {}).get("text"),
            "start_address": leg.get("start_address"),
            "end_address": leg.get("end_address"),
            "start_location": leg.get("start_location"),
            "end_location": leg.get("end_location"),
            "warnings": route.get("warnings", []),
            "overview_polyline": route.get("overview_polyline", {}).get("points"),
            "steps": steps,
        })

    return {"status": status, "routes": routes_out}
