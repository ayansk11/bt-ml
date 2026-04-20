"""/predictions - per-stop arrivals with scheduled / agency / adjusted ETAs."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from ..config import UTC
from ..models.schemas import (
    PredictionDto, PredictionsResponse, TripEtaTrajectoryResponse, TripStopEtaDto,
)
from ..services.gtfs_helpers import (
    epoch_now, now_utc, scheduled_local_to_utc, service_date_for, time_features_from,
)
from ..services.predictor import combine_correction, confidence_tier

router = APIRouter()


def _trip_delay_lookup(trip_updates_feed) -> dict[str, dict[int, int]]:
    """trip_id → {stop_sequence → arrival.delay (seconds)}; plus a -1 key = trip-level median."""
    out: dict[str, dict[int, int]] = defaultdict(dict)
    if not trip_updates_feed:
        return out
    for e in trip_updates_feed.feed_message.entity:
        if not e.HasField("trip_update"):
            continue
        tu = e.trip_update
        tid = str(tu.trip.trip_id)
        if not tid:
            continue
        delays = []
        for stu in tu.stop_time_update:
            if stu.HasField("arrival"):
                d = int(stu.arrival.delay)
                out[tid][int(stu.stop_sequence)] = d
                delays.append(d)
        if delays:
            # trip-level median (fallback)
            sd = sorted(delays); m = sd[len(sd) // 2]
            out[tid][-1] = int(m)
    return out


def _trip_vehicle_lookup(positions_feed) -> dict[str, dict]:
    """trip_id → {vehicle_id, current_stop_sequence, pos_ts, staleness}"""
    out: dict[str, dict] = {}
    if not positions_feed:
        return out
    now = epoch_now()
    for e in positions_feed.feed_message.entity:
        v = e.vehicle
        tid = str(v.trip.trip_id) if v.trip.trip_id else ""
        if not tid:
            continue
        ts = int(v.timestamp) if v.timestamp else 0
        out[tid] = {
            "vehicle_id": str(v.vehicle.id) if v.vehicle.id else None,
            "current_stop_sequence": int(v.current_stop_sequence) if v.current_stop_sequence else None,
            "pos_ts": ts,
            "staleness_sec": (now - ts) if ts else 9999,
        }
    return out


def _compute_upstream_trend(trip_delays_history_60s_ago: Optional[dict], trip_id: str, current_delay: int) -> tuple[float, bool]:
    """This live service doesn't maintain history; return (0, False). Batch trainer uses real trend."""
    return 0.0, False


def _build_prediction(
    state, trip_id: str, stop_seq: int, stop_id: str, scheduled_utc, bt_delay: int,
    vehicle_info: Optional[dict], horizon_seconds: int,
) -> Optional[PredictionDto]:
    sc = state.static
    predictor = state.predictor
    intercepts = state.intercepts

    trip = sc.trips_by_id.get(trip_id)
    route_id = trip.route_id if trip else None
    route = sc.routes_by_id.get(route_id) if route_id else None
    headsign = trip.headsign if trip else None
    total_stops = sc.total_stops_of(trip_id) or 1

    time_feats = time_features_from(scheduled_utc)
    upstream_trend, has_trend = _compute_upstream_trend(None, trip_id, bt_delay)

    feature_row = {
        **time_feats,
        "route_id": route_id or "",
        "bt_trip_delay_seconds": float(bt_delay),
        "trip_progress_fraction": float(stop_seq) / float(total_stops),
        "stops_remaining": float(total_stops - stop_seq),
        "prediction_horizon_seconds": float(horizon_seconds),
        "upstream_delay_trend_60s": upstream_trend,
        "has_upstream_trend": int(has_trend),
        "route_length_km": float(sc.route_length_km_by_route.get(route_id or "", 0.0)),
        "average_stop_spacing_m": float(sc.avg_stop_spacing_m_by_route.get(route_id or "", 0.0)),
    }

    a1_pred = predictor.predict_correction(feature_row)
    correction, source = combine_correction(predictor, intercepts, route_id, a1_pred)
    conf = confidence_tier(predictor, route_id, horizon_seconds, has_trend, source)

    bt_predicted = scheduled_utc + timedelta(seconds=int(bt_delay))
    ours_predicted = bt_predicted + timedelta(seconds=float(correction))

    return PredictionDto(
        stop_id=stop_id,
        stop_sequence=stop_seq,
        trip_id=trip_id,
        route_id=route_id,
        route_short_name=route.short_name if route else None,
        headsign=headsign,
        vehicle_id=vehicle_info.get("vehicle_id") if vehicle_info else None,
        scheduled_arrival_utc=scheduled_utc.isoformat(),
        bt_delay_seconds=int(bt_delay),
        bt_predicted_arrival_utc=bt_predicted.isoformat(),
        ours_predicted_arrival_utc=ours_predicted.isoformat(),
        correction_seconds=round(float(correction), 1),
        horizon_seconds=int(horizon_seconds),
        confidence=conf,  # type: ignore[arg-type]
        model_source=source,  # type: ignore[arg-type]
        is_realtime=vehicle_info is not None,
    )


@router.get("/predictions", response_model=PredictionsResponse)
def predictions(
    request: Request,
    stop_id: str = Query(..., description="stops.txt stop_id"),
    horizon_minutes: int = Query(30, ge=1, le=180),
) -> PredictionsResponse:
    state = request.app.state
    sc = state.static
    if stop_id not in sc.stops_by_id:
        raise HTTPException(status_code=404, detail=f"stop_id '{stop_id}' not in stops.txt")

    now = now_utc()
    horizon_end = now + timedelta(minutes=horizon_minutes)

    tu_feed = state.rt.trip_updates()
    pos_feed = state.rt.positions()
    trip_delays = _trip_delay_lookup(tu_feed)
    trip_vehicles = _trip_vehicle_lookup(pos_feed)
    feed_header_ts = int(tu_feed.header_timestamp) if tu_feed else 0

    # Service-date (local) at which to evaluate scheduled times.
    # Live active trips may have been scheduled for yesterday (overnight wrap).
    # Simple: use today's local date + try yesterday for HH≥24 handling in `scheduled_local_to_utc`.
    service_date = service_date_for(now)

    preds: list[PredictionDto] = []
    for trip_id, stop_seq in sc.stop_id_to_trip_stops.get(stop_id, []):
        stop_times = sc.stop_times_by_trip.get(trip_id, [])
        # find the StopTimeRow at this seq
        st_row = next((r for r in stop_times if r.stop_sequence == stop_seq and r.stop_id == stop_id), None)
        if not st_row:
            continue
        scheduled_utc = scheduled_local_to_utc(service_date, st_row.arrival_time)
        if scheduled_utc is None:
            continue
        if scheduled_utc < now - timedelta(minutes=1) or scheduled_utc > horizon_end:
            continue

        # BT delay: prefer per-stop entry, else trip-level median, else 0
        delay_map = trip_delays.get(trip_id, {})
        bt_delay = int(delay_map.get(stop_seq, delay_map.get(-1, 0)))

        # Live vehicle?
        veh = trip_vehicles.get(trip_id)
        horizon_s = int((scheduled_utc + timedelta(seconds=bt_delay) - now).total_seconds())
        if horizon_s < 0:
            horizon_s = 0

        p = _build_prediction(state, trip_id, stop_seq, stop_id, scheduled_utc, bt_delay, veh, horizon_s)
        if p:
            preds.append(p)

    preds.sort(key=lambda p: p.ours_predicted_arrival_utc)

    return PredictionsResponse(
        stop_id=stop_id,
        stop_name=sc.stops_by_id[stop_id].name,
        horizon_minutes=horizon_minutes,
        generated_at_utc=now.isoformat(),
        feed_header_ts_utc=(scheduled_local_to_utc(service_date, "00:00:00").replace(tzinfo=None).isoformat() if False else None) or (
            None if not feed_header_ts else
            f"{feed_header_ts}"  # keep simple - epoch seconds string; Android can parse
        ),
        feed_header_age_seconds=int(epoch_now() - feed_header_ts) if feed_header_ts else None,
        predictions=preds,
    )


@router.get("/predictions/trip/{trip_id}", response_model=TripEtaTrajectoryResponse)
def trip_eta(request: Request, trip_id: str) -> TripEtaTrajectoryResponse:
    state = request.app.state
    sc = state.static
    if trip_id not in sc.stop_times_by_trip:
        raise HTTPException(status_code=404, detail=f"trip_id '{trip_id}' not in stop_times.txt")

    now = now_utc()
    service_date = service_date_for(now)
    tu_feed = state.rt.trip_updates()
    pos_feed = state.rt.positions()
    trip_delays = _trip_delay_lookup(tu_feed)
    trip_vehicles = _trip_vehicle_lookup(pos_feed)
    trip = sc.trips_by_id.get(trip_id)
    veh = trip_vehicles.get(trip_id)
    cur_seq = veh.get("current_stop_sequence") if veh else None

    stops_out: list[TripStopEtaDto] = []
    for st in sc.stop_times_by_trip[trip_id]:
        scheduled_utc = scheduled_local_to_utc(service_date, st.arrival_time)
        if scheduled_utc is None:
            continue
        delay_map = trip_delays.get(trip_id, {})
        bt_delay = int(delay_map.get(st.stop_sequence, delay_map.get(-1, 0)))
        horizon_s = max(0, int((scheduled_utc + timedelta(seconds=bt_delay) - now).total_seconds()))
        p = _build_prediction(state, trip_id, st.stop_sequence, st.stop_id, scheduled_utc, bt_delay, veh, horizon_s)
        if not p:
            continue
        stops_out.append(TripStopEtaDto(
            stop_id=p.stop_id,
            stop_sequence=p.stop_sequence,
            stop_name=sc.stops_by_id.get(p.stop_id).name if p.stop_id in sc.stops_by_id else None,
            scheduled_arrival_utc=p.scheduled_arrival_utc,
            bt_predicted_arrival_utc=p.bt_predicted_arrival_utc,
            ours_predicted_arrival_utc=p.ours_predicted_arrival_utc,
            correction_seconds=p.correction_seconds,
            confidence=p.confidence,
        ))

    return TripEtaTrajectoryResponse(
        trip_id=trip_id,
        route_id=trip.route_id if trip else None,
        vehicle_id=veh.get("vehicle_id") if veh else None,
        current_stop_sequence=cur_seq,
        generated_at_utc=now.isoformat(),
        stops=stops_out,
    )
