"""POST/GET /nlq — stretch endpoint (C2). Stub that returns a no-match shape so the
Android integration can wire it before the real implementation lands in Phase 6."""
from __future__ import annotations

import time

from fastapi import APIRouter, Query

from ..models.schemas import NlqResponse

router = APIRouter()


@router.get("/nlq", response_model=NlqResponse)
def nlq(q: str = Query(..., description="natural language query")) -> NlqResponse:
    t0 = time.perf_counter()
    # Phase 4 stub: echo a "none" parse. Phase 6 (C2) replaces with regex + Claude.
    return NlqResponse(
        query=q,
        intent="unknown",
        parse_source="none",
        latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
    )
