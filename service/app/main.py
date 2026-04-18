"""FastAPI app entrypoint: loads static data + models on startup, wires routers."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from .routers import alerts, detections, health, nlq, plan, predictions, routes, stats, stops, vehicles
from .services.directions_client import DirectionsClient
from .services.gtfs_client import GtfsRealtimeClient
from .services.predictor import build_predictor
from .services.static_cache import StaticCache

log = logging.getLogger("bt")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    # Directions client — optional. If the key is missing we still boot; /plan
    # will 503 with a clear message rather than crashing the service.
    gmaps_key = os.environ.get("GOOGLE_MAPS_API_KEY") or os.environ.get("MAPS_API_KEY")
    if gmaps_key:
        app.state.directions = DirectionsClient(api_key=gmaps_key)
        log.info("DirectionsClient ready (HTTP/2 enabled)")
    else:
        app.state.directions = None
        log.warning("GOOGLE_MAPS_API_KEY not set; /plan will return 503")

    log.info("Startup complete")
    try:
        yield
    finally:
        if app.state.directions is not None:
            await app.state.directions.close()
        log.info("Shutdown complete")


app = FastAPI(title="BT Inference Service", version="1.1.0", lifespan=lifespan)

# Gzip helps the /plan payload (few KB) — low-overhead compression for anything >500B.
app.add_middleware(GZipMiddleware, minimum_size=500)

# Allow the Android emulator + local dev origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
app.include_router(plan.router)
