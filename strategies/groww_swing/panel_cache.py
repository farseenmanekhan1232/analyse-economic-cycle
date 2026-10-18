"""Offline Groww OHLCV panel cache for real-history backtests.

Groww equity/index candles are available from ~2020 (vendor limit), not 20y.
Daily requests max 180 days — we chunk from GROWW_HISTORY_START → now.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = Path(
    os.getenv("GROWW_SWING_CACHE", str(_REPO_ROOT / "data" / "groww_cache"))
)

# Groww Backtesting API: equities/indices from 2020
GROWW_HISTORY_START = datetime(2020, 1, 1)


def _symbol_path(cache_dir: Path, symbol: str) -> Path:
    safe = symbol.upper().replace(" ", "_").replace("/", "_")
    return cache_dir / f"{safe}.csv"


def save_frame(cache_dir: Path, symbol: str, df: pd.DataFrame) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    out.to_csv(_symbol_path(cache_dir, symbol), index_label="date")


def load_frame(cache_dir: Path, symbol: str) -> pd.DataFrame:
    path = _symbol_path(cache_dir, symbol)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    return df.sort_index()


def load_panel(
    symbols: List[str],
    *,
    cache_dir: Optional[Path] = None,
) -> Dict[str, pd.DataFrame]:
    root = cache_dir or DEFAULT_CACHE_DIR
    out: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = load_frame(root, sym)
        if not df.empty:
            out[sym.upper()] = df
    return out


def _history_span(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str], int]:
    if df is None or df.empty:
        return None, None, 0
    idx = pd.DatetimeIndex(pd.to_datetime(df.index)).sort_values()
    return str(idx[0].date()), str(idx[-1].date()), int(len(idx))


def write_manifest(
    cache_dir: Path,
    *,
    symbols: List[str],
    frames: Dict[str, pd.DataFrame],
    primary_only: bool,
    full_history: bool,
    interval: str = "day",
) -> Dict[str, Any]:
    starts, ends, counts = [], [], []
    for df in frames.values():
        s, e, n = _history_span(df)
        if s:
            starts.append(s)
            ends.append(e)
            counts.append(n)
    meta: Dict[str, Any] = {
        "symbols": symbols,
        "n": len(symbols),
        "primary_only": primary_only,
        "full_history": full_history,
        "interval": interval,
        "history_start": min(starts) if starts else None,
        "history_end": max(ends) if ends else None,
        "min_bars": min(counts) if counts else 0,
        "max_bars": max(counts) if counts else 0,
        "groww_vendor_note": (
            "Groww equity/index history from ~2020 only — not 20y. "
            "15m is not the primary swing timeframe."
        ),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def read_manifest(cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    root = cache_dir or DEFAULT_CACHE_DIR
    path = root / "manifest.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def fetch_and_cache_panel(
    broker: Any,
    symbols: List[str],
    *,
    days: int = 400,
    cache_dir: Optional[Path] = None,
    force: bool = False,
    full_history: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Fetch daily candles from Groww and write CSVs under data/groww_cache/."""
    root = cache_dir or DEFAULT_CACHE_DIR
    root.mkdir(parents=True, exist_ok=True)
    start = GROWW_HISTORY_START if full_history else None
    # ~trading days since 2020 if full; else requested window
    min_bars_ok = 800 if full_history else min(days - 40, 120)
    out: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        if not force:
            cached = load_frame(root, sym)
            if len(cached) >= min_bars_ok:
                out[sym.upper()] = cached
                continue
        try:
            if full_history:
                df = broker.get_historical_candles(
                    trading_symbol=sym,
                    start=start,
                    interval="day",
                    groww_symbol=f"NSE-{sym}",
                )
            else:
                df = broker.get_historical_candles(
                    trading_symbol=sym,
                    days=days,
                    interval="day",
                    groww_symbol=f"NSE-{sym}",
                )
        except Exception as exc:
            logger.warning("Fetch failed %s: %s", sym, exc)
            df = pd.DataFrame()
        if df.empty:
            cached = load_frame(root, sym)
            if not cached.empty:
                out[sym.upper()] = cached
            continue
        save_frame(root, sym, df)
        out[sym.upper()] = df
    write_manifest(
        root,
        symbols=list(out.keys()),
        frames=out,
        primary_only=True,
        full_history=full_history,
    )
    return out


def build_sector_and_symbol_panels(
    broker: Any,
    *,
    days: int = 400,
    cache_dir: Optional[Path] = None,
    force: bool = False,
    primary_only: bool = True,
    full_history: bool = False,
    progress: Optional[Any] = None,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
    """Sector proxy ETFs as sector_data + ETF candles.

    full_history=True: chunk from GROWW_HISTORY_START (2020-01-01) → now.
    primary_only=True: one liquid ETF per sector.
    """
    from .universe import SECTOR_ETFS, SECTOR_PROXY_ETF

    sector_syms = list(dict.fromkeys(SECTOR_PROXY_ETF.values()))
    if primary_only:
        etf_syms = list(sector_syms)
    else:
        etf_syms = []
        for syms in SECTOR_ETFS.values():
            for s in syms:
                if s not in etf_syms:
                    etf_syms.append(s)

    all_syms = list(dict.fromkeys(sector_syms + etf_syms + ["NIFTY"]))
    root = cache_dir or DEFAULT_CACHE_DIR
    min_bars_ok = 800 if full_history else min(days - 40, 120)
    out: Dict[str, pd.DataFrame] = {}
    total = len(all_syms)
    for i, sym in enumerate(all_syms, start=1):
        if progress is not None:
            try:
                progress(i, total, sym)
            except Exception:
                pass
        if not force:
            cached = load_frame(root, sym)
            if len(cached) >= min_bars_ok:
                out[sym.upper()] = cached
                continue
        try:
            if full_history:
                df = broker.get_historical_candles(
                    trading_symbol=sym,
                    start=GROWW_HISTORY_START,
                    interval="day",
                    groww_symbol=f"NSE-{sym}",
                )
            else:
                df = broker.get_historical_candles(
                    trading_symbol=sym,
                    days=days,
                    interval="day",
                    groww_symbol=f"NSE-{sym}",
                )
        except Exception as exc:
            logger.warning("Fetch failed %s: %s", sym, exc)
            df = pd.DataFrame()
        if df.empty:
            cached = load_frame(root, sym)
            if not cached.empty:
                out[sym.upper()] = cached
            continue
        save_frame(root, sym, df)
        out[sym.upper()] = df

    write_manifest(
        root,
        symbols=list(out.keys()),
        frames=out,
        primary_only=primary_only,
        full_history=full_history,
    )

    sector_data: Dict[str, pd.DataFrame] = {}
    for sector, proxy in SECTOR_PROXY_ETF.items():
        df = out.get(proxy.upper())
        if df is not None and not df.empty:
            sector_data[sector] = df

    symbol_candles = {
        k: v
        for k, v in out.items()
        if k != "NIFTY" and any(k == s.upper() for s in etf_syms)
    }
    return sector_data, symbol_candles


def load_cached_backtest_panels(
    *,
    cache_dir: Optional[Path] = None,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], Optional[pd.DataFrame]]:
    """Load sector + symbol panels from cache only (no network)."""
    from .universe import SECTOR_ETFS, SECTOR_PROXY_ETF

    root = cache_dir or DEFAULT_CACHE_DIR
    sector_data: Dict[str, pd.DataFrame] = {}
    for sector, proxy in SECTOR_PROXY_ETF.items():
        df = load_frame(root, proxy)
        if not df.empty:
            sector_data[sector] = df

    symbol_candles: Dict[str, pd.DataFrame] = {}
    for syms in SECTOR_ETFS.values():
        for s in syms:
            df = load_frame(root, s)
            if not df.empty:
                symbol_candles[s.upper()] = df

    bench = load_frame(root, "NIFTY")
    return sector_data, symbol_candles, bench if not bench.empty else None


def cache_is_usable(cache_dir: Optional[Path] = None, min_symbols: int = 6) -> bool:
    root = cache_dir or DEFAULT_CACHE_DIR
    _, symbols, _ = load_cached_backtest_panels(cache_dir=root)
    return len(symbols) >= min_symbols


def cache_history_summary(cache_dir: Optional[Path] = None) -> Dict[str, Any]:
    root = cache_dir or DEFAULT_CACHE_DIR
    meta = read_manifest(root)
    _, symbols, bench = load_cached_backtest_panels(cache_dir=root)
    return {
        "cache_ready": len(symbols) >= 6,
        "n_symbols": len(symbols),
        "has_benchmark": bench is not None and not bench.empty,
        "manifest": meta,
    }
