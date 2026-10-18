"""Groww Cloud CNC swing strategy entrypoint.

Deploy: copy this package (or run `python -m strategies.groww_swing`) on Groww Cloud.
See DEPLOY.md. Keep dry_run=true until you are ready to live-trade.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PKG = Path(__file__).resolve().parent
if str(_PKG.parent.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent.parent))
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

try:
    from strategies.groww_swing.broker import GrowwBroker
    from strategies.groww_swing.cycle_filter import compute_cycle_bias
    from strategies.groww_swing.regime_router import eligible_approaches, router_snapshot
    from strategies.groww_swing.risk import filter_and_size
    from strategies.groww_swing.setups import scan_universe
    from strategies.groww_swing.universe import (
        SECTOR_ETFS,
        SECTOR_INDEX_SYMBOLS,
        SECTOR_PROXY_ETF,
        sector_for_symbol,
        symbols_for_sectors,
    )
except ImportError:
    from broker import GrowwBroker
    from cycle_filter import compute_cycle_bias
    from regime_router import eligible_approaches, router_snapshot
    from risk import filter_and_size
    from setups import scan_universe
    from universe import (
        SECTOR_ETFS,
        SECTOR_INDEX_SYMBOLS,
        SECTOR_PROXY_ETF,
        sector_for_symbol,
        symbols_for_sectors,
    )

logger = logging.getLogger("groww_swing")
STATE_PATH = _PKG / "positions_state.json"


def load_params(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or (_PKG / "params.json")
    if not p.exists():
        p = Path(__file__).with_name("params.json")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _sector_proxy_map() -> Dict[str, str]:
    out = dict(SECTOR_PROXY_ETF)
    out.update(SECTOR_INDEX_SYMBOLS)
    return out


def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"positions": {}}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"positions": {}}


def _save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _order_accepted(order_resp: Dict[str, Any], *, dry_run: bool) -> bool:
    if dry_run:
        return True
    if not order_resp:
        return False
    status = str(
        order_resp.get("order_status")
        or order_resp.get("status")
        or order_resp.get("payload", {}).get("order_status")
        or ""
    ).upper()
    if status in {"REJECTED", "CANCELLED", "FAILED", "ERROR"}:
        return False
    # Groww dry IDs or real ids
    if order_resp.get("groww_order_id") or order_resp.get("order_id") or order_resp.get("dry_run"):
        return True
    return status in {"", "OPEN", "ACKED", "APPROVED", "TRIGGER_PENDING", "COMPLETED", "EXECUTED", "DRY_RUN"}


def _estimate_open_risk_rupees(
    holdings: List[Dict[str, Any]],
    state: Dict[str, Any],
    params: Dict[str, Any],
) -> List[float]:
    """Risk from open CNC positions (state stop if known, else ~3% notional)."""
    risks: List[float] = []
    positions = state.get("positions") or {}
    fallback_pct = float(params.get("open_risk_fallback_pct", 0.03))
    for h in holdings:
        sym = str(h["trading_symbol"]).upper()
        qty = float(h.get("quantity") or 0)
        avg = float(h.get("average_price") or 0)
        meta = positions.get(sym) or {}
        stop = meta.get("stop")
        entry = float(meta.get("entry") or avg or 0)
        if stop is not None and entry > float(stop) and qty > 0:
            risks.append(qty * (entry - float(stop)))
        elif qty > 0 and avg > 0:
            risks.append(qty * avg * fallback_pct)
    return risks


def manage_time_exits(
    br: GrowwBroker,
    *,
    holdings: List[Dict[str, Any]],
    params: Dict[str, Any],
    state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """CNC market sell when held >= max_hold_days (tracked in positions_state.json)."""
    max_hold = int(params.get("max_hold_days", 20))
    exchange = str(params.get("exchange") or "NSE")
    dry = bool(params.get("dry_run", True))
    positions = state.setdefault("positions", {})
    today = datetime.now(timezone.utc).date()
    exits: List[Dict[str, Any]] = []

    held_syms = {str(h["trading_symbol"]).upper() for h in holdings}
    # Drop state for symbols no longer held
    for sym in list(positions.keys()):
        if sym not in held_syms:
            positions.pop(sym, None)

    for h in holdings:
        sym = str(h["trading_symbol"]).upper()
        qty = int(float(h.get("quantity") or 0))
        if qty < 1:
            continue
        meta = positions.get(sym)
        if not meta or not meta.get("entry_date"):
            continue
        try:
            entry_d = datetime.fromisoformat(str(meta["entry_date"])[:10]).date()
        except Exception:
            continue
        held_days = (today - entry_d).days
        if held_days < max_hold:
            continue
        logger.info("Time exit %s held=%sd qty=%s", sym, held_days, qty)
        if dry:
            resp = {
                "dry_run": True,
                "action": "TIME_EXIT_SELL",
                "trading_symbol": sym,
                "quantity": qty,
            }
        else:
            resp = br.place_cnc_sell(
                trading_symbol=sym,
                quantity=qty,
                order_type="MARKET",
                exchange=exchange,
            )
        positions.pop(sym, None)
        exits.append({"symbol": sym, "held_days": held_days, "response": resp})
    return exits


def run_once(
    *,
    broker: Optional[GrowwBroker] = None,
    params: Optional[Dict[str, Any]] = None,
    capital: Optional[float] = None,
) -> Dict[str, Any]:
    p = params or load_params()
    dry = bool(p.get("dry_run", True))
    br = broker or GrowwBroker(dry_run=dry)
    state = _load_state()

    candle_days = int(p.get("scan_history_days") or 260)
    sector_data = br.fetch_sector_closes(SECTOR_PROXY_ETF, days=candle_days)
    if len(sector_data) < 4:
        sector_data = br.fetch_sector_closes(
            _sector_proxy_map(),
            days=candle_days,
            etf_fallback=SECTOR_PROXY_ETF,
        )

    vix_val = None
    vix_sym = str(p.get("vix_symbol") or "INDIA VIX")
    try:
        vix_df = br.get_historical_candles(
            trading_symbol=vix_sym,
            days=60,
            groww_symbol=f"NSE-{vix_sym}",
        )
        if not vix_df.empty:
            vix_val = float(vix_df["close"].iloc[-1])
    except Exception as exc:
        logger.warning("VIX fetch skipped: %s", exc)

    bias = compute_cycle_bias(sector_data, vix_value=vix_val, params=p)
    approaches = eligible_approaches(bias, p)
    logger.info(
        "Cycle: phase=%s sub=%s risk_off=%s allowed=%s approaches=%s",
        bias.get("phase"),
        bias.get("sub_phase"),
        bias.get("risk_off"),
        bias.get("allowed_sectors"),
        approaches,
    )

    result: Dict[str, Any] = {
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
            )
            if k in bias
        },
        "router": router_snapshot(bias, p),
        "orders": [],
        "exits": [],
        "setups": [],
        "dry_run": dry,
    }
    result["_sector_frames"] = sector_data

    holdings = br.get_holdings()
    # Time-based exits even when flat/risk-off
    exits = manage_time_exits(br, holdings=holdings, params=p, state=state)
    result["exits"] = exits
    if exits:
        holdings = br.get_holdings()
    _save_state(state)

    if bias.get("risk_off") or not bias.get("allowed_sectors") or not approaches:
        result["message"] = "No new risk — cycle/router flat/risk-off"
        return result

    allowed = list(bias["allowed_sectors"])
    symbols = symbols_for_sectors(allowed)
    symbol_sector: Dict[str, str] = {}
    for sec in allowed:
        for sym in SECTOR_ETFS.get(sec, []):
            symbol_sector[sym.upper()] = sec

    candles = br.fetch_symbol_candles(symbols, days=min(candle_days, 180))
    bench_sym = str(p.get("benchmark_symbol") or "NIFTY")
    bench_df = br.get_historical_candles(
        trading_symbol=bench_sym,
        days=min(candle_days, 180),
        groww_symbol=f"NSE-{bench_sym}",
    )
    bench_close = bench_df["close"] if not bench_df.empty else None

    setups = scan_universe(
        candles,
        symbol_sector=symbol_sector,
        params=p,
        benchmark_close=bench_close,
        bias=bias,
        approaches=approaches,
    )
    result["setups"] = setups

    open_symbols = [h["trading_symbol"] for h in holdings]
    open_sectors = [
        symbol_sector.get(s.upper()) or sector_for_symbol(s) or ""
        for s in open_symbols
    ]
    open_risk = _estimate_open_risk_rupees(holdings, state, p)

    cap = capital
    if cap is None:
        try:
            cap = br.estimate_capital(fallback=float(os.getenv("SWING_CAPITAL", "100000")))
        except Exception:
            cap = float(os.getenv("SWING_CAPITAL", "100000"))

    sized = filter_and_size(
        setups,
        capital=float(cap),
        params=p,
        open_symbols=open_symbols,
        open_sectors=open_sectors,
        open_risk_rupees=open_risk,
    )
    result["capital"] = cap
    result["sized"] = sized

    exchange = str(p.get("exchange") or "NSE")
    order_type = str(p.get("order_type") or "LIMIT")
    offset = float(p.get("limit_offset_pct") or 0.001)
    # Default False — dual full-qty GTT is unsafe; stop-only protective leg
    place_target_gtt = bool(p.get("place_target_gtt", False))
    fill_wait_s = float(p.get("fill_wait_seconds", 2.0))

    positions = state.setdefault("positions", {})
    for trade in sized:
        limit_px = None
        if order_type.upper() == "LIMIT":
            limit_px = round(float(trade["entry"]) * (1 + offset), 2)
        order_resp = br.place_cnc_buy(
            trading_symbol=trade["symbol"],
            quantity=int(trade["quantity"]),
            price=limit_px,
            order_type=order_type,
            exchange=exchange,
        )
        gtt_stop = None
        gtt_tgt = None
        if _order_accepted(order_resp, dry_run=dry):
            if not dry and fill_wait_s > 0:
                time.sleep(fill_wait_s)
            gtt_stop = br.place_gtt_stop(
                trading_symbol=trade["symbol"],
                quantity=int(trade["quantity"]),
                trigger_price=float(trade["stop"]),
                exchange=exchange,
            )
            if place_target_gtt:
                gtt_tgt = br.place_gtt_target(
                    trading_symbol=trade["symbol"],
                    quantity=int(trade["quantity"]),
                    trigger_price=float(trade["target"]),
                    exchange=exchange,
                )
            positions[str(trade["symbol"]).upper()] = {
                "entry_date": datetime.now(timezone.utc).date().isoformat(),
                "entry": float(trade["entry"]),
                "stop": float(trade["stop"]),
                "target": float(trade["target"]),
                "approach": trade.get("setup") or trade.get("approach"),
                "quantity": int(trade["quantity"]),
            }
        else:
            logger.warning("Skip GTT — order not accepted for %s: %s", trade["symbol"], order_resp)

        result["orders"].append(
            {
                "trade": trade,
                "approach": trade.get("setup") or trade.get("approach"),
                "order": order_resp,
                "gtt_stop": gtt_stop,
                "gtt_target": gtt_tgt,
            }
        )

    _save_state(state)
    result["message"] = (
        f"Processed {len(sized)} entries via {approaches} "
        f"({'dry-run' if dry else 'LIVE'})"
    )
    return result


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    params = load_params()
    if os.getenv("SWING_LIVE", "").lower() in {"1", "true", "yes"}:
        params["dry_run"] = False
    out = run_once(params=params)
    # Drop non-JSON frames
    out.pop("_sector_frames", None)
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
