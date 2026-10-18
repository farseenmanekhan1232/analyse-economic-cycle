"""Walk-forward swing backtest (cycle filter + setups). No Groww dependency.

Accepts pre-loaded OHLCV dicts so research can use Kite or Groww candles.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from .cycle_filter import compute_cycle_bias
from .regime_router import eligible_approaches
from .risk import shares_for_risk
from .setups import scan_universe
from .universe import SECTOR_ETFS, sector_for_symbol

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_PARAMS_PATH = PACKAGE_DIR / "params.json"


def load_params(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or DEFAULT_PARAMS_PATH
    with open(p, encoding="utf-8") as f:
        return json.load(f)


@dataclass
class Trade:
    symbol: str
    sector: str
    setup: str
    entry_date: str
    entry: float
    stop: float
    target: float
    quantity: int
    exit_date: Optional[str] = None
    exit: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    r_multiple: float = 0.0


@dataclass
class BacktestResult:
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    starting_capital: float = 0.0
    ending_capital: float = 0.0
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    expectancy_r: float = 0.0
    max_drawdown_pct: float = 0.0
    num_trades: int = 0
    with_cycle_filter: bool = True
    approach_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _align_dates(frames: Mapping[str, pd.DataFrame]) -> pd.DatetimeIndex:
    idx = None
    for df in frames.values():
        if df is None or df.empty:
            continue
        i = pd.DatetimeIndex(pd.to_datetime(df.index)).normalize()
        idx = i if idx is None else idx.intersection(i)
    return idx if idx is not None else pd.DatetimeIndex([])


def _slice_upto(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.to_datetime(out.index).normalize()
    return out.loc[out.index <= as_of]


def run_swing_backtest(
    sector_data: Mapping[str, pd.DataFrame],
    symbol_candles: Mapping[str, pd.DataFrame],
    *,
    symbol_sector: Optional[Mapping[str, str]] = None,
    benchmark: Optional[pd.DataFrame] = None,
    vix_series: Optional[pd.Series] = None,
    params: Optional[Mapping[str, Any]] = None,
    capital: float = 100_000.0,
    use_cycle_filter: bool = True,
    rebalance_every_n_days: int = 1,
) -> BacktestResult:
    """
    Daily walk-forward:
    - compute cycle bias on sector history up to t
    - scan allowed symbols for setups
    - enter at next bar open (approx: same-bar close for simplicity on daily)
    - exit on stop / target / max hold
    """
    p = dict(params or load_params())
    cost_bps = float(p.get("transaction_cost_bps", 10)) / 10_000.0
    max_hold = int(p.get("max_hold_days", 20))
    risk_pct = float(p.get("risk_pct_per_trade", 0.0075))
    max_open = int(p.get("max_open_trades", 4))

    # Build symbol→sector map
    sym_sec: Dict[str, str] = {}
    if symbol_sector:
        sym_sec.update({k.upper(): v for k, v in symbol_sector.items()})
    for sector, symbols in SECTOR_ETFS.items():
        for s in symbols:
            sym_sec.setdefault(s.upper(), sector)
    for s in symbol_candles:
        sym_sec.setdefault(s.upper(), sector_for_symbol(s) or "UNKNOWN")

    dates = _align_dates(symbol_candles)
    if len(dates) < 80:
        logger.warning("Not enough overlapping history for backtest (%s bars)", len(dates))
        return BacktestResult(starting_capital=capital, ending_capital=capital)

    # Warmup for indicators
    start_i = 60
    cash = float(capital)
    open_trades: List[Dict[str, Any]] = []
    closed: List[Trade] = []
    equity_curve: List[Dict[str, Any]] = []
    peak = capital

    bench_close = None
    if benchmark is not None and not benchmark.empty:
        b = benchmark.copy()
        b.index = pd.to_datetime(b.index).normalize()
        col = "close" if "close" in b.columns else b.columns[0]
        bench_close = b[col].astype(float)

    for i in range(start_i, len(dates)):
        as_of = dates[i]
        if rebalance_every_n_days > 1 and (i - start_i) % rebalance_every_n_days != 0:
            # still manage exits daily
            pass

        # Mark-to-market + exits
        still_open: List[Dict[str, Any]] = []
        for ot in open_trades:
            sym = ot["symbol"]
            df = symbol_candles.get(sym)
            if df is None:
                df = symbol_candles.get(sym.upper())
            if df is None:
                still_open.append(ot)
                continue
            hist = _slice_upto(df, as_of)
            if hist.empty:
                still_open.append(ot)
                continue
            bar = hist.iloc[-1]
            high = float(bar["high"] if "high" in hist.columns else bar["close"])
            low = float(bar["low"] if "low" in hist.columns else bar["close"])
            close = float(bar["close"])
            entry_date = pd.Timestamp(ot["entry_date"])
            held = (as_of - entry_date).days

            exit_px = None
            reason = None
            if low <= ot["stop"]:
                exit_px = ot["stop"]
                reason = "stop"
            elif high >= ot["target"]:
                exit_px = ot["target"]
                reason = "target"
            elif held >= max_hold:
                exit_px = close
                reason = "time"

            if exit_px is not None:
                pnl = (exit_px - ot["entry"]) * ot["quantity"]
                pnl -= cost_bps * exit_px * ot["quantity"]
                cash += ot["quantity"] * exit_px
                risk = ot["entry"] - ot["stop"]
                r_mult = ((exit_px - ot["entry"]) / risk) if risk > 0 else 0.0
                closed.append(
                    Trade(
                        symbol=sym,
                        sector=ot["sector"],
                        setup=ot["setup"],
                        entry_date=str(ot["entry_date"])[:10],
                        entry=ot["entry"],
                        stop=ot["stop"],
                        target=ot["target"],
                        quantity=ot["quantity"],
                        exit_date=str(as_of.date()),
                        exit=round(exit_px, 4),
                        exit_reason=reason,
                        pnl=round(pnl, 2),
                        r_multiple=round(r_mult, 3),
                    )
                )
            else:
                still_open.append(ot)
        open_trades = still_open

        # Entries
        if len(open_trades) < max_open and (i - start_i) % rebalance_every_n_days == 0:
            sector_hist = {
                k: _slice_upto(v, as_of) for k, v in sector_data.items() if v is not None and not v.empty
            }
            vix_val = None
            if vix_series is not None and len(vix_series):
                vs = vix_series.copy()
                vs.index = pd.to_datetime(vs.index).normalize()
                vs = vs.loc[vs.index <= as_of]
                if len(vs):
                    vix_val = float(vs.iloc[-1])

            if use_cycle_filter:
                bias = compute_cycle_bias(sector_hist, vix_value=vix_val, params=p)
                allowed = set(bias.get("allowed_sectors") or [])
                risk_off = bool(bias.get("risk_off"))
            else:
                allowed = set(sector_hist.keys()) or set(sym_sec.values())
                risk_off = False

            if not risk_off and allowed:
                open_syms = {t["symbol"] for t in open_trades}
                sector_counts: Dict[str, int] = {}
                for t in open_trades:
                    sector_counts[t["sector"]] = sector_counts.get(t["sector"], 0) + 1

                bias_for_scan = {
                    "phase": bias.get("phase") if use_cycle_filter else "expansion",
                    "sub_phase": bias.get("sub_phase") if use_cycle_filter else "early_expansion",
                    "risk_off": risk_off,
                    "allowed_sectors": list(allowed),
                }
                if not use_cycle_filter:
                    # Baseline: all enabled approaches, all sectors present
                    bias_for_scan["phase"] = "expansion"
                    bias_for_scan["risk_off"] = False

                candle_slice = {
                    sym: _slice_upto(df, as_of)
                    for sym, df in symbol_candles.items()
                    if sym_sec.get(sym.upper(), "") in allowed or not use_cycle_filter
                }
                bclose = None
                if bench_close is not None:
                    bclose = bench_close.loc[bench_close.index <= as_of]

                approaches = (
                    eligible_approaches(bias_for_scan, p)
                    if use_cycle_filter
                    else None
                )
                candidates = scan_universe(
                    candle_slice,
                    symbol_sector=sym_sec,
                    params=p,
                    benchmark_close=bclose,
                    bias=bias_for_scan if use_cycle_filter else None,
                    approaches=approaches,
                )
                candidates = [
                    c for c in candidates if c["symbol"].upper() not in open_syms
                ]

                max_sector = int(p.get("max_sector_trades", 2))
                for hit in candidates:
                    if len(open_trades) >= max_open:
                        break
                    sector = hit["sector"]
                    if sector_counts.get(sector, 0) >= max_sector:
                        continue
                    qty = shares_for_risk(
                        capital=cash + sum(
                            t["quantity"]
                            * float(
                                _slice_upto(
                                    symbol_candles[t["symbol"]], as_of
                                ).iloc[-1]["close"]
                            )
                            for t in open_trades
                            if t["symbol"] in symbol_candles
                        ),
                        entry=float(hit["entry"]),
                        stop=float(hit["stop"]),
                        risk_pct=risk_pct,
                    )
                    if qty < 1:
                        qty = shares_for_risk(
                            capital=capital,
                            entry=float(hit["entry"]),
                            stop=float(hit["stop"]),
                            risk_pct=risk_pct,
                        )
                    if qty < 1:
                        continue
                    notional = qty * float(hit["entry"])
                    if notional > cash:
                        qty = int(cash // float(hit["entry"]))
                    if qty < 1:
                        continue
                    cash -= notional
                    cash -= cost_bps * notional
                    open_trades.append(
                        {
                            "symbol": hit["symbol"],
                            "sector": sector,
                            "setup": hit["setup"],
                            "entry_date": as_of,
                            "entry": float(hit["entry"]),
                            "stop": float(hit["stop"]),
                            "target": float(hit["target"]),
                            "quantity": qty,
                        }
                    )
                    sector_counts[sector] = sector_counts.get(sector, 0) + 1

        # Equity
        mtm = cash
        for t in open_trades:
            df = symbol_candles.get(t["symbol"])
            if df is None:
                continue
            hist = _slice_upto(df, as_of)
            if hist.empty:
                continue
            mtm += t["quantity"] * float(hist.iloc[-1]["close"])
        peak = max(peak, mtm)
        dd = (peak - mtm) / peak * 100 if peak > 0 else 0.0
        equity_curve.append(
            {"date": str(as_of.date()), "equity": round(mtm, 2), "drawdown_pct": round(dd, 2)}
        )

    # Force close remaining at last bar
    if dates.size and open_trades:
        as_of = dates[-1]
        for ot in open_trades:
            df = symbol_candles.get(ot["symbol"])
            if df is None:
                continue
            hist = _slice_upto(df, as_of)
            if hist.empty:
                continue
            exit_px = float(hist.iloc[-1]["close"])
            pnl = (exit_px - ot["entry"]) * ot["quantity"]
            risk = ot["entry"] - ot["stop"]
            r_mult = ((exit_px - ot["entry"]) / risk) if risk > 0 else 0.0
            closed.append(
                Trade(
                    symbol=ot["symbol"],
                    sector=ot["sector"],
                    setup=ot["setup"],
                    entry_date=str(ot["entry_date"])[:10],
                    entry=ot["entry"],
                    stop=ot["stop"],
                    target=ot["target"],
                    quantity=ot["quantity"],
                    exit_date=str(as_of.date()),
                    exit=round(exit_px, 4),
                    exit_reason="eod",
                    pnl=round(pnl, 2),
                    r_multiple=round(r_mult, 3),
                )
            )

    ending = equity_curve[-1]["equity"] if equity_curve else capital
    wins = [t for t in closed if t.pnl > 0]
    r_list = [t.r_multiple for t in closed]
    max_dd = max((e["drawdown_pct"] for e in equity_curve), default=0.0)

    by_setup = Counter(t.setup for t in closed)
    approach_stats: Dict[str, Any] = {}
    for setup, n in by_setup.items():
        subset = [t for t in closed if t.setup == setup]
        wr = len([t for t in subset if t.pnl > 0]) / len(subset) * 100 if subset else 0.0
        exp = float(np.mean([t.r_multiple for t in subset])) if subset else 0.0
        approach_stats[setup] = {
            "num_trades": n,
            "win_rate": round(wr, 1),
            "expectancy_r": round(exp, 3),
            "total_pnl": round(sum(t.pnl for t in subset), 2),
        }

    return BacktestResult(
        trades=closed,
        equity_curve=equity_curve,
        starting_capital=capital,
        ending_capital=round(ending, 2),
        total_return_pct=round((ending / capital - 1) * 100, 2) if capital else 0.0,
        win_rate=round(len(wins) / len(closed) * 100, 1) if closed else 0.0,
        expectancy_r=round(float(np.mean(r_list)), 3) if r_list else 0.0,
        max_drawdown_pct=round(max_dd, 2),
        num_trades=len(closed),
        with_cycle_filter=use_cycle_filter,
        approach_stats=approach_stats,
    )


def compare_cycle_vs_baseline(
    sector_data: Mapping[str, pd.DataFrame],
    symbol_candles: Mapping[str, pd.DataFrame],
    **kwargs: Any,
) -> Dict[str, Any]:
    with_filter = run_swing_backtest(
        sector_data, symbol_candles, use_cycle_filter=True, **kwargs
    )
    baseline = run_swing_backtest(
        sector_data, symbol_candles, use_cycle_filter=False, **kwargs
    )
    return {
        "with_cycle_filter": with_filter.to_dict(),
        "baseline_technicals_only": baseline.to_dict(),
        "cycle_edge_return_pct": round(
            with_filter.total_return_pct - baseline.total_return_pct, 2
        ),
        "cycle_edge_expectancy_r": round(
            with_filter.expectancy_r - baseline.expectancy_r, 3
        ),
    }


def synthetic_demo_data(
    n_days: int = 320,
    seed: int = 42,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame]]:
    """Generate correlated synthetic sector + ETF series for offline tests."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    sectors = ["BANK", "IT", "PHARMA", "AUTO", "METAL", "FMCG", "ENERGY", "REALTY"]
    # Regime: first half expansion (cyclicals up), second half contraction
    sector_data: Dict[str, pd.DataFrame] = {}
    for i, sec in enumerate(sectors):
        cyclical = sec in {"BANK", "AUTO", "METAL", "ENERGY", "REALTY"}
        drift = np.where(
            np.arange(n_days) < n_days // 2,
            0.0008 if cyclical else 0.0002,
            -0.0005 if cyclical else 0.0004,
        )
        noise = rng.normal(0, 0.012, n_days)
        rets = drift + noise
        close = 100 * np.cumprod(1 + rets)
        high = close * (1 + rng.uniform(0.002, 0.01, n_days))
        low = close * (1 - rng.uniform(0.002, 0.01, n_days))
        open_ = close * (1 + rng.normal(0, 0.002, n_days))
        vol = rng.integers(100_000, 500_000, n_days)
        sector_data[sec] = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
            index=idx,
        )

    symbol_candles: Dict[str, pd.DataFrame] = {}
    for sec, symbols in SECTOR_ETFS.items():
        if sec not in sector_data:
            continue
        base = sector_data[sec]["close"].values
        for j, sym in enumerate(symbols[:1]):
            noise = rng.normal(0, 0.004, n_days)
            close = base * np.cumprod(1 + noise) / np.cumprod(1 + noise)[0]
            # Force a few pullback setups mid-series
            high = close * 1.008
            low = close * 0.992
            open_ = close
            vol = rng.integers(50_000, 200_000, n_days)
            symbol_candles[sym] = pd.DataFrame(
                {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
                index=idx,
            )
    return sector_data, symbol_candles


def export_calibrated_params(
    result: BacktestResult,
    path: Optional[Path] = None,
    base_params: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Write params.json with last backtest summary nested under calibration."""
    params = dict(base_params or load_params())
    params["calibration"] = {
        "total_return_pct": result.total_return_pct,
        "win_rate": result.win_rate,
        "expectancy_r": result.expectancy_r,
        "max_drawdown_pct": result.max_drawdown_pct,
        "num_trades": result.num_trades,
        "with_cycle_filter": result.with_cycle_filter,
    }
    out = path or DEFAULT_PARAMS_PATH
    with open(out, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2)
        f.write("\n")
    return params


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sectors, symbols = synthetic_demo_data()
    filtered = run_swing_backtest(
        sectors, symbols, capital=100_000.0, use_cycle_filter=True
    )
    baseline = run_swing_backtest(
        sectors, symbols, capital=100_000.0, use_cycle_filter=False
    )
    summary = {
        "with_cycle": {
            "total_return_pct": filtered.total_return_pct,
            "win_rate": filtered.win_rate,
            "expectancy_r": filtered.expectancy_r,
            "max_drawdown_pct": filtered.max_drawdown_pct,
            "num_trades": filtered.num_trades,
        },
        "baseline": {
            "total_return_pct": baseline.total_return_pct,
            "win_rate": baseline.win_rate,
            "expectancy_r": baseline.expectancy_r,
            "max_drawdown_pct": baseline.max_drawdown_pct,
            "num_trades": baseline.num_trades,
        },
        "cycle_edge_return_pct": round(
            filtered.total_return_pct - baseline.total_return_pct, 2
        ),
    }
    print(json.dumps(summary, indent=2))
    export_calibrated_params(filtered)
    print(f"Updated {DEFAULT_PARAMS_PATH}")
