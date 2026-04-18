"""Shared helpers for time conversion + feature extraction from live feeds."""
from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from ..config import AGENCY_TZ, UTC


def scheduled_local_to_utc(service_date: date, arrival_time_str: str) -> Optional[datetime]:
    """GTFS 'HH:MM:SS' (HH may be ≥24) + service_date (local) → tz-aware UTC datetime."""
    try:
        h, m, s = (int(x) for x in arrival_time_str.split(":"))
    except Exception:
        return None
    days_over, h_mod = divmod(h, 24)
    naive = datetime.combine(service_date, time(h_mod, m, s)) + timedelta(days=days_over)
    local = naive.replace(tzinfo=AGENCY_TZ)
    return local.astimezone(UTC)


def now_utc() -> datetime:
    return datetime.now(UTC)


def epoch_now() -> int:
    return int(now_utc().timestamp())


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1); phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1); dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def service_date_for(ts_utc: datetime) -> date:
    """Local date in agency TZ for picking the scheduled arrival day."""
    return ts_utc.astimezone(AGENCY_TZ).date()


def time_features_from(ts_utc: datetime) -> dict:
    local = ts_utc.astimezone(AGENCY_TZ)
    return {
        "hour_of_day": int(local.hour),
        "minute_of_hour": int(local.minute),
        "day_of_week": int(local.weekday()),
        "is_weekend": int(local.weekday() >= 5),
    }
