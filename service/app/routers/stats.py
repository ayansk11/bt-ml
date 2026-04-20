"""GET /stats - live BT-vs-ours audit numbers, plus fleet health for D1 dashboard."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..config import BT_HEADLINE_MAE, STALE_VEHICLE_SEC
from ..models.schemas import StatsResponse
from ..services.gtfs_helpers import epoch_now, now_utc

router = APIRouter()


@router.get("/stats", response_model=StatsResponse)
def stats(request: Request) -> StatsResponse:
    state = request.app.state
    meta = state.metadata
    cv = meta.get("cv", {}) if isinstance(meta, dict) else {}
    hmae = cv.get("oof_3_5_min", {}).get("mae") if isinstance(cv.get("oof_3_5_min"), dict) else None

    # live fleet health
    pos = state.rt.positions()
    now_ep = epoch_now()
    fleet = 0
    stale = 0
    if pos:
        for e in pos.feed_message.entity:
            v = e.vehicle
            if not v.vehicle.id:
                continue
            fleet += 1
            ts = int(v.timestamp) if v.timestamp else 0
            if ts and (now_ep - ts) > STALE_VEHICLE_SEC:
                stale += 1

    intercepts_nonzero = sum(1 for v in state.intercepts.values.values() if v != 0)
    return StatsResponse(
        generated_at_utc=now_utc().isoformat(),
        bt_headline_mae_s=BT_HEADLINE_MAE,
        a1_cv_headline_mae_s=float(hmae) if hmae is not None else None,
        a1_cv_improvement_s=(BT_HEADLINE_MAE - float(hmae)) if hmae is not None else None,
        a1_cv_improvement_pct=((BT_HEADLINE_MAE - float(hmae)) / BT_HEADLINE_MAE * 100) if hmae is not None else None,
        model_source=state.predictor.model_source,
        routes_with_intercept=intercepts_nonzero,
        live_fleet_size=fleet,
        live_stale_vehicle_count=stale,
    )
