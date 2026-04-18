"""/nlq — parse short natural-language transit queries into intents."""
from __future__ import annotations

import os
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


def _claude_parse(q: str) -> Optional[dict]:
    """Optional Claude-API fallback. Returns None on any error / missing key.
    Never raises; fails loud in logs (caller wraps).
    Enforces 800ms timeout via anthropic client timeout kwarg.
    """
    import logging
    log = logging.getLogger("bt.nlq")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=0.8)
        system = (
            "You parse short English queries about a US city bus app. Output STRICT JSON only, no prose, "
            "matching this schema: {intent: 'next_on_route'|'show_route'|'stop_search'|'unknown', "
            "route_id?: string, stop_query?: string, direction?: string}. "
            "Routes are alphanumeric like '6', '3E', '4W'."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            system=system,
            messages=[{"role": "user", "content": q}],
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        import json
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "intent" in parsed:
            return parsed
    except Exception as e:
        log.warning("Claude nlq fallback failed: %s", e)
        return None
    return None


@router.get("/nlq", response_model=NlqResponse)
def nlq(q: str = Query(..., description="natural language query")) -> NlqResponse:
    t0 = time.perf_counter()
    # Regex first — always on, <1ms
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

    # Claude fallback
    claude_hit = _claude_parse(q)
    if claude_hit:
        return NlqResponse(
            query=q,
            intent=str(claude_hit.get("intent", "unknown")),
            route_id=claude_hit.get("route_id"),
            stop_id=claude_hit.get("stop_id"),
            direction=claude_hit.get("direction"),
            parse_source="claude",
            latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
        )

    return NlqResponse(
        query=q,
        intent="unknown",
        parse_source="none",
        latency_ms=round((time.perf_counter() - t0) * 1000.0, 2),
    )
