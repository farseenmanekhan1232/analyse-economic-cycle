"""Unit tests for portable groww_swing package (no growwapi required)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from strategies.groww_swing.backtest import (
    export_calibrated_params,
    run_swing_backtest,
    synthetic_demo_data,
)
from strategies.groww_swing.cycle_filter import compute_cycle_bias, closes_frame
from strategies.groww_swing.risk import filter_and_size, shares_for_risk
from strategies.groww_swing.setups import atr, detect_setup, enrich, rsi
from strategies.groww_swing.universe import sector_for_symbol, symbols_for_sectors


def test_closes_frame_and_cycle_bias():
    sectors, _ = synthetic_demo_data(n_days=250, seed=1)
    closes = closes_frame(sectors)
    assert not closes.empty
    assert "BANK" in closes.columns
    bias = compute_cycle_bias(sectors, vix_value=14.0)
    assert bias["phase"] in {"expansion", "contraction", "unknown"}
    assert "sector_scores" in bias
    assert isinstance(bias["allowed_sectors"], list)


def test_risk_sizing():
    qty = shares_for_risk(capital=100_000, entry=100.0, stop=95.0, risk_pct=0.01)
    assert qty == 200  # 1000 risk / 5 per share
    qty2 = shares_for_risk(capital=1000, entry=100.0, stop=95.0, risk_pct=0.01)
    assert qty2 == 2  # cash capped


def test_filter_and_size_respects_max_open():
    setups = [
        {
            "symbol": f"SYM{i}",
            "sector": "BANK" if i < 3 else "IT",
            "entry": 100.0,
            "stop": 95.0,
            "target": 110.0,
            "setup": "pullback",
        }
        for i in range(6)
    ]
    sized = filter_and_size(
        setups,
        capital=100_000,
        params={"max_open_trades": 3, "max_sector_trades": 2, "risk_pct_per_trade": 0.01},
    )
    assert len(sized) <= 3
    assert all(s["quantity"] >= 1 for s in sized)


def test_indicators_and_setup_detection():
    rng = np.random.default_rng(0)
    n = 120
    idx = pd.bdate_range("2024-01-01", periods=n)
    # Uptrend then mild pullback into EMA
    close = np.linspace(100, 130, n) + rng.normal(0, 0.3, n)
    close[-3:] = close[-5] * np.array([0.995, 0.992, 0.998])
    df = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.integers(1e5, 2e5, n),
        },
        index=idx,
    )
    enriched = enrich(df, {"ema_fast": 20, "ema_slow": 50, "atr_period": 14, "rsi_period": 14})
    assert "atr" in enriched.columns
    assert enriched["atr"].iloc[-1] > 0
    assert 0 < rsi(df["close"]).iloc[-1] < 100
    assert atr(df).iloc[-1] > 0

    hit = detect_setup(df, symbol="BANKBEES", sector="BANK", params={
        "ema_fast": 20,
        "ema_slow": 50,
        "atr_period": 14,
        "atr_stop_mult": 2.0,
        "target_r_mult": 2.5,
        "rsi_period": 14,
        "rsi_pullback_low": 30,
        "rsi_pullback_high": 70,
        "breakout_lookback": 20,
    })
    # May or may not fire depending on random path; ensure no crash and shape if present
    if hit:
        assert hit["entry"] > hit["stop"]
        assert hit["target"] > hit["entry"]
        assert hit["side"] == "BUY"


def test_universe_helpers():
    assert sector_for_symbol("BANKBEES") == "BANK"
    assert "BANKBEES" in symbols_for_sectors(["BANK"])


def test_catalog_and_router():
    from strategies.groww_swing.catalog import ALL_APPROACH_IDS, resolve_enabled
    from strategies.groww_swing.regime_router import eligible_approaches

    params = {
        "enabled_approaches": list(ALL_APPROACH_IDS),
        "allow_contraction_defensives": True,
    }
    assert set(resolve_enabled(params)) == set(ALL_APPROACH_IDS)
    exp = eligible_approaches(
        {"phase": "expansion", "sub_phase": "early_expansion", "risk_off": False},
        params,
    )
    assert "trend_pullback" in exp
    assert "defensive_mean_reversion" not in exp
    con = eligible_approaches(
        {"phase": "contraction", "sub_phase": "contraction", "risk_off": False},
        params,
    )
    assert "defensive_mean_reversion" in con
    assert eligible_approaches({"phase": "expansion", "risk_off": True}, params) == []


def test_rs_momentum_disabled_by_default():
    from strategies.groww_swing.backtest import load_params

    p = load_params()
    assert "rs_momentum" not in (p.get("enabled_approaches") or [])


def test_eval_writes_report(tmp_path):
    from strategies.groww_swing.eval import run_full_eval
    from strategies.groww_swing.panel_cache import save_frame, write_manifest
    from strategies.groww_swing.universe import SECTOR_PROXY_ETF

    # Build a tiny fake cache so eval can run offline
    sectors, symbols = synthetic_demo_data(n_days=280, seed=9)
    for sec, proxy in SECTOR_PROXY_ETF.items():
        if sec in sectors:
            save_frame(tmp_path, proxy, sectors[sec])
    for sym, df in symbols.items():
        save_frame(tmp_path, sym, df)
    write_manifest(
        tmp_path,
        symbols=list(symbols.keys()),
        frames=symbols,
        primary_only=True,
        full_history=True,
    )
    report = run_full_eval(
        capital=100_000.0,
        rebalance_every_n_days=10,
        cache_dir=tmp_path,
        out_path=tmp_path / "last_eval.json",
    )
    assert report["mode"] == "groww_cache_full"
    assert "with_cycle_filter" in report
    assert "baseline_technicals_only" in report
    assert (tmp_path / "last_eval.json").exists()


def test_scan_universe_respects_approaches():
    from strategies.groww_swing.setups import scan_universe

    sectors, symbols = synthetic_demo_data(n_days=250, seed=2)
    symbol_sector = {s: sector_for_symbol(s) or "" for s in symbols}
    bias = compute_cycle_bias(sectors, vix_value=14.0)
    allowed = {"trend_pullback", "trend_breakout"}
    hits = scan_universe(
        symbols,
        symbol_sector=symbol_sector,
        params={
            "enabled_approaches": list(allowed),
            "ema_fast": 20,
            "ema_slow": 50,
            "atr_period": 14,
            "atr_stop_mult": 2.0,
            "target_r_mult": 2.5,
            "rsi_period": 14,
            "breakout_lookback": 20,
            "allow_contraction_defensives": True,
        },
        bias=bias,
        approaches=list(allowed),
    )
    for h in hits:
        assert h["setup"] in allowed


def test_backtest_runs_and_exports(tmp_path):
    sectors, symbols = synthetic_demo_data(n_days=280, seed=7)
    result = run_swing_backtest(sectors, symbols, capital=100_000.0, use_cycle_filter=True)
    assert result.starting_capital == 100_000.0
    assert result.num_trades >= 0
    assert len(result.equity_curve) > 0
    assert isinstance(result.approach_stats, dict)
    out = tmp_path / "params.json"
    import json

    base = {
        "risk_pct_per_trade": 0.0075,
        "max_open_trades": 4,
        "dry_run": True,
    }
    with open(out, "w") as f:
        json.dump(base, f)
    exported = export_calibrated_params(result, path=out, base_params=base)
    assert "calibration" in exported
    assert exported["calibration"]["num_trades"] == result.num_trades
