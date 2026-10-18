"""Position sizing and portfolio heat guards for CNC swings."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence


def shares_for_risk(
    *,
    capital: float,
    entry: float,
    stop: float,
    risk_pct: float,
) -> int:
    """Integer share count so dollar risk ≈ capital * risk_pct."""
    if capital <= 0 or entry <= 0 or stop <= 0 or entry <= stop:
        return 0
    risk_rupees = capital * risk_pct
    per_share = entry - stop
    if per_share <= 0:
        return 0
    qty = int(risk_rupees // per_share)
    # Cap so notional does not exceed capital
    max_by_cash = int(capital // entry)
    return max(0, min(qty, max_by_cash))


def portfolio_heat(
    open_risks: Sequence[float],
    capital: float,
) -> float:
    """Fraction of capital currently at risk across open stops."""
    if capital <= 0:
        return 1.0
    return float(sum(max(0.0, r) for r in open_risks) / capital)


def filter_and_size(
    setups: Sequence[Mapping[str, Any]],
    *,
    capital: float,
    params: Mapping[str, Any],
    open_symbols: Optional[Sequence[str]] = None,
    open_sectors: Optional[Sequence[str]] = None,
    open_risk_rupees: Optional[Sequence[float]] = None,
) -> List[Dict[str, Any]]:
    """Apply concentration / heat limits and attach quantity."""
    open_syms = {s.upper() for s in (open_symbols or [])}
    sector_counts: Dict[str, int] = {}
    for sec in open_sectors or []:
        sector_counts[sec] = sector_counts.get(sec, 0) + 1

    max_open = int(params.get("max_open_trades", 4))
    max_sector = int(params.get("max_sector_trades", 2))
    risk_pct = float(params.get("risk_pct_per_trade", 0.0075))
    max_heat = float(params.get("max_portfolio_heat", 0.04))

    current_open = len(open_syms)
    heat = portfolio_heat(open_risk_rupees or [], capital)
    sized: List[Dict[str, Any]] = []

    for raw in setups:
        if current_open + len(sized) >= max_open:
            break
        symbol = str(raw["symbol"]).upper()
        if symbol in open_syms:
            continue
        sector = str(raw.get("sector") or "")
        if sector_counts.get(sector, 0) >= max_sector:
            continue

        entry = float(raw["entry"])
        stop = float(raw["stop"])
        qty = shares_for_risk(
            capital=capital,
            entry=entry,
            stop=stop,
            risk_pct=risk_pct,
        )
        if qty < 1:
            continue

        trade_risk = qty * (entry - stop)
        if heat + trade_risk / capital > max_heat:
            continue

        order = dict(raw)
        order["quantity"] = qty
        order["notional"] = round(qty * entry, 2)
        order["risk_rupees"] = round(trade_risk, 2)
        order["risk_pct"] = round(trade_risk / capital * 100, 3) if capital else 0.0
        sized.append(order)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        heat += trade_risk / capital

    return sized
