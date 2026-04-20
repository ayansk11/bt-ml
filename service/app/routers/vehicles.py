"""GET /vehicles - live bus positions, enriched with route_id and stale flag."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import STALE_VEHICLE_SEC
from ..models.schemas import VehicleDto
from ..services.gtfs_helpers import epoch_now

router = APIRouter()


@router.get("/vehicles", response_model=list[VehicleDto])
def list_vehicles(request: Request) -> list[VehicleDto]:
    state = request.app.state
    sc = state.static
    feed = state.rt.positions()
    if not feed:
        return []
    now = epoch_now()
    out: list[VehicleDto] = []
    for e in feed.feed_message.entity:  # type: ignore[attr-defined]
        v = e.vehicle
        if not v.vehicle.id:
            continue
        ts = int(v.timestamp) if v.timestamp else 0
        staleness = now - ts if ts else 0
        trip_id = str(v.trip.trip_id) if v.trip.trip_id else None
        route_id = sc.route_of(trip_id) if trip_id else None
        lat = float(v.position.latitude) if v.HasField("position") else 0.0
        lon = float(v.position.longitude) if v.HasField("position") else 0.0
        bearing = float(v.position.bearing) if v.HasField("position") else 0.0
        out.append(VehicleDto(
            vehicle_id=str(v.vehicle.id),
            label=str(v.vehicle.label) if v.vehicle.label else None,
            trip_id=trip_id,
            route_id=route_id,
            lat=lat, lon=lon, bearing=bearing,
            timestamp=ts,
            current_stop_sequence=int(v.current_stop_sequence) if v.current_stop_sequence else None,
            current_status=int(v.current_status),
            is_stale=staleness > STALE_VEHICLE_SEC,
            staleness_seconds=int(staleness),
        ))
    return out
