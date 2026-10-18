import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.config import DEFAULT_START_DATE, SECTOR_INDICES
from backend.data.cache_manager import CacheManager
from backend.data.kite_client import KiteClient
from backend.analysis.regime_detection import RegimeDetector
from backend.models.schemas import SectorPerformanceMetrics

logger = logging.getLogger(__name__)


class SectorAnalyzer:
    """Risk-adjusted sector performance analysis across economic regimes."""

    def __init__(
        self,
        kite: Optional[KiteClient] = None,
        cache: Optional[CacheManager] = None,
        risk_free_rate: float = 0.04,
    ) -> None:
        self.kite = kite
        self.cache = cache or CacheManager()
        self.risk_free_rate = risk_free_rate
        self._results: Dict[str, pd.DataFrame] = {}

    def analyze_sector(
        self,
        sector_key: str,
        sector_df: pd.DataFrame,
        regime_probs: pd.DataFrame,
    ) -> List[SectorPerformanceMetrics]:
        if sector_df.empty or regime_probs.empty:
            return []

        close = sector_df.get("close", sector_df.iloc[:, 0] if sector_df.shape[1] == 1 else pd.Series())
        quarterly = close.resample("QE").last()
        returns = quarterly.pct_change().dropna()

        aligned_regimes = regime_probs.reindex(returns.index, method="ffill")
        if aligned_regimes.empty:
            return []

        metrics: List[SectorPerformanceMetrics] = []
        regimes = ["recovery", "expansion", "contraction", "trough"]
        available_regimes = [r for r in regimes if r in aligned_regimes.columns]

        for regime in available_regimes:
            regime_mask = aligned_regimes[regime] > 0.5
            regime_returns = returns[regime_mask]

            if len(regime_returns) < 3:
                continue

            mean_ret = float(regime_returns.mean() * 100)
            std_ret = float(regime_returns.std() * 100)
            sharpe = self._compute_sharpe(regime_returns)
            sortino = self._compute_sortino(regime_returns)
            max_dd = self._compute_max_drawdown(close, regime_mask)
            win_rate = float((regime_returns > 0).sum() / len(regime_returns))

            metrics.append(SectorPerformanceMetrics(
                sector=sector_key,
                regime=regime,
                mean_return=round(mean_ret, 2),
                std_return=round(std_ret, 2),
                sharpe_ratio=round(sharpe, 3),
                sortino_ratio=round(sortino, 3),
                max_drawdown=round(max_dd, 2),
                win_rate=round(win_rate, 2),
                num_quarters=len(regime_returns),
            ))

        return metrics

    def analyze_all_sectors(
        self,
        sector_data: Dict[str, pd.DataFrame],
        regime_probs: pd.DataFrame,
    ) -> Dict[str, List[SectorPerformanceMetrics]]:
        self._results = {}
        for sector_key, df in sector_data.items():
            metrics = self.analyze_sector(sector_key, df, regime_probs)
            if metrics:
                self._results[sector_key] = metrics

        return self._results

    def _compute_sharpe(self, returns: pd.Series) -> float:
        excess = returns - (self.risk_free_rate / 4)
        if excess.std() == 0:
            return 0.0
        return float(excess.mean() / excess.std() * np.sqrt(4))

    def _compute_sortino(self, returns: pd.Series) -> float:
        excess = returns - (self.risk_free_rate / 4)
        downside = excess[excess < 0]
        if len(downside) == 0 or downside.std() == 0:
            return float("inf") if excess.mean() > 0 else 0.0
        return float(excess.mean() / downside.std() * np.sqrt(4))

    def _compute_max_drawdown(self, close: pd.Series, regime_mask: pd.Series) -> float:
        regime_close = close[close.index.isin(regime_mask[regime_mask].index)]
        if len(regime_close) < 2:
            return 0.0

        peak = regime_close.expanding().max()
        drawdown = (regime_close - peak) / peak
        return float(drawdown.min() * 100)

    def compute_correlation_matrix(self, sector_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        returns_dict: Dict[str, pd.Series] = {}
        for key, df in sector_data.items():
            if df.empty:
                continue
            close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
            daily_ret = close.pct_change().dropna()
            if not daily_ret.empty:
                returns_dict[key] = daily_ret

        if not returns_dict:
            return pd.DataFrame()

        return pd.DataFrame(returns_dict).corr()

    def compute_beta_to_nifty(
        self, sector_key: str, sector_df: pd.DataFrame, nifty_df: Optional[pd.DataFrame] = None
    ) -> Optional[float]:
        if sector_df.empty or nifty_df is None or nifty_df.empty:
            return None

        sector_close = sector_df.get("close", sector_df.iloc[:, 0])
        nifty_close = nifty_df.get("close", nifty_df.iloc[:, 0])

        sector_ret = sector_close.pct_change().dropna()
        nifty_ret = nifty_close.pct_change().dropna()

        aligned = pd.concat([sector_ret, nifty_ret], axis=1).dropna()
        if len(aligned) < 20:
            return None

        cov = aligned.cov().iloc[0, 1]
        var = aligned.iloc[:, 1].var()
        if var == 0:
            return None

        return float(cov / var)

    def compute_factor_exposures(
        self, sector_key: str, sector_df: pd.DataFrame, nifty_df: Optional[pd.DataFrame] = None
    ) -> Dict[str, float]:
        exposures: Dict[str, float] = {}

        close = sector_df.get("close", sector_df.iloc[:, 0] if sector_df.shape[1] == 1 else pd.Series())
        returns = close.pct_change().dropna()

        exposures["volatility"] = float(returns.std() * np.sqrt(252))
        exposures["skewness"] = float(returns.skew())
        exposures["kurtosis"] = float(returns.kurtosis())

        beta = self.compute_beta_to_nifty(sector_key, sector_df, nifty_df)
        exposures["beta"] = beta if beta is not None else 1.0

        return exposures

    def get_top_sectors_by_regime(
        self,
        regime: str,
        metric: str = "sharpe_ratio",
        top_n: int = 3,
    ) -> List[Tuple[str, float]]:
        scored: List[Tuple[str, float]] = []
        for sector_key, metrics_list in self._results.items():
            for m in metrics_list:
                if m.regime == regime:
                    val = getattr(m, metric, 0)
                    scored.append((sector_key, val))
                    break

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_n]

    @property
    def results(self) -> Dict[str, List[SectorPerformanceMetrics]]:
        return self._results


def compute_recent_momentum(
    sector_data: Dict[str, pd.DataFrame],
    lookback_days: int = 90,
) -> Dict[str, float]:
    momentum: Dict[str, float] = {}
    for key, df in sector_data.items():
        if df.empty:
            momentum[key] = 0.0
            continue
        close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
        if len(close) < lookback_days:
            momentum[key] = 0.0
            continue
        recent = close.iloc[-lookback_days:]
        momentum[key] = float((recent.iloc[-1] / recent.iloc[0] - 1) * 100)
    return momentum


def compute_composite_score(
    sector_key: str,
    metrics: List[SectorPerformanceMetrics],
    current_regime: str,
    momentum_pct: float,
    signal_bias: float,
    sub_phase_sectors: Dict[str, List[str]],
    sub_phase: str,
    *,
    sub_phase_fits: Optional[Dict[str, float]] = None,
) -> Dict:
    """Compute a 0-100 conviction score for a sector.

    Sub-phase contribution is blended (not 5/10/20 cliffs). Optional
    sub_phase_fits maps phase_type → 0–1 soft fit from cycle vote score.
    """

    regime_metric = None
    for m in metrics:
        if m.regime == current_regime:
            regime_metric = m
            break

    historical_score = 0.0
    if regime_metric and regime_metric.mean_return > 0:
        sharpe = max(min(regime_metric.sharpe_ratio, 2.0), -1.0)
        historical_score = (sharpe + 1) / 3.0 * 30

    # Smooth momentum: linear from -10% → 0 pts, 0% → 12.5, +10% → 25
    mom = float(momentum_pct)
    if mom >= 10:
        momentum_score = 25.0
    elif mom <= -10:
        momentum_score = 0.0
    else:
        momentum_score = (mom + 10.0) / 20.0 * 25.0

    # Symmetric signal score around neutral bias 0 → mid points
    # bias typically in [-1, 1]; clamp contribution
    bias = max(min(float(signal_bias), 1.0), -1.0)
    signal_score = (bias + 1.0) / 2.0 * 25.0 + 5.0  # 5–30 range

    fits = sub_phase_fits or {}
    best_blend = 0.0
    listed_anywhere = False
    for phase_type, sectors in sub_phase_sectors.items():
        sector_list = sectors if isinstance(sectors, (list, tuple, set)) else []
        if sector_key not in sector_list:
            continue
        listed_anywhere = True
        soft = float(fits.get(phase_type, 1.0 if phase_type == sub_phase else 0.35))
        if phase_type == sub_phase:
            soft = max(soft, 0.85)
        best_blend = max(best_blend, soft)

    if best_blend > 0:
        # Blend 8–20 instead of hard 5/10/20
        sub_phase_score = 8.0 + best_blend * 12.0
    elif listed_anywhere:
        sub_phase_score = 8.0
    else:
        sub_phase_score = 5.0

    total = min(round(historical_score + momentum_score + signal_score + sub_phase_score, 0), 100)
    return {
        "score": total,
        "historical_pct": round(historical_score, 1),
        "momentum_pct": round(momentum_score, 1),
        "signal_pct": round(signal_score, 1),
        "sub_phase_pct": round(sub_phase_score, 1),
    }


def compute_exit_signals(
    sector_key: str,
    sector_df: pd.DataFrame,
    metrics: List[SectorPerformanceMetrics],
    current_regime: str,
    phase_progress: float,
    signals: Dict,
    recent_momentum: float = 0.0,
    composite_score: float = 50.0,
    sub_phase_fit: bool = False,
) -> Dict:
    """Compute sector-specific exit signals: hold period, stop loss, exit triggers.

    Hold range varies by phase progress, volatility, momentum, score, and cycle fit.
    recent_momentum is a percentage (e.g. 5.2 for +5.2%).
    """
    close = sector_df.get("close", sector_df.iloc[:, 0] if sector_df.shape[1] == 1 else pd.Series())
    if close.empty or len(close) < 20:
        return {"hold_for": "Unknown", "exit_trigger": "Insufficient data", "stop_loss_pct": 0.0}

    returns = close.pct_change().dropna()
    volatility = float(returns.std() * np.sqrt(252)) if len(returns) > 20 else 0.15
    stop_loss = round(volatility * 2.0 * 100, 1)

    hold_for = _compute_hold_range(
        phase_progress=phase_progress,
        volatility=volatility,
        recent_momentum=recent_momentum,
        composite_score=composite_score,
        sub_phase_fit=sub_phase_fit,
    )

    triggers = []
    for name, sig in signals.items():
        if not hasattr(sig, "direction"):
            continue
        if sig.direction == "bearish" and sig.confidence > 0.5:
            if name == "vix" and sector_key in ("BANK", "AUTO", "METAL", "REALTY"):
                triggers.append("VIX > 25")
            elif name == "india_vix" and sector_key in ("BANK", "AUTO", "METAL", "REALTY"):
                triggers.append("India VIX elevated")
            elif name == "crude_oil" and sector_key in ("AUTO", "CONSUMER_DURABLES", "FMCG"):
                triggers.append("Oil spike")
            elif name == "dollar_index" and sector_key in ("BANK", "AUTO", "PSU_BANK", "REALTY"):
                triggers.append("Dollar strengthening")
            elif name == "inrusd" and sector_key in ("AUTO", "OIL_GAS", "CONSUMER_DURABLES"):
                triggers.append("INR depreciation")

    exit_trigger = "; ".join(triggers[:2]) if triggers else f"Stop-loss: -{stop_loss}%"

    return {
        "hold_for": hold_for,
        "exit_trigger": exit_trigger,
        "stop_loss_pct": stop_loss,
    }


def _compute_hold_range(
    phase_progress: float,
    volatility: float,
    recent_momentum: float,
    composite_score: float,
    sub_phase_fit: bool,
) -> str:
    """Derive a concrete month range for this sector."""
    progress = min(max(float(phase_progress), 0.0), 1.0)

    # Base midpoint: ~14 months early in phase → ~2 months late
    mid = 14.0 - progress * 12.0

    # Volatility: higher vol shortens hold (anchor at 20% annualized)
    vol = max(volatility, 0.08)
    mid *= max(0.55, min(1.35, 0.22 / vol))

    # Momentum (%): strong uptrend extends, selloff shortens
    if recent_momentum > 8:
        mid *= 1.25
    elif recent_momentum > 3:
        mid *= 1.10
    elif recent_momentum < -5:
        mid *= 0.70
    elif recent_momentum < -2:
        mid *= 0.85

    # Conviction score
    if composite_score >= 70:
        mid *= 1.15
    elif composite_score >= 60:
        mid *= 1.05
    elif composite_score < 45:
        mid *= 0.75
    elif composite_score < 55:
        mid *= 0.90

    # Favored in current sub-phase
    mid *= 1.10 if sub_phase_fit else 0.90

    mid = min(max(mid, 1.5), 18.0)
    lo = max(1, int(round(mid)) - 2)
    hi = int(round(mid)) + 2

    if lo >= 12:
        return "12+ months"
    if hi <= 2:
        return "1-2 months"
    return f"{lo}-{hi} months"
