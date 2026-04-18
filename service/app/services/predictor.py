"""Predictor: LightGBM residual + per-route intercept + confidence tier."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

import joblib
import numpy as np
import pandas as pd

from ..config import (
    CONF_HIGH_MAX_HORIZON_S, CONF_HIGH_MIN_ROUTE_SAMPLES, CONF_MEDIUM_MAX_HORIZON_S,
    MODELS_DIR,
)

log = logging.getLogger("bt.predictor")


class Predictor(Protocol):
    model_source: str
    route_support: dict[str, int]

    def predict_correction(self, feature_row: dict) -> float: ...


@dataclass
class RouteIntercepts:
    values: dict[str, float]
    sample_counts: dict[str, int]

    def for_route(self, route_id: Optional[str]) -> float:
        return float(self.values.get(str(route_id), 0.0))


def load_route_intercepts() -> RouteIntercepts:
    p = MODELS_DIR / "route_intercepts.json"
    if not p.exists():
        log.warning("route_intercepts.json missing at %s; using zeros", p)
        return RouteIntercepts(values={}, sample_counts={})
    data = json.loads(p.read_text())
    return RouteIntercepts(
        values={str(k): float(v) for k, v in data.get("route_intercepts_seconds", {}).items()},
        sample_counts={str(k): int(v) for k, v in data.get("computed_from_samples", {}).items()},
    )


class A1Predictor:
    model_source = "a1_lightgbm"

    def __init__(self, bundle: dict, route_support: dict[str, int]):
        self.booster = bundle["booster"]
        self.feature_cols: list[str] = bundle["feature_cols"]
        self.categorical_cols: list[str] = bundle["categorical_cols"]
        self.category_maps: dict[str, list[str]] = bundle["category_maps"]
        self.route_support: dict[str, int] = route_support

    @classmethod
    def from_disk(cls, route_support: dict[str, int]) -> Optional["A1Predictor"]:
        path = MODELS_DIR / "a1_delay_correction.joblib"
        if not path.exists():
            log.error("A1 joblib missing at %s", path)
            return None
        try:
            bundle = joblib.load(path)
            return cls(bundle, route_support)
        except Exception as e:
            log.error("A1 load failed: %s", e, exc_info=True)
            return None

    def predict_correction(self, feature_row: dict) -> float:
        df = pd.DataFrame([feature_row])
        for c in self.categorical_cols:
            cats = self.category_maps.get(c, [])
            df[c] = pd.Categorical(df[c].astype(str), categories=cats)
        df = df[self.feature_cols]
        pred = float(self.booster.predict(df)[0])
        return pred

    def knows_route(self, route_id: Optional[str]) -> bool:
        if not route_id:
            return False
        cats = self.category_maps.get("route_id", [])
        return str(route_id) in cats


class BaselinePredictor:
    model_source = "passthrough"

    def __init__(self, route_support: dict[str, int]):
        self.route_support: dict[str, int] = route_support

    def predict_correction(self, feature_row: dict) -> float:
        return 0.0

    def knows_route(self, route_id: Optional[str]) -> bool:
        return False


def build_predictor() -> tuple[Predictor, RouteIntercepts, dict]:
    """Load metadata to determine abort flag → pick A1 or Baseline. Never raises."""
    intercepts = load_route_intercepts()
    meta_path = MODELS_DIR / "a1_metadata.json"
    metadata: dict = {}
    abort = False
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text())
            abort = bool(metadata.get("aborted", False))
        except Exception as e:
            log.error("a1_metadata.json unreadable: %s", e)
    # per-route training-sample counts (used for A3 confidence tiering)
    route_support = {}
    for r, m in metadata.get("cv", {}).get("oof_per_route", {}).items():
        if isinstance(m, dict) and "n" in m:
            route_support[str(r)] = int(m["n"])

    if abort:
        log.error("A1 aborted per metadata; falling back to Baseline passthrough")
        return BaselinePredictor(route_support), intercepts, metadata

    p = A1Predictor.from_disk(route_support)
    if p is None:
        return BaselinePredictor(route_support), intercepts, metadata
    return p, intercepts, metadata


def combine_correction(
    predictor: Predictor,
    intercepts: RouteIntercepts,
    route_id: Optional[str],
    a1_pred: float,
) -> tuple[float, str]:
    """Return (final_correction_seconds, model_source_applied)."""
    is_baseline = isinstance(predictor, BaselinePredictor)
    if is_baseline:
        return intercepts.for_route(route_id), "a2_intercept"

    # A1 is primary. If A1 trained on this route, trust A1 alone (route_id categorical captured the bias).
    if predictor.knows_route(route_id):  # type: ignore[attr-defined]
        return a1_pred, "a1_lightgbm"
    # Unseen route: fall back to A2 intercept
    return intercepts.for_route(route_id), "a2_intercept"


def confidence_tier(
    predictor: Predictor,
    route_id: Optional[str],
    horizon_s: float,
    has_upstream_trend: bool,
    used_model_source: str,
) -> str:
    n_route = predictor.route_support.get(str(route_id), 0)
    # HIGH: model trained on ≥30 samples for this route AND horizon < 300s AND has upstream data
    if (
        not isinstance(predictor, BaselinePredictor)
        and n_route >= CONF_HIGH_MIN_ROUTE_SAMPLES
        and horizon_s < CONF_HIGH_MAX_HORIZON_S
        and has_upstream_trend
        and used_model_source == "a1_lightgbm"
    ):
        return "high"
    # MEDIUM: ≥30 samples OR we applied an intercept OR horizon < 600s
    if (
        n_route >= CONF_HIGH_MIN_ROUTE_SAMPLES
        or used_model_source == "a2_intercept"
        or horizon_s < CONF_MEDIUM_MAX_HORIZON_S
    ):
        return "medium"
    return "low"
