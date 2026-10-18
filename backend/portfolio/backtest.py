import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.config import DEFAULT_START_DATE
from backend.portfolio.risk import compute_max_drawdown
from backend.models.schemas import BacktestResult

logger = logging.getLogger(__name__)


class BacktestEngine:
    """Walk-forward backtesting for sector rotation strategy."""

    def __init__(self) -> None:
        self._results: Optional[BacktestResult] = None
        self._equity_curve: Optional[pd.DataFrame] = None

    def run_walk_forward(
        self,
        sector_data: Dict[str, pd.DataFrame],
        regime_history: pd.DataFrame,
        allocation_fn,
        start_train: str = "2005-01-01",
        end_train: str = "2012-12-31",
        test_start: str = "2013-01-01",
        test_end: Optional[str] = None,
        rebalance_freq: str = "QS",
        transaction_cost: float = 0.001,
    ) -> BacktestResult:
        test_end = test_end or datetime.now().strftime("%Y-%m-%d")

        benchmark_returns = self._compute_equal_weight_benchmark(sector_data)

        rebalance_dates = pd.date_range(test_start, test_end, freq=rebalance_freq)
        if rebalance_dates.empty:
            return BacktestResult(
                strategy_cagr=0.0, strategy_sharpe=0.0, strategy_max_drawdown=0.0,
                benchmark_cagr=0.0, benchmark_sharpe=0.0, benchmark_max_drawdown=0.0,
                alpha=0.0, win_rate=0.0, num_rebalances=0,
            )

        portfolio_value = 1.0
        daily_values: List[Dict] = []
        prev_weights: Dict[str, float] = {}

        for i, rb_date in enumerate(rebalance_dates):
            if i == 0:
                weights = allocation_fn(regime_history.loc[regime_history.index <= rb_date])
            else:
                retrain_end = rb_date - timedelta(days=1)
                weights = allocation_fn(
                    regime_history.loc[regime_history.index <= retrain_end]
                )

            if i < len(rebalance_dates) - 1:
                period_end = rebalance_dates[i + 1]
            else:
                period_end = pd.Timestamp(test_end)

            if i > 0 and prev_weights:
                turnover = sum(
                    abs(weights.get(s, 0.0) - prev_weights.get(s, 0.0))
                    for s in set(list(weights.keys()) + list(prev_weights.keys()))
                )
                portfolio_value *= (1 - turnover * transaction_cost)

            period_value = self._compute_period_return(
                weights, sector_data, rb_date, period_end
            )

            portfolio_value *= period_value
            daily_values.append({
                "date": rb_date,
                "portfolio_value": portfolio_value,
            })

            prev_weights = weights

        equity_curve = pd.DataFrame(daily_values).set_index("date")

        monthly_returns = equity_curve["portfolio_value"].pct_change().dropna()
        months_per_year = 12
        cagr = float(equity_curve["portfolio_value"].iloc[-1]) ** (months_per_year / len(monthly_returns)) - 1 if len(monthly_returns) > 0 else 0.0
        sharpe = float(monthly_returns.mean() / monthly_returns.std() * np.sqrt(12)) if monthly_returns.std() > 0 else 0.0
        strategy_dd, _, _ = compute_max_drawdown(equity_curve["portfolio_value"])

        bm_cagr = float(benchmark_returns.mean() * 12)
        bm_sharpe = float(benchmark_returns.mean() / benchmark_returns.std() * np.sqrt(12)) if benchmark_returns.std() > 0 else 0.0
        bm_cum = (1 + benchmark_returns).cumprod()
        bm_dd, _, _ = compute_max_drawdown(bm_cum)

        alpha = cagr - bm_cagr
        win_rate = float((monthly_returns > 0).sum() / len(monthly_returns)) if len(monthly_returns) > 0 else 0.0

        self._results = BacktestResult(
            strategy_cagr=round(cagr, 4),
            strategy_sharpe=round(sharpe, 4),
            strategy_max_drawdown=round(strategy_dd, 4),
            benchmark_cagr=round(bm_cagr, 4),
            benchmark_sharpe=round(bm_sharpe, 4),
            benchmark_max_drawdown=round(bm_dd, 4),
            alpha=round(alpha, 4),
            win_rate=round(win_rate, 4),
            num_rebalances=len(rebalance_dates),
        )

        self._equity_curve = equity_curve
        return self._results

    def _compute_period_return(
        self,
        weights: Dict[str, float],
        sector_data: Dict[str, pd.DataFrame],
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> float:
        period_return = 1.0
        total_weight = 0.0

        for sector, weight in weights.items():
            if sector not in sector_data or sector_data[sector].empty:
                continue
            df = sector_data[sector]
            close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())

            in_period = close[(close.index >= start) & (close.index <= end)]
            if len(in_period) >= 2:
                sector_ret = float(in_period.iloc[-1] / in_period.iloc[0])
                period_return += weight * (sector_ret - 1.0)
                total_weight += weight

        if total_weight > 0 and total_weight < 1.0:
            cash_return = 1.0 + (1.0 - total_weight) * 0.0
            period_return = (period_return - 1.0) * total_weight + cash_return

        return period_return

    def _compute_equal_weight_benchmark(
        self,
        sector_data: Dict[str, pd.DataFrame],
    ) -> pd.Series:
        daily_returns: Dict[str, pd.Series] = {}
        for sector, df in sector_data.items():
            if df.empty:
                continue
            close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
            daily_returns[sector] = close.pct_change().dropna()

        if not daily_returns:
            return pd.Series(dtype=float)

        ret_df = pd.DataFrame(daily_returns).dropna()
        n = ret_df.shape[1]
        if n == 0:
            return pd.Series(dtype=float)

        return ret_df.mean(axis=1)

    @property
    def results(self) -> Optional[BacktestResult]:
        return self._results

    @property
    def equity_curve(self) -> Optional[pd.DataFrame]:
        return self._equity_curve


class BenchmarkComparison:
    """Compare strategy against multiple benchmarks."""

    @staticmethod
    def compare(
        strategy_returns: pd.Series,
        benchmarks: Dict[str, pd.Series],
    ) -> Dict[str, Dict[str, float]]:
        comparisons: Dict[str, Dict[str, float]] = {}
        for name, bm_returns in benchmarks.items():
            aligned_strat, aligned_bm = strategy_returns.align(bm_returns, join="inner")
            if len(aligned_strat) < 12:
                continue

            excess = aligned_strat - aligned_bm
            tracking_error = float(excess.std() * np.sqrt(12))
            information_ratio = float(excess.mean() / excess.std() * np.sqrt(12)) if excess.std() > 0 else 0.0

            strat_cagr = float(aligned_strat.mean() * 12)
            bm_cagr = float(aligned_bm.mean() * 12)

            comparisons[name] = {
                "strategy_cagr": round(strat_cagr, 4),
                "benchmark_cagr": round(bm_cagr, 4),
                "alpha": round(strat_cagr - bm_cagr, 4),
                "information_ratio": round(information_ratio, 4),
                "tracking_error": round(tracking_error, 4),
            }

        return comparisons
