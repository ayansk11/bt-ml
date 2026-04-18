"""GET /plan?origin_lat=..&origin_lng=..&dest_lat=..&dest_lng=.. [&departure_time=epoch]

Proxies Google Directions (transit mode), enriches transit steps with our
A1+A2 adjusted boarding ETA + A3 confidence, returns compact JSON.

Low-latency tactics:
  - Singleton async httpx client with HTTP/2 + keepalive (see directions_client.py)
  - TTL cache on Directions responses, keyed by rounded lat/lng buckets
  - StopSnapIndex pre-built; nearest-stop lookup is ~O(n) over 512 stops (~0.3 ms)
  - No Python-level blocking calls in the request path after startup
  - Response returned as JSON (FastAPI + orjson if installed); FastAPI + Starlette
    already pick the fastest available encoder

Never 5xxs: on Directions upstream error we return `{status:"UPSTREAM_ERROR",routes:[]}`
with the error detail in `meta`.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..services.trip_planner import build_trip_plan

log = logging.getLogger("bt.plan")
router = APIRouter()


@router.get("/plan")
async def plan(
    request: Request,
    origin_lat: float = Query(...),
    origin_lng: float = Query(...),
    dest_lat: float = Query(...),
    dest_lng: float = Query(...),
    departure_time: Optional[int] = Query(None, description="epoch seconds; 'now' if omitted"),
):
    state = request.app.state
    directions_client = getattr(state, "directions", None)
    if directions_client is None:
        raise HTTPException(status_code=503, detail="directions_client not configured (missing GOOGLE_MAPS_API_KEY?)")

    t0 = time.perf_counter()
    payload, meta = await directions_client.plan(
        (origin_lat, origin_lng), (dest_lat, dest_lng),
        mode="transit", departure_time=departure_time, alternatives=True,
    )
    t_google = time.perf_counter()

    if not payload:
        return JSONResponse(
            content={
                "status": "UPSTREAM_ERROR",
                "routes": [],
                "meta": meta,
            },
            status_code=200,
        )

    plan_resp = build_trip_plan(payload, state.static, state.predictor, state.intercepts)
    t_done = time.perf_counter()

    plan_resp["meta"] = {
        **meta,
        "enrich_ms": round((t_done - t_google) * 1000.0, 2),
        "total_ms": round((t_done - t0) * 1000.0, 2),
        "model_source": state.predictor.model_source,
    }
    return plan_resp
