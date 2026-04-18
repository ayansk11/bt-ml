"""GET /stops — static stop catalogue with optional route filter."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query, Request

from ..models.schemas import StopDto

router = APIRouter()


@router.get("/stops", response_model=list[StopDto])
def list_stops(
    request: Request,
    route_id: Optional[str] = Query(None, description="filter to stops served by this route"),
    q: Optional[str] = Query(None, description="name substring, case-insensitive"),
) -> list[StopDto]:
    sc = request.app.state.static
    stops = list(sc.stops_by_id.values())

    if route_id:
        # stops served by this route
        served: set[str] = set()
        for trip_id, trip in sc.trips_by_id.items():
            if trip.route_id == route_id:
                for r in sc.stop_times_by_trip.get(trip_id, []):
                    served.add(r.stop_id)
        stops = [s for s in stops if s.stop_id in served]
    if q:
        ql = q.lower()
        stops = [s for s in stops if ql in s.name.lower()]
    return [StopDto(stop_id=s.stop_id, name=s.name, lat=s.lat, lon=s.lon, code=s.code) for s in stops]
