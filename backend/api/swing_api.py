"""Swing strategy API — Groww-history backtest + dry-run multi-approach scan."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/swing", tags=["swing"])

PARAMS_PATH = (
    Path(__file__).resolve().parents[2] / "strategies" / "groww_swing" / "params.json"
)

# Background Groww cache job (Next proxy times out on sync multi-symbol fetch)
_cache_lock = threading.Lock()
_cache_job: Dict[str, Any] = {
    "status": "idle",  # idle | running | done | error
    "message": "",
    "current": 0,
    "total": 0,
    "symbol": "",
    "sectors": 0,
    "symbols": 0,
    "full_history": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
}

_eval_lock = threading.Lock()
_eval_job: Dict[str, Any] = {
    "status": "idle",  # idle | running | done | error
    "message": "",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "result": None,
}


class BacktestRequest(BaseModel):
    capital: float = Field(100_000.0, gt=0)
    n_days: int = Field(160, ge=120, le=500)
    seed: int = 42
    quick: bool = True
    demo: bool = False  # force synthetic
    refresh_cache: bool = False  # ignored on backtest — use /cache/refresh
    enabled_approaches: Optional[List[str]] = None
    include_baseline: bool = False  # dual backtest is slow; off by default for UI


class ParamsUpdate(BaseModel):
    enabled_approaches: Optional[List[str]] = None


def _load_params() -> Dict[str, Any]:
    from strategies.groww_swing.backtest import load_params

    return load_params(PARAMS_PATH)


def _save_params(params: Dict[str, Any]) -> Dict[str, Any]:
    import json

    with open(PARAMS_PATH, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2)
        f.write("\n")
    return params


def _groww_configured() -> bool:
    return bool(
        os.getenv("GROWW_ACCESS_TOKEN")
        or (
            os.getenv("GROWW_API_KEY")
            and (os.getenv("GROWW_API_SECRET") or os.getenv("GROWW_TOTP_SECRET"))
        )
    )


def _cache_snapshot() -> Dict[str, Any]:
    with _cache_lock:
        return dict(_cache_job)


def _eval_snapshot() -> Dict[str, Any]:
    with _eval_lock:
        return dict(_eval_job)


@router.get("/status")
def swing_status() -> Dict[str, Any]:
    from strategies.groww_swing.catalog import ALL_APPROACH_IDS, APPROACH_META, resolve_enabled
    from strategies.groww_swing.panel_cache import cache_history_summary, cache_is_usable

    params = _load_params()
    hist = cache_history_summary()
    return {
        "groww_configured": _groww_configured(),
        "dry_run_default": bool(params.get("dry_run", True)),
        "params_path": str(PARAMS_PATH),
        "enabled_approaches": resolve_enabled(params),
        "approaches": [
            {"id": aid, **APPROACH_META[aid]} for aid in ALL_APPROACH_IDS
        ],
        "cache_ready": cache_is_usable(),
        "cache_history": hist,
        "cache_job": _cache_snapshot(),
        "eval_job": _eval_snapshot(),
        "calibration": params.get("calibration"),
        "cloud_hint": (
            "Deploy strategies/groww_swing on Groww Cloud (see DEPLOY.md). "
            "Pulse UI is dry-run only. Quick backtest is smoke; use Full eval for real numbers. "
            "Groww daily history from ~2020 only — not 20y; 15m is not the primary swing bar."
        ),
    }


@router.get("/params")
def swing_params() -> Dict[str, Any]:
    return _load_params()


@router.patch("/params")
def swing_params_update(body: ParamsUpdate) -> Dict[str, Any]:
    from strategies.groww_swing.catalog import ALL_APPROACH_IDS, normalize_approach_id

    params = _load_params()
    if body.enabled_approaches is not None:
        cleaned = []
        for item in body.enabled_approaches:
            aid = normalize_approach_id(str(item))
            if aid in ALL_APPROACH_IDS and aid not in cleaned:
                cleaned.append(aid)
        if not cleaned:
            raise HTTPException(status_code=400, detail="Need at least one approach")
        params["enabled_approaches"] = cleaned
    return _save_params(params)


def _resolve_panels(body: BacktestRequest) -> tuple:
    """Use Groww disk cache if present; never block the HTTP request on live fetches."""
    from strategies.groww_swing.backtest import synthetic_demo_data
    from strategies.groww_swing.panel_cache import (
        cache_is_usable,
        load_cached_backtest_panels,
    )

    if body.demo:
        sectors, symbols = synthetic_demo_data(n_days=body.n_days, seed=body.seed)
        return sectors, symbols, None, "synthetic"

    if cache_is_usable():
        sectors, symbols, bench = load_cached_backtest_panels()
        return sectors, symbols, bench, "groww_cache"

    # No cache yet — synthetic fast path (UI should kick off /cache/refresh in background)
    sectors, symbols = synthetic_demo_data(n_days=body.n_days, seed=body.seed)
    return sectors, symbols, None, "synthetic"


def _empty_baseline(capital: float) -> Any:
    from strategies.groww_swing.backtest import BacktestResult

    return BacktestResult(
        starting_capital=capital,
        ending_capital=capital,
        with_cycle_filter=False,
    )


@router.post("/backtest")
def swing_backtest(body: BacktestRequest) -> Dict[str, Any]:
    try:
        from strategies.groww_swing.backtest import (
            export_calibrated_params,
            run_swing_backtest,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Swing package import failed: {exc}") from exc

    params = _load_params()
    if body.enabled_approaches:
        params = dict(params)
        params["enabled_approaches"] = body.enabled_approaches

    sectors, symbols, bench, mode = _resolve_panels(body)
    # Keep under Next.js rewrite proxy timeout (~30s)
    rebalance = 10 if body.quick else 2
    n_days = min(body.n_days, 180) if body.quick else body.n_days
    kwargs: Dict[str, Any] = {
        "capital": body.capital,
        "params": params,
        "rebalance_every_n_days": rebalance,
    }
    if bench is not None:
        kwargs["benchmark"] = bench

    # Trim series length for quick mode (cache frames may be long)
    if body.quick and mode == "groww_cache":
        sectors = {
            k: v.tail(n_days + 40) if hasattr(v, "tail") else v for k, v in sectors.items()
        }
        symbols = {
            k: v.tail(n_days + 40) if hasattr(v, "tail") else v for k, v in symbols.items()
        }
        if bench is not None and hasattr(bench, "tail"):
            kwargs["benchmark"] = bench.tail(n_days + 40)

    t0 = time.time()
    try:
        filtered = run_swing_backtest(
            sectors, symbols, use_cycle_filter=True, **kwargs
        )
        if body.include_baseline and (time.time() - t0) < 12:
            baseline = run_swing_backtest(
                sectors, symbols, use_cycle_filter=False, **kwargs
            )
            baseline_skipped = False
        else:
            baseline = _empty_baseline(body.capital)
            baseline_skipped = True
        if mode == "groww_cache":
            export_calibrated_params(filtered, path=PARAMS_PATH, base_params=_load_params())
    except Exception as exc:
        logger.exception("Swing backtest failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    elapsed = round(time.time() - t0, 2)

    def _summary(r: Any) -> Dict[str, Any]:
        return {
            "total_return_pct": r.total_return_pct,
            "win_rate": r.win_rate,
            "expectancy_r": r.expectancy_r,
            "max_drawdown_pct": r.max_drawdown_pct,
            "num_trades": r.num_trades,
            "ending_capital": r.ending_capital,
            "approach_stats": getattr(r, "approach_stats", {}) or {},
            "equity_curve": r.equity_curve[-60:],
            "recent_trades": [
                {
                    "symbol": t.symbol,
                    "sector": t.sector,
                    "setup": t.setup,
                    "entry_date": t.entry_date,
                    "exit_date": t.exit_date,
                    "entry": t.entry,
                    "exit": t.exit,
                    "pnl": t.pnl,
                    "r_multiple": t.r_multiple,
                    "exit_reason": t.exit_reason,
                }
                for t in r.trades[-12:]
            ],
        }

    note = (
        "Quick smoke on Groww cache (trimmed) — use Full eval for promotion numbers"
        if mode == "groww_cache"
        else "Synthetic smoke — refresh full Groww daily cache (~2020→now) for real history"
    )
    if mode == "synthetic" and _groww_configured():
        note += " (cache empty)"

    out = {
        "mode": mode,
        "n_days": n_days,
        "elapsed_s": elapsed,
        "enabled_approaches": params.get("enabled_approaches"),
        "with_cycle_filter": _summary(filtered),
        "baseline_technicals_only": _summary(baseline),
        "cycle_edge_return_pct": round(
            filtered.total_return_pct - baseline.total_return_pct, 2
        ),
        "cycle_edge_expectancy_r": round(
            filtered.expectancy_r - baseline.expectancy_r, 3
        ),
        "params": _load_params(),
        "note": note,
        "cache_ready": mode == "groww_cache",
    }
    if baseline_skipped:
        out["baseline_note"] = "Baseline skipped (quick mode) — keeps response under proxy timeout"
    return out


def _attach_research_to_scan(result: Dict[str, Any], sector_data: Optional[Dict] = None) -> Dict[str, Any]:
    """Optional lightweight HMM only — not the product surface."""
    frames = sector_data or result.pop("_sector_frames", None)
    result.pop("_sector_frames", None)

    if not frames:
        return result

    try:
        import pandas as pd
        from strategies.research.features.feature_store import build_macro_feature_frame
        from strategies.research.models.regime_hmm import (
            fit_regime_hmm,
            size_multiplier_from_posterior,
        )

        closes = pd.DataFrame(
            {
                k: (v["close"] if "close" in v.columns else v.iloc[:, 0])
                for k, v in frames.items()
                if v is not None and not getattr(v, "empty", True)
            }
        )
        if closes.shape[1] < 3 or len(closes) < 40:
            return result

        macro = build_macro_feature_frame(closes).dropna()
        if len(macro) < 40:
            return result

        _, post = fit_regime_hmm(macro, n_states=2)
        p_exp = float(post["p_expansion"].iloc[-1])
        result["regime_hmm"] = {
            "p_expansion": round(p_exp, 4),
            "p_contraction": round(1 - p_exp, 4),
            "size_multiplier": round(size_multiplier_from_posterior(p_exp), 4),
        }
    except Exception as exc:
        logger.warning("HMM attach skipped: %s", exc)
    return result


@router.post("/scan")
def swing_scan(demo: bool = False) -> Dict[str, Any]:
    params = dict(_load_params())
    params["dry_run"] = True

    use_demo = demo or not _groww_configured()
    if use_demo:
        return _demo_scan(params)

    try:
        from strategies.groww_swing.main import run_once
        from strategies.groww_swing.broker import GrowwBroker
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    try:
        broker = GrowwBroker(dry_run=True)
        result = run_once(broker=broker, params=params)
        result["mode"] = "groww_dry_run"
        return _attach_research_to_scan(result)
    except Exception as exc:
        logger.warning("Groww scan failed, falling back to demo: %s", exc)
        out = _demo_scan(params)
        out["groww_error"] = str(exc)
        return out


def _demo_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    from strategies.groww_swing.backtest import synthetic_demo_data
    from strategies.groww_swing.cycle_filter import compute_cycle_bias
    from strategies.groww_swing.regime_router import router_snapshot
    from strategies.groww_swing.risk import filter_and_size
    from strategies.groww_swing.setups import scan_universe
    from strategies.groww_swing.universe import sector_for_symbol

    sectors, symbols = synthetic_demo_data(n_days=260, seed=3)
    bias = compute_cycle_bias(sectors, vix_value=16.0, params=params)
    symbol_sector = {s: sector_for_symbol(s) or "" for s in symbols}
    setups = scan_universe(
        symbols,
        symbol_sector=symbol_sector,
        params=params,
        bias=bias,
    )
    sized = filter_and_size(setups, capital=100_000.0, params=params)
    out = {
        "mode": "demo",
        "message": "Demo scan (synthetic). Configure Groww env for live dry-run candles.",
        "dry_run": True,
        "bias": {
            k: bias[k]
            for k in (
                "phase",
                "sub_phase",
                "score",
                "progress",
                "allowed_sectors",
                "risk_off",
                "reason",
                "sector_scores",
                "favored_sectors",
            )
            if k in bias
        },
        "router": router_snapshot(bias, params),
        "setups": setups,
        "sized": sized,
        "orders": [],
        "capital": 100_000.0,
    }
    return _attach_research_to_scan(out, sector_data=sectors)


def _run_cache_job(days: int, full_history: bool) -> None:
    global _cache_job
    try:
        from strategies.groww_swing.broker import GrowwBroker
        from strategies.groww_swing.panel_cache import (
            build_sector_and_symbol_panels,
            read_manifest,
        )

        def progress(i: int, total: int, sym: str) -> None:
            with _cache_lock:
                _cache_job["current"] = i
                _cache_job["total"] = total
                _cache_job["symbol"] = sym
                mode = "full ~2020→now" if full_history else f"{days}d"
                _cache_job["message"] = f"Fetching {sym} ({i}/{total}) [{mode}]"

        broker = GrowwBroker(dry_run=True)
        sectors, symbols = build_sector_and_symbol_panels(
            broker,
            days=days,
            force=True,
            primary_only=True,
            full_history=full_history,
            progress=progress,
        )
        manifest = read_manifest()
        with _cache_lock:
            _cache_job.update(
                {
                    "status": "done",
                    "message": (
                        f"Cached {len(symbols)} symbols / {len(sectors)} sectors "
                        f"({manifest.get('history_start')} → {manifest.get('history_end')})"
                    ),
                    "sectors": len(sectors),
                    "symbols": len(symbols),
                    "full_history": full_history,
                    "manifest": manifest,
                    "finished_at": time.time(),
                    "error": None,
                }
            )
    except Exception as exc:
        logger.exception("Cache refresh failed")
        with _cache_lock:
            _cache_job.update(
                {
                    "status": "error",
                    "message": str(exc),
                    "error": str(exc),
                    "finished_at": time.time(),
                }
            )


@router.post("/cache/refresh")
def swing_cache_refresh(
    days: int = 400,
    full_history: bool = True,
) -> Dict[str, Any]:
    """Start Groww daily history fetch in background (default: full ~2020→now)."""
    if not _groww_configured():
        raise HTTPException(status_code=400, detail="Groww credentials required")

    with _cache_lock:
        if _cache_job.get("status") == "running":
            return {
                "started": False,
                "message": "Cache refresh already running",
                "cache_job": dict(_cache_job),
            }
        _cache_job.update(
            {
                "status": "running",
                "message": (
                    "Starting full Groww daily fetch (~2020→now)…"
                    if full_history
                    else f"Starting Groww fetch ({days}d)…"
                ),
                "current": 0,
                "total": 0,
                "symbol": "",
                "sectors": 0,
                "symbols": 0,
                "full_history": full_history,
                "started_at": time.time(),
                "finished_at": None,
                "error": None,
            }
        )

    thread = threading.Thread(
        target=_run_cache_job,
        args=(days, full_history),
        daemon=True,
        name="groww-cache-refresh",
    )
    thread.start()
    return {
        "started": True,
        "message": "Cache refresh started in background — poll /api/swing/status",
        "full_history": full_history,
        "cache_job": _cache_snapshot(),
    }


@router.get("/cache/status")
def swing_cache_status() -> Dict[str, Any]:
    from strategies.groww_swing.panel_cache import cache_history_summary, cache_is_usable

    return {
        "cache_ready": cache_is_usable(),
        "cache_history": cache_history_summary(),
        "cache_job": _cache_snapshot(),
    }


def _run_eval_job(capital: float, rebalance: int) -> None:
    global _eval_job
    try:
        from strategies.groww_swing.eval import run_full_eval

        with _eval_lock:
            _eval_job["message"] = "Running full daily eval (cycle + baseline)…"

        report = run_full_eval(
            capital=capital,
            rebalance_every_n_days=rebalance,
        )
        # Persist calibration from full eval only
        try:
            from strategies.groww_swing.backtest import export_calibrated_params, BacktestResult

            cal = report["with_cycle_filter"]
            fake = BacktestResult(
                starting_capital=capital,
                ending_capital=cal["ending_capital"],
                total_return_pct=cal["total_return_pct"],
                win_rate=cal["win_rate"],
                expectancy_r=cal["expectancy_r"],
                max_drawdown_pct=cal["max_drawdown_pct"],
                num_trades=cal["num_trades"],
                with_cycle_filter=True,
                approach_stats=cal.get("approach_stats") or {},
            )
            export_calibrated_params(fake, path=PARAMS_PATH, base_params=_load_params())
        except Exception as exc:
            logger.warning("Could not export calibration: %s", exc)

        with _eval_lock:
            _eval_job.update(
                {
                    "status": "done",
                    "message": (
                        f"Eval done: cycle {report['with_cycle_filter']['total_return_pct']}% "
                        f"vs baseline {report['baseline_technicals_only']['total_return_pct']}% "
                        f"({report['with_cycle_filter']['num_trades']} trades)"
                    ),
                    "result": report,
                    "finished_at": time.time(),
                    "error": None,
                }
            )
    except Exception as exc:
        logger.exception("Full eval failed")
        with _eval_lock:
            _eval_job.update(
                {
                    "status": "error",
                    "message": str(exc),
                    "error": str(exc),
                    "finished_at": time.time(),
                }
            )


@router.post("/eval")
def swing_eval_start(
    capital: float = 100_000.0,
    rebalance: int = 2,
) -> Dict[str, Any]:
    """Start full daily-cache eval in background (baseline included)."""
    from strategies.groww_swing.panel_cache import cache_is_usable

    if not cache_is_usable():
        raise HTTPException(
            status_code=400,
            detail="Groww cache empty — refresh full history first",
        )

    with _eval_lock:
        if _eval_job.get("status") == "running":
            return {
                "started": False,
                "message": "Eval already running",
                "eval_job": dict(_eval_job),
            }
        _eval_job.update(
            {
                "status": "running",
                "message": "Starting full eval…",
                "started_at": time.time(),
                "finished_at": None,
                "error": None,
                "result": None,
            }
        )

    thread = threading.Thread(
        target=_run_eval_job,
        args=(capital, rebalance),
        daemon=True,
        name="groww-swing-eval",
    )
    thread.start()
    return {
        "started": True,
        "message": "Full eval started — poll /api/swing/status or /api/swing/eval",
        "eval_job": _eval_snapshot(),
    }


@router.get("/eval")
def swing_eval_status() -> Dict[str, Any]:
    return {"eval_job": _eval_snapshot()}
