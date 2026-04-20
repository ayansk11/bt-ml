"""Pydantic response models - the wire contract the Android client consumes."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


class HealthResponse(BaseModel):
    status: str
    service: str = "bt-ml"
    model_source: str
    model_loaded: bool
    a1_abort: bool
    n_routes_with_intercept: int
    version: str = "1.0.0"


class RouteDto(BaseModel):
    route_id: str
    short_name: str
    long_name: str
    color: str
    text_color: Optional[str] = None


class StopDto(BaseModel):
    stop_id: str
    name: str
    lat: float
    lon: float
    code: Optional[str] = None


class VehicleDto(BaseModel):
    vehicle_id: str
    label: Optional[str] = None
    trip_id: Optional[str] = None
    route_id: Optional[str] = None       # derived from trip_id -> trips.txt lookup
    lat: float
    lon: float
    bearing: float
    timestamp: int
    current_stop_sequence: Optional[int] = None
    current_status: Optional[int] = None
    is_stale: bool                       # (now - timestamp) > 90s
    staleness_seconds: int


class AlertDto(BaseModel):
    alert_id: str
    header: Optional[str] = None
    description: Optional[str] = None
    route_ids: list[str] = Field(default_factory=list)


class PredictionDto(BaseModel):
    stop_id: str
    stop_sequence: int
    trip_id: str
    route_id: Optional[str] = None
    route_short_name: Optional[str] = None
    headsign: Optional[str] = None
    vehicle_id: Optional[str] = None
    scheduled_arrival_utc: str
    bt_delay_seconds: int
    bt_predicted_arrival_utc: str
    ours_predicted_arrival_utc: str
    correction_seconds: float
    horizon_seconds: int
    confidence: Confidence
    model_source: Literal["a1_lightgbm", "a2_intercept", "passthrough"]
    is_realtime: bool


class PredictionsResponse(BaseModel):
    stop_id: str
    stop_name: Optional[str] = None
    horizon_minutes: int
    generated_at_utc: str
    feed_header_ts_utc: Optional[str] = None
    feed_header_age_seconds: Optional[int] = None
    predictions: list[PredictionDto]


class TripStopEtaDto(BaseModel):
    stop_id: str
    stop_sequence: int
    stop_name: Optional[str] = None
    scheduled_arrival_utc: str
    bt_predicted_arrival_utc: str
    ours_predicted_arrival_utc: str
    correction_seconds: float
    confidence: Confidence


class TripEtaTrajectoryResponse(BaseModel):
    trip_id: str
    route_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    current_stop_sequence: Optional[int] = None
    generated_at_utc: str
    stops: list[TripStopEtaDto]


class BunchingEventDto(BaseModel):
    route_id: str
    vehicle_ids: list[str]
    distance_m: float
    lat: float
    lon: float
    severity: Literal["warning", "critical"]


class BunchingResponse(BaseModel):
    generated_at_utc: str
    events: list[BunchingEventDto]


class StatsResponse(BaseModel):
    generated_at_utc: str
    bt_headline_mae_s: float
    a1_cv_headline_mae_s: Optional[float] = None
    a1_cv_improvement_s: Optional[float] = None
    a1_cv_improvement_pct: Optional[float] = None
    model_source: str
    routes_with_intercept: int
    live_fleet_size: int
    live_stale_vehicle_count: int


class NlqResponse(BaseModel):
    query: str
    intent: str
    route_id: Optional[str] = None
    stop_id: Optional[str] = None
    direction: Optional[str] = None
    parse_source: Literal["claude", "regex", "none"]
    latency_ms: float
