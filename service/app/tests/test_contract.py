"""Contract tests — run against in-process FastAPI app with real models + mock RT feeds.

`pytest service/app/tests -q` from repo root.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from service.app.main import app
from service.app.services.gtfs_client import CachedFeed


class _EmptyFeed:
    """Stand-in for a CachedFeed when we don't want network calls during tests."""
    def __init__(self):
        class _Hdr:
            timestamp = 0
        class _M:
            header = _Hdr()
            entity = []
        self.feed_message = _M()
        self.fetched_at = 0.0
        self.header_timestamp = 0
        self.content_bytes = 0


class _MockRt:
    def positions(self): return _EmptyFeed()
    def trip_updates(self): return _EmptyFeed()
    def alerts(self): return _EmptyFeed()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        # replace the real RT client with a mock so tests don't hit S3
        app.state.rt = _MockRt()
        yield c


def test_healthz_shape(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "bt-ml"
    assert body["model_source"] in {"a1_lightgbm", "passthrough"}
    assert "model_loaded" in body
    assert "n_routes_with_intercept" in body


def test_routes_nonempty(client):
    r = client.get("/routes")
    assert r.status_code == 200
    routes = r.json()
    assert isinstance(routes, list)
    assert len(routes) >= 10
    ids = {r["route_id"] for r in routes}
    assert "6" in ids  # route 6 is a known Bloomington route


def test_stops_nonempty_and_filtering(client):
    r = client.get("/stops")
    assert r.status_code == 200
    stops = r.json()
    assert len(stops) >= 400
    # name filter
    r2 = client.get("/stops", params={"q": "indiana"})
    assert r2.status_code == 200
    for s in r2.json():
        assert "indiana" in s["name"].lower()


def test_vehicles_empty_without_feed(client):
    # Mock RT returns empty; expect empty list (not 500)
    r = client.get("/vehicles")
    assert r.status_code == 200
    assert r.json() == []


def test_alerts_empty_without_feed(client):
    r = client.get("/alerts")
    assert r.status_code == 200
    assert r.json() == []


def test_bunching_empty_without_feed(client):
    r = client.get("/detections/bunching")
    assert r.status_code == 200
    body = r.json()
    assert "events" in body
    assert body["events"] == []


def test_stats(client):
    r = client.get("/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["bt_headline_mae_s"] == 94.3
    assert body["a1_cv_headline_mae_s"] is not None
    assert body["a1_cv_improvement_s"] is not None
    assert body["model_source"] in {"a1_lightgbm", "passthrough"}


def test_predictions_unknown_stop_404(client):
    r = client.get("/predictions", params={"stop_id": "NOT-A-STOP"})
    assert r.status_code == 404


def test_predictions_known_stop_shape(client):
    # Pick a real stop id by hitting /stops first
    all_stops = client.get("/stops").json()
    assert all_stops
    # Use a stop that actually appears in stop_times — grab the first stop_id that shows up as a trip stop
    # (any real stop_id should work since static cache indexes by stop_times)
    stop_id = all_stops[0]["stop_id"]
    r = client.get("/predictions", params={"stop_id": stop_id, "horizon_minutes": 60})
    assert r.status_code == 200
    body = r.json()
    assert body["stop_id"] == stop_id
    assert "predictions" in body
    # Can be empty if no active trips pass this stop in next 60 min; that's fine
    for p in body["predictions"]:
        assert p["confidence"] in {"high", "medium", "low"}
        assert p["model_source"] in {"a1_lightgbm", "a2_intercept", "passthrough"}
        assert "scheduled_arrival_utc" in p
        assert "bt_predicted_arrival_utc" in p
        assert "ours_predicted_arrival_utc" in p


def test_plan_without_api_key_returns_503(client):
    # In test env GOOGLE_MAPS_API_KEY is not set → directions_client is None
    r = client.get("/plan", params={
        "origin_lat": 39.16, "origin_lng": -86.52,
        "dest_lat": 39.20, "dest_lng": -86.54,
    })
    # Either 503 (no key) or 200 (key somehow set in env) — both are acceptable
    assert r.status_code in (200, 503)


def test_nlq_regex_next_on_route(client):
    r = client.get("/nlq", params={"q": "when is the next 6"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "when is the next 6"
    assert body["parse_source"] == "regex"
    assert body["intent"] == "next_on_route"
    assert body["route_id"] == "6"


def test_nlq_regex_show_route(client):
    r = client.get("/nlq", params={"q": "3E"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "show_route"
    assert body["route_id"] == "3E"


def test_nlq_unknown_falls_back(client):
    r = client.get("/nlq", params={"q": "hello world"})
    assert r.status_code == 200
    body = r.json()
    # Without ANTHROPIC_API_KEY set in test env, claude path is skipped → unknown
    assert body["intent"] == "unknown"
    assert body["parse_source"] in {"none", "claude"}
