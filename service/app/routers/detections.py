"""GET /detections/bunching - pairs of same-route vehicles within BUNCHING_RADIUS_M."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import BUNCHING_RADIUS_M
from ..models.schemas import BunchingEventDto, BunchingResponse
from ..services.gtfs_helpers import haversine_m, now_utc

router = APIRouter()


@router.get("/detections/bunching", response_model=BunchingResponse)
def bunching(request: Request) -> BunchingResponse:
    state = request.app.state
    sc = state.static
    feed = state.rt.positions()
    now = now_utc()
    if not feed:
        return BunchingResponse(generated_at_utc=now.isoformat(), events=[])

    # Group live vehicles by route_id (derived from trip → static)
    by_route: dict[str, list[tuple[str, float, float]]] = {}
    for e in feed.feed_message.entity:
        v = e.vehicle
        if not v.vehicle.id or not v.HasField("position"):
            continue
        tid = str(v.trip.trip_id) if v.trip.trip_id else ""
        if not tid:
            continue
        rid = sc.route_of(tid)
        if not rid:
            continue
        by_route.setdefault(rid, []).append((str(v.vehicle.id), float(v.position.latitude), float(v.position.longitude)))

    events: list[BunchingEventDto] = []
    for rid, vehs in by_route.items():
        n = len(vehs)
        for i in range(n):
            for j in range(i + 1, n):
                vid_a, la, lo = vehs[i]
                vid_b, lb, lo_b = vehs[j]
                d = haversine_m(la, lo, lb, lo_b)
                if d <= BUNCHING_RADIUS_M:
                    sev = "critical" if d <= BUNCHING_RADIUS_M * 0.5 else "warning"
                    events.append(BunchingEventDto(
                        route_id=rid,
                        vehicle_ids=[vid_a, vid_b],
                        distance_m=round(d, 1),
                        lat=(la + lb) / 2.0,
                        lon=(lo + lo_b) / 2.0,
                        severity=sev,  # type: ignore[arg-type]
                    ))

    return BunchingResponse(generated_at_utc=now.isoformat(), events=events)
