"""Instrument-level swing setups: indicators + named approach detectors."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Set

import numpy as np
import pandas as pd

from .catalog import get_detectors, prioritize, resolve_enabled
from .cycle_filter import DEFENSIVE_SECTORS
from .regime_router import eligible_approaches, filter_sectors_for_approach


def _ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.rename(columns={c: c.lower() for c in out.columns})
    return out


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def relative_strength(
    asset_close: pd.Series,
    benchmark_close: pd.Series,
    lookback: int = 63,
) -> Optional[float]:
    joined = pd.concat([asset_close, benchmark_close], axis=1, join="inner").dropna()
    if len(joined) < lookback + 1:
        return None
    a = joined.iloc[:, 0]
    b = joined.iloc[:, 1]
    if b.iloc[-1] == 0 or b.iloc[-lookback - 1] == 0:
        return None
    asset_ret = a.iloc[-1] / a.iloc[-lookback] - 1
    bench_ret = b.iloc[-1] / b.iloc[-lookback] - 1
    return round(float((asset_ret - bench_ret) * 100), 2)


def enrich(df: pd.DataFrame, params: Mapping[str, Any]) -> pd.DataFrame:
    """Add indicator columns used by approach detection."""
    out = _ohlcv(df)
    close = out["close"].astype(float)
    out["ema_fast"] = ema(close, int(params.get("ema_fast", 20)))
    out["ema_slow"] = ema(close, int(params.get("ema_slow", 50)))
    out["rsi"] = rsi(close, int(params.get("rsi_period", 14)))
    out["atr"] = atr(out, int(params.get("atr_period", 14)))
    lookback = int(params.get("breakout_lookback", 20))
    out["high_n"] = out["high"].astype(float).rolling(lookback).max().shift(1)
    out["low_n"] = out["low"].astype(float).rolling(lookback).min().shift(1)
    if "volume" in out.columns:
        out["vol_ma"] = out["volume"].astype(float).rolling(lookback).mean()
    else:
        out["vol_ma"] = np.nan
    bb_n = int(params.get("bb_period", 20))
    mid = close.rolling(bb_n).mean()
    std = close.rolling(bb_n).std()
    out["bb_mid"] = mid
    out["bb_width"] = (2.0 * std) / mid.replace(0, np.nan)
    out["bb_width_pctile"] = out["bb_width"].rolling(60).rank(pct=True)
    out["close_z"] = (close - mid) / std.replace(0, np.nan)
    out["atr_pct"] = out["atr"] / close.replace(0, np.nan)
    out["atr_pctile"] = out["atr_pct"].rolling(60).rank(pct=True)
    return out


def _levels(
    price: float,
    atr_val: float,
    params: Mapping[str, Any],
    *,
    stop_mult: Optional[float] = None,
    target_r: Optional[float] = None,
) -> Optional[Dict[str, float]]:
    sm = float(stop_mult if stop_mult is not None else params.get("atr_stop_mult", 2.0))
    tr = float(target_r if target_r is not None else params.get("target_r_mult", 2.5))
    stop = round(price - sm * atr_val, 4)
    risk = price - stop
    if risk <= 0:
        return None
    target = round(price + tr * risk, 4)
    return {"stop": stop, "target": target, "risk": risk}


def _base_context(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    rs_override: Optional[float] = None,
    skip_rs_hard_filter: bool = False,
    enriched: Optional[pd.DataFrame] = None,
) -> Optional[Dict[str, Any]]:
    enriched = enriched if enriched is not None else enrich(df, params)
    need = max(
        int(params.get("ema_slow", 50)),
        int(params.get("atr_period", 14)),
        int(params.get("breakout_lookback", 20)),
        60,
    ) + 5
    if len(enriched) < need:
        return None

    row = enriched.iloc[-1]
    prev = enriched.iloc[-2]
    price = float(row["close"])
    atr_val = float(row["atr"]) if pd.notna(row["atr"]) else None
    if atr_val is None or atr_val <= 0 or price <= 0:
        return None

    rsi_now = float(row["rsi"]) if pd.notna(row["rsi"]) else None
    rsi_prev = float(prev["rsi"]) if pd.notna(prev["rsi"]) else None
    if rsi_now is None:
        return None

    rs = rs_override
    if rs is None and benchmark_close is not None:
        rs = relative_strength(
            enriched["close"],
            benchmark_close,
            lookback=int(params.get("rs_lookback", 63)),
        )
        if not skip_rs_hard_filter and rs is not None and rs < 0:
            return None

    return {
        "enriched": enriched,
        "row": row,
        "prev": prev,
        "price": price,
        "atr_val": atr_val,
        "ema_fast": float(row["ema_fast"]),
        "ema_slow": float(row["ema_slow"]),
        "rsi_now": rsi_now,
        "rsi_prev": rsi_prev,
        "rs": rs,
        "symbol": symbol.upper(),
        "sector": sector,
    }


def _pack(
    ctx: Dict[str, Any],
    *,
    setup: str,
    rationale: str,
    params: Mapping[str, Any],
    stop_mult: Optional[float] = None,
    target_r: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    levels = _levels(
        ctx["price"],
        ctx["atr_val"],
        params,
        stop_mult=stop_mult,
        target_r=target_r,
    )
    if levels is None:
        return None
    return {
        "symbol": ctx["symbol"],
        "sector": ctx["sector"],
        "setup": setup,
        "approach": setup,
        "side": "BUY",
        "entry": round(ctx["price"], 4),
        "stop": levels["stop"],
        "target": levels["target"],
        "atr": round(ctx["atr_val"], 4),
        "rsi": round(ctx["rsi_now"], 2),
        "rs_vs_benchmark_pct": ctx["rs"],
        "r_rupees": round(levels["risk"], 4),
        "rationale": rationale,
        "as_of": ctx["enriched"].index[-1].isoformat(),
    }


def detect_trend_pullback(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    ctx: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Optional[Dict[str, Any]]:
    ctx = ctx or _base_context(
        df, symbol=symbol, sector=sector, params=params, benchmark_close=benchmark_close
    )
    if ctx is None:
        return None
    if ctx["rs"] is not None and ctx["rs"] < 0:
        return None
    rsi_lo = float(params.get("rsi_pullback_low", 40))
    rsi_hi = float(params.get("rsi_pullback_high", 55))
    near_ema = abs(ctx["price"] - ctx["ema_fast"]) / ctx["price"] <= 0.015
    uptrend = ctx["ema_fast"] > ctx["ema_slow"] and ctx["price"] > ctx["ema_slow"]
    rsi_reclaim = (
        ctx["rsi_prev"] is not None
        and ctx["rsi_prev"] < rsi_lo
        and rsi_lo <= ctx["rsi_now"] <= rsi_hi + 5
    )
    if uptrend and near_ema and (rsi_reclaim or rsi_lo <= ctx["rsi_now"] <= rsi_hi):
        return _pack(
            ctx,
            setup="trend_pullback",
            rationale=f"EMA{params.get('ema_fast', 20)} pullback in uptrend, RSI={ctx['rsi_now']:.1f}",
            params=params,
        )
    return None


def detect_trend_breakout(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    ctx: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Optional[Dict[str, Any]]:
    ctx = ctx or _base_context(
        df, symbol=symbol, sector=sector, params=params, benchmark_close=benchmark_close
    )
    if ctx is None:
        return None
    if ctx["rs"] is not None and ctx["rs"] < 0:
        return None
    row = ctx["row"]
    high_n = float(row["high_n"]) if pd.notna(row.get("high_n")) else None
    vol = float(row["volume"]) if "volume" in ctx["enriched"].columns and pd.notna(row.get("volume")) else None
    vol_ma = float(row["vol_ma"]) if pd.notna(row.get("vol_ma")) else None
    vol_ok = vol is None or vol_ma is None or vol_ma == 0 or vol >= 1.1 * vol_ma
    uptrend = ctx["ema_fast"] > ctx["ema_slow"] and ctx["price"] > ctx["ema_slow"]
    if high_n and ctx["price"] > high_n and uptrend and vol_ok:
        return _pack(
            ctx,
            setup="trend_breakout",
            rationale=f"Breakout above {int(params.get('breakout_lookback', 20))}d high {high_n:.2f}",
            params=params,
        )
    return None


def detect_rs_momentum(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    rs_rank_ok: bool = False,
    ctx: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Optional[Dict[str, Any]]:
    """Only fires when caller marks symbol in top RS cohort (rs_rank_ok)."""
    if not rs_rank_ok:
        return None
    ctx = ctx or _base_context(
        df,
        symbol=symbol,
        sector=sector,
        params=params,
        benchmark_close=benchmark_close,
        skip_rs_hard_filter=True,
    )
    if ctx is None:
        return None
    if ctx["rs"] is None or ctx["rs"] < float(params.get("rs_momentum_min_pct", 0.0)):
        return None
    uptrend = ctx["ema_fast"] > ctx["ema_slow"] and ctx["price"] > ctx["ema_slow"]
    if not uptrend or ctx["rsi_now"] < float(params.get("rs_momentum_min_rsi", 50)):
        return None
    return _pack(
        ctx,
        setup="rs_momentum",
        rationale=f"Top RS vs benchmark ({ctx['rs']}%), RSI={ctx['rsi_now']:.1f}",
        params=params,
        stop_mult=float(params.get("rs_momentum_atr_stop", 2.2)),
        target_r=float(params.get("rs_momentum_target_r", 2.0)),
    )


def detect_defensive_mean_reversion(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    ctx: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Optional[Dict[str, Any]]:
    if sector not in set(DEFENSIVE_SECTORS):
        return None
    ctx = ctx or _base_context(
        df,
        symbol=symbol,
        sector=sector,
        params=params,
        benchmark_close=benchmark_close,
        skip_rs_hard_filter=True,
    )
    if ctx is None:
        return None
    row = ctx["row"]
    z = float(row["close_z"]) if pd.notna(row.get("close_z")) else None
    rsi_lo = float(params.get("mr_rsi_oversold", 35))
    reclaim = (
        ctx["rsi_prev"] is not None
        and ctx["rsi_prev"] < rsi_lo
        and ctx["rsi_now"] >= rsi_lo
        and ctx["rsi_now"] < 55
    )
    z_bounce = (
        z is not None
        and z < float(params.get("mr_z_entry", -1.5))
        and ctx["rsi_prev"] is not None
        and ctx["rsi_now"] > ctx["rsi_prev"]
    )
    if not (reclaim or z_bounce):
        return None
    return _pack(
        ctx,
        setup="defensive_mean_reversion",
        rationale=f"Defensive MR: RSI={ctx['rsi_now']:.1f} z={z}",
        params=params,
        stop_mult=float(params.get("mr_atr_stop", 1.5)),
        target_r=float(params.get("mr_target_r", 1.5)),
    )


def detect_vol_compression_break(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    ctx: Optional[Dict[str, Any]] = None,
    **_: Any,
) -> Optional[Dict[str, Any]]:
    ctx = ctx or _base_context(
        df, symbol=symbol, sector=sector, params=params, benchmark_close=benchmark_close
    )
    if ctx is None:
        return None
    if ctx["rs"] is not None and ctx["rs"] < 0:
        return None
    row = ctx["row"]
    width_pct = float(row["bb_width_pctile"]) if pd.notna(row.get("bb_width_pctile")) else None
    atr_pctile = float(row["atr_pctile"]) if pd.notna(row.get("atr_pctile")) else None
    compressed = (
        (width_pct is not None and width_pct <= float(params.get("squeeze_bb_pctile", 0.25)))
        or (atr_pctile is not None and atr_pctile <= float(params.get("squeeze_atr_pctile", 0.25)))
    )
    if not compressed:
        return None
    high_n = float(row["high_n"]) if pd.notna(row.get("high_n")) else None
    uptrend = ctx["ema_fast"] > ctx["ema_slow"]
    if not (high_n and ctx["price"] > high_n and uptrend):
        return None
    return _pack(
        ctx,
        setup="vol_compression_break",
        rationale=f"Squeeze break (bb_pctile={width_pct}) above {high_n:.2f}",
        params=params,
        stop_mult=float(params.get("squeeze_atr_stop", 1.8)),
        target_r=float(params.get("squeeze_target_r", 2.5)),
    )


def detect_setup(
    df: pd.DataFrame,
    *,
    symbol: str,
    sector: str,
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    approaches: Optional[List[str]] = None,
    rs_rank_ok: bool = False,
) -> Optional[Dict[str, Any]]:
    """Try enabled/eligible approaches in priority order; return first hit."""
    detectors = get_detectors()
    ids = prioritize(approaches or resolve_enabled(params))
    # Enrich once — detectors reuse ctx (was ~5× enrich per symbol before)
    ctx = _base_context(
        df,
        symbol=symbol,
        sector=sector,
        params=params,
        benchmark_close=benchmark_close,
        skip_rs_hard_filter=True,
    )
    if ctx is None:
        return None
    for aid in ids:
        fn = detectors.get(aid)
        if not fn:
            continue
        hit = fn(
            df,
            symbol=symbol,
            sector=sector,
            params=params,
            benchmark_close=benchmark_close,
            rs_rank_ok=rs_rank_ok,
            ctx=ctx,
        )
        if hit:
            return hit
    return None


def _rs_top_symbols(
    candles: Mapping[str, pd.DataFrame],
    *,
    symbol_sector: Mapping[str, str],
    allowed_sectors: Set[str],
    benchmark_close: Optional[pd.Series],
    params: Mapping[str, Any],
) -> Set[str]:
    if benchmark_close is None:
        return set()
    scores: List[tuple] = []
    lookback = int(params.get("rs_lookback", 63))
    for symbol, df in candles.items():
        sector = symbol_sector.get(symbol) or symbol_sector.get(symbol.upper()) or ""
        if allowed_sectors and sector not in allowed_sectors:
            continue
        enriched = _ohlcv(df)
        if len(enriched) < lookback + 5:
            continue
        rs = relative_strength(enriched["close"], benchmark_close, lookback=lookback)
        if rs is None:
            continue
        scores.append((symbol.upper(), rs))
    if not scores:
        return set()
    scores.sort(key=lambda x: x[1], reverse=True)
    top_n = max(int(params.get("rs_momentum_top_n", 3)), max(1, len(scores) // 4))
    return {s for s, _ in scores[:top_n]}


def scan_universe(
    candles: Mapping[str, pd.DataFrame],
    *,
    symbol_sector: Mapping[str, str],
    params: Mapping[str, Any],
    benchmark_close: Optional[pd.Series] = None,
    bias: Optional[Mapping[str, Any]] = None,
    approaches: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Scan symbols for named approaches (regime-routed when bias provided)."""
    if approaches is not None:
        approach_ids = prioritize(list(approaches))
    elif bias is not None:
        approach_ids = eligible_approaches(bias, params)
    else:
        approach_ids = prioritize(resolve_enabled(params))

    if not approach_ids:
        return []

    allowed_sectors: Set[str] = set()
    if bias and bias.get("allowed_sectors"):
        allowed_sectors = set(bias["allowed_sectors"])

    # Union of sectors any eligible approach can trade
    scan_sectors: Set[str] = set()
    if allowed_sectors:
        for aid in approach_ids:
            scan_sectors.update(filter_sectors_for_approach(aid, list(allowed_sectors)))
    else:
        scan_sectors = set(symbol_sector.values())

    top_rs: Set[str] = set()
    if "rs_momentum" in approach_ids:
        top_rs = _rs_top_symbols(
            candles,
            symbol_sector=symbol_sector,
            allowed_sectors=scan_sectors or set(symbol_sector.values()),
            benchmark_close=benchmark_close,
            params=params,
        )

    setups: List[Dict[str, Any]] = []
    for symbol, df in candles.items():
        sector = symbol_sector.get(symbol) or symbol_sector.get(symbol.upper()) or ""
        if not sector:
            continue
        if scan_sectors and sector not in scan_sectors:
            continue
        filtered: List[str] = []
        for a in approach_ids:
            if a == "defensive_mean_reversion" and sector not in set(DEFENSIVE_SECTORS):
                continue
            filtered.append(a)
        if not filtered:
            continue
        hit = detect_setup(
            df,
            symbol=symbol,
            sector=sector,
            params=params,
            benchmark_close=benchmark_close,
            approaches=filtered,
            rs_rank_ok=symbol.upper() in top_rs,
        )
        if hit:
            setups.append(hit)

    setups.sort(
        key=lambda s: (
            s.get("rs_vs_benchmark_pct") is not None,
            s.get("rs_vs_benchmark_pct") or -999,
        ),
        reverse=True,
    )
    return setups
