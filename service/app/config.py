"""Service config + constants."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
MODELS_DIR = Path(os.environ.get("MODELS_DIR", ROOT / "models"))
STATIC_DIR = Path(os.environ.get("STATIC_DIR", ROOT / "data" / "gtfs_static"))

BT_BASE = "https://s3.amazonaws.com/etatransit.gtfs/bloomingtontransit.etaspot.net"
POSITIONS_URL = f"{BT_BASE}/position_updates.pb"
TRIP_UPDATES_URL = f"{BT_BASE}/trip_updates.pb"
ALERTS_URL = f"{BT_BASE}/alerts.pb"
STATIC_URL = f"{BT_BASE}/gtfs.zip"

AGENCY_TZ = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

# Cache TTLs
RT_CACHE_TTL_SEC = 5  # we poll ourselves every <=5s; feed publishes ~10s cadence

# A3 confidence thresholds
CONF_HIGH_MIN_ROUTE_SAMPLES = 30
CONF_HIGH_MAX_HORIZON_S = 300
CONF_MEDIUM_MAX_HORIZON_S = 600

# Bunching
BUNCHING_RADIUS_M = 200.0

# Stale vehicle threshold
STALE_VEHICLE_SEC = 90

# Bloomington bbox sanity
BBOX = dict(lat_min=39.08, lat_max=39.25, lon_min=-86.60, lon_max=-86.43)

BT_HEADLINE_MAE = 94.3  # from BASELINE_REPORT
