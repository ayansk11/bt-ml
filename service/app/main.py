"""FastAPI entry — wires all spine routers + model loading on startup.

Design: app.state carries the loaded static cache, live RT client, predictor,
intercepts, and metadata. Routers pull from request.app.state. This keeps
every endpoint testable by constructing a FastAPI app in tests and injecting
mocks into app.state (see service/app/tests/).
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import alerts, detections, health, nlq, predictions, routes, stats, stops, vehicles
from .services.gtfs_client import GtfsRealtimeClient
from .services.predictor import build_predictor
from .services.static_cache import StaticCache

log = logging.getLogger("bt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="BT Inference Service", version="1.0.0")

# Allow the Android emulator + local dev origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    log.info("Loading static GTFS...")
    sc = StaticCache()
    sc.load()
    log.info("Static loaded: %d routes, %d stops, %d trips, stop_times for %d trips",
             len(sc.routes_by_id), len(sc.stops_by_id), len(sc.trips_by_id), len(sc.stop_times_by_trip))
    app.state.static = sc

    log.info("Loading A1 + route intercepts...")
    predictor, intercepts, metadata = build_predictor()
    app.state.predictor = predictor
    app.state.intercepts = intercepts
    app.state.metadata = metadata
    log.info("Predictor ready: model_source=%s  intercepts=%d routes",
             predictor.model_source, len(intercepts.values))

    app.state.rt = GtfsRealtimeClient()
    log.info("Startup complete")


# Routers
app.include_router(health.router)
app.include_router(routes.router)
app.include_router(stops.router)
app.include_router(vehicles.router)
app.include_router(alerts.router)
app.include_router(predictions.router)
app.include_router(detections.router)
app.include_router(stats.router)
app.include_router(nlq.router)
