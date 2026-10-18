"""Unit tests for sticky recommend + phase deadband (importlib to avoid package __init__)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


thresholds = _load("thresholds_ut", "backend/decision/thresholds.py")
# recommend imports thresholds via package path — load with patched sys.modules
import sys
import types

# Minimal fake package tree so recommend can `from backend.decision.thresholds import ...`
backend_pkg = types.ModuleType("backend")
backend_pkg.__path__ = [str(ROOT / "backend")]
decision_pkg = types.ModuleType("backend.decision")
decision_pkg.__path__ = [str(ROOT / "backend/decision")]
sys.modules.setdefault("backend", backend_pkg)
sys.modules["backend.decision"] = decision_pkg
sys.modules["backend.decision.thresholds"] = thresholds

recommend = _load("recommend_ut", "backend/decision/recommend.py")

# market_signals needs backend.decision.thresholds for deadband helpers
analysis_pkg = types.ModuleType("backend.analysis")
analysis_pkg.__path__ = [str(ROOT / "backend/analysis")]
sys.modules["backend.analysis"] = analysis_pkg

# Provide lightweight config stub used by market_signals
config = types.ModuleType("backend.config")
config.INDIA_VIX_SYMBOL = "INDIAVIX"
config.DEFAULT_START_DATE = "2005-01-01"
sys.modules["backend.config"] = config

cache_mod = types.ModuleType("backend.data.cache_manager")


class CacheManager:  # noqa: D101
    pass


cache_mod.CacheManager = CacheManager
data_pkg = types.ModuleType("backend.data")
data_pkg.__path__ = [str(ROOT / "backend/data")]
sys.modules["backend.data"] = data_pkg
sys.modules["backend.data.cache_manager"] = cache_mod

market_signals = _load("market_signals_ut", "backend/analysis/market_signals.py")

is_sticky_recommended = recommend.is_sticky_recommended
EXIT_SCORE = thresholds.EXIT_SCORE
RECOMMEND_ENTER = thresholds.RECOMMEND_ENTER
MarketSignals = market_signals.MarketSignals


def test_sticky_enter_requires_clearance_or_streak():
    assert is_sticky_recommended(61.0, was_recommended=False) is False
    assert is_sticky_recommended(RECOMMEND_ENTER, was_recommended=False) is True
    assert (
        is_sticky_recommended(61.0, prev_scores=[61.0], was_recommended=False) is True
    )


def test_sticky_exit_band():
    assert is_sticky_recommended(56.0, was_recommended=True) is True
    assert is_sticky_recommended(EXIT_SCORE, was_recommended=True) is True
    assert is_sticky_recommended(EXIT_SCORE - 0.5, was_recommended=True) is False


def test_phase_deadband_holds_early():
    phase, sub = MarketSignals._phase_with_deadband(0.95, "early_expansion")
    assert phase == "expansion"
    assert sub == "early_expansion"
    _p, sub2 = MarketSignals._phase_with_deadband(0.5, "early_expansion")
    assert sub2 == "late_expansion"


def test_phase_deadband_needs_clearance_to_enter_early():
    _p, sub = MarketSignals._phase_with_deadband(1.05, "late_expansion")
    assert sub == "late_expansion"
    _p2, sub2 = MarketSignals._phase_with_deadband(1.2, "late_expansion")
    assert sub2 == "early_expansion"


def test_soft_sub_phase_fit_is_continuous():
    early = MarketSignals._soft_sub_phase_fit(1.2, "early_expansion")
    late = MarketSignals._soft_sub_phase_fit(0.6, "late_expansion")
    mid = MarketSignals._soft_sub_phase_fit(0.6, "early_expansion")
    assert early > mid
    assert 0 < late <= 1.0
