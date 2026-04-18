"""POST/GET /nlq — natural language query (C2 stretch).

Regex-based intent parser. Never raises to the caller.

Supported intents returned in `intent`:
  - next_on_route       — "next 6", "when does 3E come", "when is the next 9"
  - stop_search         — "bus to <name>", "[name] stop"
  - show_route          — "route 6", "show 3E"
  - unknown             — no match
"""
from __future__ import annotations

import re
import time
from typing import Optional

from fastapi import APIRouter, Query

from ..models.schemas import NlqResponse

router = APIRouter()

# Regexes  ------------------------------------------------------------------
# Route pattern: at least one digit, optional trailing letter (e.g. 6, 3E, 4W, 11)
_ROUTE_TOKEN = r"[0-9]+[A-Za-z]?"
_RE_NEXT_ROUTE = re.compile(
    rf"(?:next|when\s+(?:does|is)|when's)\s+(?:the\s+)?(?:next\s+)?(?:bus\s+)?(?:route\s+)?\b({_ROUTE_TOKEN})\b",
    re.IGNORECASE,
)
_RE_SHOW_ROUTE = re.compile(
    rf"(?:route|line)\s+\b({_ROUTE_TOKEN})\b",
    re.IGNORECASE,
)
_RE_BUS_TO = re.compile(r"(?:bus\s+)?to\s+(.+)", re.IGNORECASE)


def _canonical_route(token: str) -> str:
    return token.strip().upper()


def _regex_parse(q: str) -> Optional[dict]:
    q = q.strip()
    if not q:
        return None
    m = _RE_NEXT_ROUTE.search(q)
    if m:
        return {"intent": "next_on_route", "route_id": _canonical_route(m.group(1))}
    m = _RE_SHOW_ROUTE.search(q)
    if m:
        return {"intent": "show_route", "route_id": _canonical_route(m.group(1))}
    m = _RE_BUS_TO.search(q)
    if m:
        tail = m.group(1).strip(" .?!")
        if tail:
            return {"intent": "stop_search", "stop_id": None, "direction": None, "stop_query": tail}
    # standalone "6" / "3E" → show_route
    if re.fullmatch(_ROUTE_TOKEN, q, re.IGNORECASE):
        return {"intent": "show_route", "route_id": _canonical_route(q)}
    return None


@router.get("/nlq", response_model=NlqResponse)
def nlq(q: str = Query(..., description="natural language query")) -> NlqResponse:
    t0 = time.perf_counter()
    regex_hit = _regex_parse(q)
    if regex_hit:
        return NlqResponse(
            query=q,
            intent=str(regex_hit.get("intent", "unknown")),
            route_id=regex_hit.get("route_id"),
            stop_id=regex_hit.get("stop_id"),
            direction=regex_hit.get("direction"),
            parse_source="regex",
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

    return NlqResponse(
        query=q,
        intent="unknown",
        parse_source="none",
        latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
    )
