"""GET /healthz — liveness + model state."""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..models.schemas import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
def healthz(request: Request) -> HealthResponse:
    state = request.app.state
    return HealthResponse(
        status="ok",
        model_source=state.predictor.model_source,
        model_loaded=not (state.predictor.model_source == "passthrough"),
        a1_abort=bool(state.metadata.get("aborted", False)),
        n_routes_with_intercept=sum(1 for v in state.intercepts.values.values() if v != 0),
    )
