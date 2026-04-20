"""GET /alerts - GTFS-RT alert feed, parsed."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..models.schemas import AlertDto

router = APIRouter()


@router.get("/alerts", response_model=list[AlertDto])
def list_alerts(request: Request) -> list[AlertDto]:
    feed = request.app.state.rt.alerts()
    if not feed:
        return []
    out: list[AlertDto] = []
    for e in feed.feed_message.entity:  # type: ignore[attr-defined]
        if not e.HasField("alert"):
            continue
        a = e.alert
        header = next((t.text for t in a.header_text.translation), None) if a.HasField("header_text") else None
        desc = next((t.text for t in a.description_text.translation), None) if a.HasField("description_text") else None
        route_ids = [str(ie.route_id) for ie in a.informed_entity if ie.route_id]
        out.append(AlertDto(alert_id=str(e.id), header=header, description=desc, route_ids=route_ids))
    return out
