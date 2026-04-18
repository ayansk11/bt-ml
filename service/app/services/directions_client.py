"""Async Google Directions client with a small in-memory TTL cache."""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

log = logging.getLogger("bt.directions")

GOOGLE_URL = "https://maps.googleapis.com/maps/api/directions/json"
CACHE_TTL_SEC = 60        # brief — transit schedules shift with the hour
CACHE_MAX_ENTRIES = 512
ROUND_DP = 4              # ~11m precision at Bloomington latitudes


@dataclass
class _Entry:
    payload: dict
    stored_at: float


class DirectionsClient:
    """Singleton — instantiated once by main.py at startup, closed at shutdown."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        # Tight but forgiving pool. max_keepalive_connections > max_connections
        # would be wrong; keep them equal so httpx reuses sockets aggressively.
        limits = httpx.Limits(
            max_connections=16,
            max_keepalive_connections=16,
            keepalive_expiry=60.0,
        )
        timeout = httpx.Timeout(connect=3.0, read=6.0, write=3.0, pool=2.0)
        self._client = httpx.AsyncClient(
            http2=True,
            limits=limits,
            timeout=timeout,
            headers={"User-Agent": "bt-ml/0.1"},
        )
        self._cache: dict[tuple, _Entry] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def _cache_key(self, origin: tuple[float, float], dest: tuple[float, float], mode: str, departure_time: Optional[int]) -> tuple:
        return (
            round(origin[0], ROUND_DP), round(origin[1], ROUND_DP),
            round(dest[0], ROUND_DP), round(dest[1], ROUND_DP),
            mode,
            # bucket departure_time by minute so "now" requests within 60s hit cache
            (departure_time // 60) if departure_time else "now",
        )

    def _trim_cache(self) -> None:
        if len(self._cache) <= CACHE_MAX_ENTRIES:
            return
        # drop oldest half
        ordered = sorted(self._cache.items(), key=lambda kv: kv[1].stored_at)
        for k, _ in ordered[: len(ordered) // 2]:
            self._cache.pop(k, None)

    async def plan(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        mode: str = "transit",
        departure_time: Optional[int] = None,
        alternatives: bool = True,
    ) -> tuple[dict, dict]:
        """Returns (payload, meta) where meta carries {cache_hit, latency_ms, upstream_status}."""
        t0 = time.perf_counter()
        key = self._cache_key(origin, dest, mode, departure_time)

        cached = self._cache.get(key)
        if cached and (time.time() - cached.stored_at) < CACHE_TTL_SEC:
            return cached.payload, {
                "cache_hit": True,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "upstream_status": "cached",
            }

        params: dict[str, Any] = {
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{dest[0]},{dest[1]}",
            "mode": mode,
            "alternatives": "true" if alternatives else "false",
            "key": self.api_key,
        }
        if departure_time:
            params["departure_time"] = str(departure_time)
        else:
            params["departure_time"] = "now"

        try:
            r = await self._client.get(GOOGLE_URL, params=params)
            upstream_status = str(r.status_code)
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            log.warning("Directions upstream error: %s", e)
            return {}, {
                "cache_hit": False,
                "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "upstream_status": f"error: {type(e).__name__}",
            }

        status = payload.get("status", "UNKNOWN")
        if status not in ("OK", "ZERO_RESULTS"):
            log.warning("Directions non-OK status: %s %s", status, payload.get("error_message"))

        # Only cache OK / ZERO_RESULTS
        if status in ("OK", "ZERO_RESULTS"):
            self._cache[key] = _Entry(payload=payload, stored_at=time.time())
            self._trim_cache()

        return payload, {
            "cache_hit": False,
            "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "upstream_status": upstream_status,
        }
