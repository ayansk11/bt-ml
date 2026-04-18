"""FastAPI entry — spine endpoints are wired in Phase 4.

For Phase 1, this provides `/healthz` and a runnable uvicorn target so that
the initial commit produces a genuinely runnable artifact.
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="BT Inference Service", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "service": "bt-ml", "phase": "1-scaffold"}
