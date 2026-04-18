"""Loads static GTFS into in-memory maps on startup.

Everything needed for prediction joins + passthrough endpoints:
  - routes_by_id: dict[route_id, RouteRecord]
  - stops_by_id:  dict[stop_id, StopRecord]
  - trips_by_id:  dict[trip_id, TripRecord]
  - stop_times_by_trip: dict[trip_id, list[StopTimeRow]]  (sorted by stop_sequence)
  - stop_id_to_trip_stops: dict[stop_id, list[(trip_id, stop_sequence)]]
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import STATIC_DIR


@dataclass
class RouteRecord:
    route_id: str
    short_name: str
    long_name: str
    color: str
    text_color: str = "FFFFFF"


@dataclass
class StopRecord:
    stop_id: str
    name: str
    lat: float
    lon: float
    code: Optional[str] = None


@dataclass
class TripRecord:
    trip_id: str
    route_id: str
    service_id: str
    headsign: Optional[str]
    direction_id: Optional[str]
    shape_id: Optional[str]


@dataclass
class StopTimeRow:
    trip_id: str
    stop_id: str
    stop_sequence: int
    arrival_time: str  # "HH:MM:SS" in agency local
    departure_time: str


class StaticCache:
    def __init__(self) -> None:
        self.routes_by_id: dict[str, RouteRecord] = {}
        self.stops_by_id: dict[str, StopRecord] = {}
        self.trips_by_id: dict[str, TripRecord] = {}
        self.stop_times_by_trip: dict[str, list[StopTimeRow]] = {}
        self.stop_id_to_trip_stops: dict[str, list[tuple[str, int]]] = {}
        self.total_stops_per_trip: dict[str, int] = {}
        self.route_length_km_by_route: dict[str, float] = {}
        self.avg_stop_spacing_m_by_route: dict[str, float] = {}

    def load(self) -> None:
        routes = pd.read_csv(STATIC_DIR / "routes.txt", dtype=str, keep_default_na=False, na_values=[""])
        for _, r in routes.iterrows():
            self.routes_by_id[str(r["route_id"])] = RouteRecord(
                route_id=str(r["route_id"]),
                short_name=str(r.get("route_short_name", "")),
                long_name=str(r.get("route_long_name", "")),
                color=str(r.get("route_color", "0057A8")) or "0057A8",
                text_color=str(r.get("route_text_color", "FFFFFF")) or "FFFFFF",
            )

        stops = pd.read_csv(STATIC_DIR / "stops.txt", dtype=str, keep_default_na=False, na_values=[""])
        for _, r in stops.iterrows():
            try:
                lat = float(r["stop_lat"]); lon = float(r["stop_lon"])
            except Exception:
                continue
            self.stops_by_id[str(r["stop_id"])] = StopRecord(
                stop_id=str(r["stop_id"]),
                name=str(r.get("stop_name", "")),
                lat=lat, lon=lon,
                code=str(r.get("stop_code", "")) or None,
            )

        trips = pd.read_csv(STATIC_DIR / "trips.txt", dtype=str, keep_default_na=False, na_values=[""])
        for _, r in trips.iterrows():
            self.trips_by_id[str(r["trip_id"])] = TripRecord(
                trip_id=str(r["trip_id"]),
                route_id=str(r["route_id"]),
                service_id=str(r.get("service_id", "")),
                headsign=str(r.get("trip_headsign", "")) or None,
                direction_id=str(r.get("direction_id", "")) or None,
                shape_id=str(r.get("shape_id", "")) or None,
            )

        st = pd.read_csv(STATIC_DIR / "stop_times.txt", dtype=str, keep_default_na=False, na_values=[""])
        st["stop_sequence"] = st["stop_sequence"].astype(int)
        for trip_id, g in st.groupby("trip_id"):
            g = g.sort_values("stop_sequence")
            rows = [
                StopTimeRow(
                    trip_id=str(trip_id),
                    stop_id=str(r["stop_id"]),
                    stop_sequence=int(r["stop_sequence"]),
                    arrival_time=str(r["arrival_time"]),
                    departure_time=str(r.get("departure_time") or r["arrival_time"]),
                )
                for _, r in g.iterrows()
            ]
            self.stop_times_by_trip[str(trip_id)] = rows
            self.total_stops_per_trip[str(trip_id)] = len(rows)
            for row in rows:
                self.stop_id_to_trip_stops.setdefault(row.stop_id, []).append((row.trip_id, row.stop_sequence))

        # Precompute per-route length / spacing for feature lookup at inference time
        shapes = pd.read_csv(STATIC_DIR / "shapes.txt", dtype=str, keep_default_na=False, na_values=[""])
        shapes["shape_pt_sequence"] = shapes["shape_pt_sequence"].astype(int)
        shapes["shape_pt_lat"] = shapes["shape_pt_lat"].astype(float)
        shapes["shape_pt_lon"] = shapes["shape_pt_lon"].astype(float)
        # trip -> length
        from math import asin, cos, radians, sin, sqrt
        def hav(a_lat, a_lon, b_lat, b_lon):
            R = 6371000.0
            p1 = radians(a_lat); p2 = radians(b_lat)
            dp = radians(b_lat - a_lat); dl = radians(b_lon - a_lon)
            x = sin(dp/2)**2 + cos(p1)*cos(p2)*sin(dl/2)**2
            return 2 * R * asin(sqrt(x))

        shape_lengths_m: dict[str, float] = {}
        for shape_id, g in shapes.groupby("shape_id"):
            g = g.sort_values("shape_pt_sequence").reset_index(drop=True)
            total = 0.0
            for i in range(1, len(g)):
                total += hav(g.iloc[i-1]["shape_pt_lat"], g.iloc[i-1]["shape_pt_lon"],
                             g.iloc[i]["shape_pt_lat"], g.iloc[i]["shape_pt_lon"])
            shape_lengths_m[str(shape_id)] = total

        # aggregate per-route: average of trip lengths (in km) among trips whose shape_id we have a length for
        trip_len_km: dict[str, float] = {}
        for trip_id, trip in self.trips_by_id.items():
            sid = trip.shape_id
            if sid and sid in shape_lengths_m:
                trip_len_km[trip_id] = shape_lengths_m[sid] / 1000.0
        # route means
        from collections import defaultdict
        per_route_len: dict[str, list[float]] = defaultdict(list)
        per_route_stops: dict[str, list[int]] = defaultdict(list)
        for trip_id, km in trip_len_km.items():
            rid = self.trips_by_id[trip_id].route_id
            per_route_len[rid].append(km)
            per_route_stops[rid].append(self.total_stops_per_trip.get(trip_id, 0))
        for rid, lens in per_route_len.items():
            self.route_length_km_by_route[rid] = sum(lens) / max(1, len(lens))
            stops = per_route_stops[rid]
            avg_stops = sum(stops) / max(1, len(stops))
            if avg_stops > 1:
                self.avg_stop_spacing_m_by_route[rid] = (self.route_length_km_by_route[rid] * 1000.0) / avg_stops
            else:
                self.avg_stop_spacing_m_by_route[rid] = 0.0

    # helpers used at inference time
    def total_stops_of(self, trip_id: str) -> int:
        return self.total_stops_per_trip.get(trip_id, 0)

    def route_of(self, trip_id: str) -> Optional[str]:
        t = self.trips_by_id.get(trip_id)
        return t.route_id if t else None
