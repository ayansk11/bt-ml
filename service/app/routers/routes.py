"""GET /routes - static route catalogue."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..models.schemas import RouteDto

router = APIRouter()


@router.get("/routes", response_model=list[RouteDto])
def list_routes(request: Request) -> list[RouteDto]:
    sc = request.app.state.static
    return [
        RouteDto(
            route_id=r.route_id,
            short_name=r.short_name,
            long_name=r.long_name,
            color=r.color,
            text_color=r.text_color,
        )
        for r in sc.routes_by_id.values()
    ]
