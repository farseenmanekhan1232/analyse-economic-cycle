"""Full Groww daily-cache evaluation (cycle vs baseline + per-approach stats).

Usage:
  python -m strategies.groww_swing.eval
  python -m strategies.groww_swing.eval --capital 100000 --rebalance 2

Uses data/groww_cache/ only (no live network). Refresh cache first:
  POST /api/swing/cache/refresh?full_history=true
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_PKG = Path(__file__).resolve().parent
if str(_PKG.parent.parent) not in sys.path:
    sys.path.insert(0, str(_PKG.parent.parent))

logger = logging.getLogger("groww_swing.eval")


def run_full_eval(
    *,
    capital: float = 100_000.0,
    rebalance_every_n_days: int = 2,
    params: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
    out_path: Optional[Path] = None,
) -> Dict[str, Any]:
    from strategies.groww_swing.backtest import load_params, run_swing_backtest
    from strategies.groww_swing.panel_cache import (
        DEFAULT_CACHE_DIR,
        cache_history_summary,
        load_cached_backtest_panels,
        read_manifest,
    )

    root = cache_dir or DEFAULT_CACHE_DIR
    summary = cache_history_summary(root)
    if not summary.get("cache_ready"):
        raise RuntimeError(
            f"Groww cache not usable at {root}. "
            "Run full-history cache refresh first."
        )

    p = dict(params or load_params())
    sectors, symbols, bench = load_cached_backtest_panels(cache_dir=root)
    if not sectors or not symbols:
        raise RuntimeError("Cache panels empty")

    kwargs: Dict[str, Any] = {
        "capital": capital,
        "params": p,
        "rebalance_every_n_days": rebalance_every_n_days,
    }
    if bench is not None:
        kwargs["benchmark"] = bench

    logger.info(
        "Eval start: sectors=%s symbols=%s rebalance=%s capital=%s",
        len(sectors),
        len(symbols),
        rebalance_every_n_days,
        capital,
    )
    filtered = run_swing_backtest(sectors, symbols, use_cycle_filter=True, **kwargs)
    baseline = run_swing_backtest(sectors, symbols, use_cycle_filter=False, **kwargs)

    report: Dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "groww_cache_full",
        "interval": "day",
        "cache": summary,
        "manifest": read_manifest(root),
        "capital": capital,
        "rebalance_every_n_days": rebalance_every_n_days,
        "enabled_approaches": p.get("enabled_approaches"),
        "with_cycle_filter": {
            "total_return_pct": filtered.total_return_pct,
            "win_rate": filtered.win_rate,
            "expectancy_r": filtered.expectancy_r,
            "max_drawdown_pct": filtered.max_drawdown_pct,
            "num_trades": filtered.num_trades,
            "ending_capital": filtered.ending_capital,
            "approach_stats": filtered.approach_stats,
        },
        "baseline_technicals_only": {
            "total_return_pct": baseline.total_return_pct,
            "win_rate": baseline.win_rate,
            "expectancy_r": baseline.expectancy_r,
            "max_drawdown_pct": baseline.max_drawdown_pct,
            "num_trades": baseline.num_trades,
            "ending_capital": baseline.ending_capital,
            "approach_stats": baseline.approach_stats,
        },
        "cycle_edge_return_pct": round(
            filtered.total_return_pct - baseline.total_return_pct, 2
        ),
        "cycle_edge_expectancy_r": round(
            filtered.expectancy_r - baseline.expectancy_r, 3
        ),
        "notes": [
            "Groww history from ~2020 only (vendor limit) — not 20 years.",
            "Primary timeframe is daily; 15m is not used for this eval.",
        ],
    }

    # Recommend disables: E[R] < 0 with enough trades
    kills = []
    for aid, st in (filtered.approach_stats or {}).items():
        n = int(st.get("num_trades") or 0)
        er = float(st.get("expectancy_r") or 0)
        if n >= 8 and er < 0:
            kills.append({"approach": aid, "num_trades": n, "expectancy_r": er})
    report["recommended_disable"] = kills

    dest = out_path or (root / "last_eval.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["written_to"] = str(dest)
    logger.info(
        "Eval done: cycle=%s%% baseline=%s%% edge=%s trades=%s → %s",
        filtered.total_return_pct,
        baseline.total_return_pct,
        report["cycle_edge_return_pct"],
        filtered.num_trades,
        dest,
    )
    return report


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(description="Full Groww daily-cache swing eval")
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--rebalance", type=int, default=2, help="Rebalance every N days")
    ap.add_argument("--out", type=str, default="", help="Output JSON path")
    args = ap.parse_args()
    out = Path(args.out) if args.out else None
    try:
        report = run_full_eval(
            capital=args.capital,
            rebalance_every_n_days=args.rebalance,
            out_path=out,
        )
    except Exception as exc:
        logger.error("%s", exc)
        sys.exit(1)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
