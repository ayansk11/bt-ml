"""Thin cached fetcher for the three GTFS-RT `.pb` feeds.

In-process TTL cache so we don't hammer S3 per request.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests
from google.transit import gtfs_realtime_pb2

from ..config import ALERTS_URL, POSITIONS_URL, RT_CACHE_TTL_SEC, TRIP_UPDATES_URL


@dataclass
class CachedFeed:
    feed_message: object
    fetched_at: float
    header_timestamp: int
    content_bytes: int


class GtfsRealtimeClient:
    def __init__(self) -> None:
        self._cache: dict[str, CachedFeed] = {}

    def _fetch(self, url: str) -> Optional[CachedFeed]:
        now = time.time()
        cached = self._cache.get(url)
        if cached and (now - cached.fetched_at) < RT_CACHE_TTL_SEC:
            return cached
        try:
            r = requests.get(url, timeout=10.0,
                             headers={"User-Agent": "bt-ml/0.1 (+hackathon)"})
            if r.status_code != 200 or not r.content:
                return cached  # keep stale on failure
            feed = gtfs_realtime_pb2.FeedMessage()
            feed.ParseFromString(r.content)
            cf = CachedFeed(
                feed_message=feed,
                fetched_at=now,
                header_timestamp=int(feed.header.timestamp) if feed.header.timestamp else 0,
                content_bytes=len(r.content),
            )
            self._cache[url] = cf
            return cf
        except Exception:
            return cached

    def positions(self) -> Optional[CachedFeed]:
        return self._fetch(POSITIONS_URL)

    def trip_updates(self) -> Optional[CachedFeed]:
        return self._fetch(TRIP_UPDATES_URL)

    def alerts(self) -> Optional[CachedFeed]:
        return self._fetch(ALERTS_URL)
