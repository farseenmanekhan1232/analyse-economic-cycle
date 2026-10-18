import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from backend.config import SECTOR_INDICES
from backend.analysis.regime_detection import RegimeDetector
from backend.analysis.sector_analysis import SectorAnalyzer, compute_recent_momentum
from backend.analysis.leading_signals import LeadingSignalAnalyzer
from backend.models.schemas import (
    SectorAllocation,
    PortfolioAllocation,
    RegimeProbabilities,
)

logger = logging.getLogger(__name__)


class PortfolioAllocator:
    """Tactical sector allocation based on regime probabilities and risk metrics."""

    DEFAULT_STRATEGIC_WEIGHTS: Dict[str, float] = {
        "BANK": 0.12,
        "IT": 0.12,
        "PHARMA": 0.10,
        "FMCG": 0.10,
        "AUTO": 0.08,
        "METAL": 0.06,
        "ENERGY": 0.08,
        "INFRA": 0.06,
        "CONSUMER_DURABLES": 0.06,
        "HEALTHCARE": 0.06,
        "OIL_GAS": 0.05,
        "REALTY": 0.04,
        "PSU_BANK": 0.04,
        "PVT_BANK": 0.04,
        "MEDIA": 0.03,
    }

    def __init__(
        self,
        regime_detector: Optional[RegimeDetector] = None,
        sector_analyzer: Optional[SectorAnalyzer] = None,
        signal_analyzer: Optional[LeadingSignalAnalyzer] = None,
    ) -> None:
        self.regime_detector = regime_detector
        self.sector_analyzer = sector_analyzer
        self.signal_analyzer = signal_analyzer

    def allocate(
        self,
        regime_probs: Optional[RegimeProbabilities] = None,
        sector_data: Optional[Dict[str, pd.DataFrame]] = None,
        momentum_data: Optional[Dict[str, float]] = None,
        cross_asset_signals: Optional[Dict[str, Dict[str, float]]] = None,
        strategic_weights: Optional[Dict[str, float]] = None,
        num_sectors: int = 10,
    ) -> PortfolioAllocation:
        strategic = strategic_weights or self._get_default_strategic_weights()

        if regime_probs is None:
            regime_probs = RegimeProbabilities(
                record_date=datetime.now().date(),
                recovery=0.25,
                expansion=0.25,
                contraction=0.25,
                trough=0.25,
            )

        tactical_overlay = self._compute_tactical_overlay(
            regime_probs,
            sector_data,
            momentum_data,
        )

        risk_adjustment = self._compute_risk_adjustment(sector_data) if sector_data else {}

        available_sectors = list(strategic.keys())
        scores: Dict[str, float] = {}

        for sector in available_sectors:
            strat = strategic.get(sector, 1.0 / len(available_sectors))
            tact = tactical_overlay.get(sector, 0.0)
            risk = risk_adjustment.get(sector, 1.0)

            score = strat * (1.0 + tact) * risk

            if momentum_data and sector in momentum_data:
                mom = momentum_data[sector]
                if mom > 0:
                    score *= 1.2
                elif mom < -10:
                    score *= 0.5

            if cross_asset_signals:
                score = self._apply_cross_asset_filter(sector, score, cross_asset_signals)

            scores[sector] = max(score, 0.0)

        total = sum(scores.values())
        if total == 0:
            total = 1.0

        scored_sectors = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:num_sectors]
        scored_total = sum(s[1] for s in scored_sectors)

        allocations: List[SectorAllocation] = []
        for sector, score in scored_sectors:
            final_weight = score / scored_total
            strat_w = strategic.get(sector, 1.0 / len(available_sectors))
            tact_w = tactical_overlay.get(sector, 0.0)
            risk_w = risk_adjustment.get(sector, 1.0)

            allocations.append(SectorAllocation(
                sector=sector,
                strategic_weight=round(strat_w, 4),
                tactical_weight=round(tact_w, 4),
                risk_adjusted_weight=round(risk_w, 4),
                final_weight=round(final_weight, 4),
            ))

        return PortfolioAllocation(
            effective_date=datetime.now().date(),
            allocations=allocations,
            cash_weight=round(1.0 - sum(a.final_weight for a in allocations), 4),
            regime_probabilities=regime_probs,
        )

    def _compute_tactical_overlay(
        self,
        regime_probs: RegimeProbabilities,
        sector_data: Optional[Dict[str, pd.DataFrame]],
        momentum_data: Optional[Dict[str, float]],
    ) -> Dict[str, float]:
        overlay: Dict[str, float] = {}

        if self.sector_analyzer is None or self.sector_analyzer.results is None:
            return overlay

        results = self.sector_analyzer.results

        regime_weights = {
            "expansion": regime_probs.expansion,
            "recovery": regime_probs.recovery,
            "contraction": regime_probs.contraction,
            "trough": regime_probs.trough,
        }

        for sector, metrics_list in results.items():
            weighted_score = 0.0
            for metric in metrics_list:
                regime_prob = regime_weights.get(metric.regime, 0.0)
                regime_score = metric.sharpe_ratio * regime_prob
                weighted_score += regime_score
            overlay[sector] = round(weighted_score, 4)

        return overlay

    def _compute_risk_adjustment(self, sector_data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        adjustment: Dict[str, float] = {}

        for sector, df in sector_data.items():
            if df.empty:
                adjustment[sector] = 1.0
                continue

            close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
            returns = close.pct_change().dropna()

            if len(returns) < 60:
                adjustment[sector] = 1.0
                continue

            recent_vol = float(returns.iloc[-60:].std())
            if recent_vol == 0:
                adjustment[sector] = 1.0
                continue

            long_term_vol = float(returns.std())
            if long_term_vol == 0:
                adjustment[sector] = 1.0
                continue

            normalized_vol = 1.0 / (recent_vol / long_term_vol)
            adjustment[sector] = round(normalized_vol, 4)

        return adjustment

    def _apply_cross_asset_filter(
        self,
        sector: str,
        score: float,
        signals: Dict[str, Dict[str, float]],
    ) -> float:
        modified = score

        if "sector_oil_sensitivity" in signals and sector in signals["sector_oil_sensitivity"]:
            oil_sens = signals["sector_oil_sensitivity"][sector]
            oil_signal = signals.get("oil", {}).get("momentum_6m", 0.0)

            if oil_sens > 0.3 and oil_signal > 0.15:
                modified *= 0.7
            elif oil_sens < -0.3 and oil_signal > 0.15:
                modified *= 1.3

        if "sector_fx_sensitivity" in signals and sector in signals["sector_fx_sensitivity"]:
            fx_sens = signals["sector_fx_sensitivity"][sector]
            fx_signal = signals.get("inrusd", {}).get("momentum_6m", 0.0)

            if fx_sens > 0.3 and fx_signal > 0.0:
                modified *= 1.2
            elif fx_sens < -0.3 and fx_signal > 0.0:
                modified *= 0.8

        return max(modified, 0.0)

    def _get_default_strategic_weights(self) -> Dict[str, float]:
        return self.DEFAULT_STRATEGIC_WEIGHTS.copy()

    def rebalance_signal(
        self,
        current_allocation: PortfolioAllocation,
        new_allocation: PortfolioAllocation,
        threshold: float = 0.05,
    ) -> bool:
        current_weights = {a.sector: a.final_weight for a in current_allocation.allocations}
        new_weights = {a.sector: a.final_weight for a in new_allocation.allocations}

        all_sectors = set(list(current_weights.keys()) + list(new_weights.keys()))
        total_deviation = sum(
            abs(new_weights.get(s, 0.0) - current_weights.get(s, 0.0))
            for s in all_sectors
        )

        return total_deviation > threshold
