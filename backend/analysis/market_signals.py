"""Market-derived economic cycle signals computed from Kite sector data.

Replaces GDP-based regime detection with forward-looking market signals:
1. Cyclicals/Defensives ratio -> expansion vs contraction
2. Credit cycle proxy via Bank vs Nifty
3. Inflation expectations via Commodities vs Consumers
4. Growth vs Value rotation
5. Market breadth (% sectors above 200DMA)
6. Sector rotation momentum ranking
7. India VIX (from Kite, not US VIX)
"""

import logging
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from backend.config import INDIA_VIX_SYMBOL
from backend.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)

CYCLICAL_SECTORS = [
    "BANK",
    "AUTO",
    "REALTY",
    "INFRA",
    "METAL",
    "ENERGY",
    "PSU_BANK",
    "PVT_BANK",
    "OIL_GAS",
    "CONSUMER_DURABLES",
]
DEFENSIVE_SECTORS = ["PHARMA", "FMCG", "HEALTHCARE", "IT", "MEDIA"]
COMMODITY_SECTORS = ["METAL", "OIL_GAS", "ENERGY"]
CONSUMER_SECTORS = ["FMCG", "CONSUMER_DURABLES", "AUTO"]
GROWTH_SECTORS = ["IT", "PHARMA", "HEALTHCARE"]
VALUE_SECTORS = ["BANK", "PSU_BANK", "PVT_BANK", "ENERGY", "METAL"]


class MarketSignals:
    """Derives economic cycle signals from sector index data."""

    def __init__(self, cache: Optional[CacheManager] = None) -> None:
        self.cache = cache or CacheManager()
        self._signals: Dict = {}

    def compute_all(
        self,
        sector_data: Dict[str, pd.DataFrame],
        kite_client=None,
    ) -> Dict:
        """Compute all market-derived cycle signals."""
        self._signals = {}

        for name, fn in [
            ("cyclical_defensive", self.compute_cyclical_defensive_ratio),
            ("credit_cycle", self.compute_credit_cycle),
            ("inflation_expectations", self.compute_inflation_expectations),
            ("growth_value", self.compute_growth_value_rotation),
            ("market_breadth", self.compute_market_breadth),
            ("sector_momentum", self.compute_sector_rotation_momentum),
            ("india_vix", lambda d, k=kite_client: self.compute_india_vix(k) if k else {"value": None, "signal": "unknown"}),
        ]:
            try:
                if name == "india_vix":
                    sig = fn(sector_data)  # type: ignore
                else:
                    sig = fn(sector_data)
                self._signals[name] = sig
            except Exception as e:
                logger.warning(f"{name} signal failed: {e}")

        return self._signals

    @staticmethod
    def _get_daily_closes(sector_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        closes: Dict[str, pd.Series] = {}
        for key, df in sector_data.items():
            if df.empty:
                continue
            col = "close" if "close" in df.columns else df.columns[0]
            series = df[col].dropna()
            # Deduplicate index (Kite chunked fetches can produce overlaps)
            series = series[~series.index.duplicated(keep="last")]
            closes[key] = series
        if not closes:
            return pd.DataFrame()
        return pd.DataFrame(closes).dropna(how="all")

    @staticmethod
    def _trend_signal(series: pd.Series, lookback: int = 63) -> Dict:
        """Compute MA crossover + trend signal for any ratio series."""
        if len(series) < lookback:
            return {"signal": "unknown", "trend_pct": 0.0, "confidence": 0.3}
        ma_short = series.rolling(21).mean()
        ma_long = series.rolling(lookback).mean()
        trend = float((series.iloc[-1] / series.iloc[-lookback] - 1) * 100)
        if ma_short.iloc[-1] > ma_long.iloc[-1] and trend > 2:
            return {"signal": "rising", "trend_pct": round(trend, 2), "confidence": min(0.9, 0.5 + abs(trend) / 20)}
        elif ma_short.iloc[-1] < ma_long.iloc[-1] and trend < -2:
            return {"signal": "falling", "trend_pct": round(trend, 2), "confidence": min(0.9, 0.5 + abs(trend) / 20)}
        return {"signal": "flat", "trend_pct": round(trend, 2), "confidence": 0.4}

    def compute_cyclical_defensive_ratio(
        self, sector_data: Dict[str, pd.DataFrame]
    ) -> Dict:
        """Cyclicals vs Defensives. Rising = expansion, falling = contraction."""
        closes = self._get_daily_closes(sector_data)
        if closes.empty:
            return {"signal": "unknown", "ratio": None}

        cyc = [s for s in CYCLICAL_SECTORS if s in closes.columns]
        dfn = [s for s in DEFENSIVE_SECTORS if s in closes.columns]
        if not cyc or not dfn:
            return {"signal": "unknown", "ratio": None}

        ratio = (closes[cyc].mean(axis=1) / closes[dfn].mean(axis=1)).dropna()
        ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
        trend = self._trend_signal(ratio_norm)

        return {
            "signal": "expansion" if trend["signal"] == "rising" else "contraction" if trend["signal"] == "falling" else "transition",
            "ratio": round(float(ratio_norm.iloc[-1]), 4),
            "trend_3m_pct": trend["trend_pct"],
            "confidence": trend["confidence"],
        }

    def compute_credit_cycle(self, sector_data: Dict[str, pd.DataFrame]) -> Dict:
        """Bank vs broad market = credit cycle proxy."""
        closes = self._get_daily_closes(sector_data)
        if closes.empty:
            return {"signal": "neutral", "ratio": None}

        bank_s = [s for s in ["BANK", "PVT_BANK", "PSU_BANK"] if s in closes.columns]
        if not bank_s:
            return {"signal": "neutral", "ratio": None}

        ratio = (closes[bank_s].mean(axis=1) / closes.mean(axis=1)).dropna()
        ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
        trend = self._trend_signal(ratio_norm)

        phase = "credit_expansion" if trend["signal"] == "rising" else "credit_contraction" if trend["signal"] == "falling" else "neutral"
        return {"signal": phase, "ratio": round(float(ratio_norm.iloc[-1]), 4), "trend_3m_pct": trend["trend_pct"]}

    def compute_inflation_expectations(self, sector_data: Dict[str, pd.DataFrame]) -> Dict:
        """Commodities vs Consumers = inflation expectations."""
        closes = self._get_daily_closes(sector_data)
        if closes.empty:
            return {"signal": "neutral", "ratio": None}

        comm = [s for s in COMMODITY_SECTORS if s in closes.columns]
        cons = [s for s in CONSUMER_SECTORS if s in closes.columns]
        if not comm or not cons:
            return {"signal": "neutral", "ratio": None}

        ratio = (closes[comm].mean(axis=1) / closes[cons].mean(axis=1)).dropna()
        ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
        trend = self._trend_signal(ratio_norm)

        if trend["trend_pct"] > 5:
            sig = "rising_inflation"
        elif trend["trend_pct"] < -5:
            sig = "falling_inflation"
        else:
            sig = "stable"
        return {"signal": sig, "ratio": round(float(ratio_norm.iloc[-1]), 4), "trend_3m_pct": trend["trend_pct"]}

    def compute_growth_value_rotation(self, sector_data: Dict[str, pd.DataFrame]) -> Dict:
        """Growth vs Value rotation."""
        closes = self._get_daily_closes(sector_data)
        if closes.empty:
            return {"signal": "neutral", "ratio": None}

        gs = [s for s in GROWTH_SECTORS if s in closes.columns]
        vs = [s for s in VALUE_SECTORS if s in closes.columns]
        if not gs or not vs:
            return {"signal": "neutral", "ratio": None}

        ratio = (closes[gs].mean(axis=1) / closes[vs].mean(axis=1)).dropna()
        ratio_norm = ratio / ratio.iloc[0] if ratio.iloc[0] != 0 else ratio
        trend = self._trend_signal(ratio_norm)

        rot = "growth_leading" if trend["trend_pct"] > 3 else "value_leading" if trend["trend_pct"] < -3 else "neutral"
        return {"signal": rot, "ratio": round(float(ratio_norm.iloc[-1]), 4), "trend_3m_pct": trend["trend_pct"]}

    def compute_market_breadth(self, sector_data: Dict[str, pd.DataFrame]) -> Dict:
        """Percentage of sectors above 200-day moving average."""
        closes = self._get_daily_closes(sector_data)
        if closes.empty:
            return {"breadth_pct": 0, "signal": "unknown"}

        above, total = 0, 0
        details: Dict[str, bool] = {}
        for col in closes.columns:
            series = closes[col].dropna()
            if len(series) < 200:
                continue
            ma200 = series.rolling(200).mean()
            if pd.notna(ma200.iloc[-1]) and ma200.iloc[-1] > 0:
                details[col] = series.iloc[-1] > ma200.iloc[-1]
                if details[col]:
                    above += 1
                total += 1

        if total == 0:
            return {"breadth_pct": 0, "signal": "unknown"}

        pct = (above / total) * 100
        signal = "healthy" if pct >= 70 else "moderate" if pct >= 40 else "narrow"
        return {"breadth_pct": round(pct, 1), "signal": signal, "sectors_above": above, "total_sectors": total, "details": details}

    def compute_sector_rotation_momentum(
        self, sector_data: Dict[str, pd.DataFrame], lookback: int = 63
    ) -> Dict:
        """Rank sectors by 3-month momentum."""
        closes = self._get_daily_closes(sector_data)
        if closes.empty:
            return {"leaders": [], "laggards": [], "rotation_type": "unknown"}

        momentum: Dict[str, float] = {}
        for col in closes.columns:
            series = closes[col].dropna()
            if len(series) < lookback:
                continue
            momentum[col] = round((series.iloc[-1] / series.iloc[-lookback] - 1) * 100, 2)

        if not momentum:
            return {"leaders": [], "laggards": [], "rotation_type": "unknown"}

        sorted_mom = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
        leaders = sorted_mom[:5]
        laggards = sorted_mom[-5:]

        top3 = [s[0] for s in sorted_mom[:3]]
        cyc_count = sum(1 for s in top3 if s in CYCLICAL_SECTORS)
        def_count = sum(1 for s in top3 if s in DEFENSIVE_SECTORS)

        rot = "cyclical_led" if cyc_count >= 2 else "defensive_led" if def_count >= 2 else "mixed"
        return {
            "leaders": [{"sector": s, "momentum_pct": m} for s, m in leaders],
            "laggards": [{"sector": s, "momentum_pct": m} for s, m in laggards],
            "rotation_type": rot,
        }

    def compute_india_vix(self, kite_client=None) -> Dict:
        """India VIX from Kite (NSE: INDIAVIX)."""
        if kite_client is None:
            return {"value": None, "signal": "unknown"}

        try:
            token = kite_client.get_instrument_token("NSE", INDIA_VIX_SYMBOL)
            if token is None:
                logger.warning("India VIX instrument token not found")
                return {"value": None, "signal": "unknown"}

            vix_df = kite_client.fetch_historical(token, "2005-01-01", datetime.now().strftime("%Y-%m-%d"))

            if vix_df is None or vix_df.empty:
                return {"value": None, "signal": "unknown"}

            close = vix_df.get("close", vix_df.iloc[:, 0])
            close = close[~close.index.duplicated(keep="last")]
            current = float(close.iloc[-1])
            avg_60d = float(close.iloc[-60:].mean()) if len(close) >= 60 else current

            if current > 25:
                sig = "fear"
            elif current > 20:
                sig = "elevated"
            elif current < 12:
                sig = "complacent"
            else:
                sig = "normal"
            return {"value": round(current, 1), "signal": sig, "avg_60d": round(avg_60d, 1)}
        except Exception as e:
            logger.warning(f"India VIX fetch failed: {e}")
            return {"value": None, "signal": "unknown"}

    def get_cycle_phase(self, prev_sub_phase: Optional[str] = None) -> Dict:
        """Synthesize all signals into a single phase determination.

        Uses enter/exit deadbands so early↔late and expansion↔contraction
        do not flip on a single ±0.5 vote near the old hard cliffs.
        """
        cd = self._signals.get("cyclical_defensive", {})
        cc = self._signals.get("credit_cycle", {})
        mb = self._signals.get("market_breadth", {})
        rm = self._signals.get("sector_momentum", {})

        score = 0.0
        if cd.get("signal") == "expansion":
            score += 1.0
        elif cd.get("signal") == "contraction":
            score -= 1.0

        if cc.get("signal") == "credit_expansion":
            score += 0.5
        elif cc.get("signal") == "credit_contraction":
            score -= 0.5

        if mb.get("signal") == "healthy":
            score += 0.5
        elif mb.get("signal") == "narrow":
            score -= 0.5

        if rm.get("rotation_type") == "cyclical_led":
            score += 0.5
        elif rm.get("rotation_type") == "defensive_led":
            score -= 0.5

        prev = (prev_sub_phase or "").strip() or None
        phase, sub = self._phase_with_deadband(score, prev)

        progress = self._estimate_phase_progress(sub, score, cd, mb)

        return {
            "phase": phase,
            "sub_phase": sub,
            "score": round(score, 2),
            "progress": progress,
            "cyclical_defensive": cd.get("signal"),
            "credit_cycle": cc.get("signal"),
            "breadth": mb.get("signal"),
            "rotation": rm.get("rotation_type"),
            "prev_sub_phase": prev,
            "early_fit": self._soft_sub_phase_fit(score, "early_expansion"),
            "late_fit": self._soft_sub_phase_fit(score, "late_expansion"),
            "contraction_fit": self._soft_sub_phase_fit(score, "contraction"),
        }

    @staticmethod
    def _phase_with_deadband(score: float, prev_sub: Optional[str]) -> tuple:
        from backend.decision.thresholds import (
            PHASE_CONTRACTION_ENTER,
            PHASE_CONTRACTION_EXIT,
            PHASE_EARLY_ENTER,
            PHASE_EARLY_EXIT,
            PHASE_EXPANSION_FLOOR,
        )

        prev = prev_sub or "late_expansion"

        # Contraction sticky band
        if prev == "contraction":
            if score <= PHASE_CONTRACTION_EXIT:
                return "contraction", "contraction"
            if score >= PHASE_EARLY_ENTER:
                return "expansion", "early_expansion"
            if score >= PHASE_EXPANSION_FLOOR:
                return "expansion", "late_expansion"
            return "contraction", "contraction"

        # Expansion sticky: early vs late
        if prev == "early_expansion":
            if score >= PHASE_EARLY_EXIT:
                return "expansion", "early_expansion"
            if score <= PHASE_CONTRACTION_ENTER:
                return "contraction", "contraction"
            return "expansion", "late_expansion"

        # Default / late_expansion
        if score >= PHASE_EARLY_ENTER:
            return "expansion", "early_expansion"
        if score <= PHASE_CONTRACTION_ENTER:
            return "contraction", "contraction"
        if score <= PHASE_CONTRACTION_EXIT and score < PHASE_EXPANSION_FLOOR:
            return "contraction", "contraction"
        return "expansion", "late_expansion"

    @staticmethod
    def _soft_sub_phase_fit(cycle_score: float, target: str) -> float:
        """0–1 blend of how well cycle_score matches a sub-phase (no hard cliff)."""
        if target == "early_expansion":
            # Full fit near ≥1.2, none below 0.5
            return float(min(max((cycle_score - 0.5) / 0.7, 0.0), 1.0))
        if target == "late_expansion":
            # Peak around 0.3–0.9
            if cycle_score >= 1.2:
                return 0.15
            if cycle_score >= 0.3:
                return float(min(max(1.0 - abs(cycle_score - 0.65) / 0.55, 0.2), 1.0))
            if cycle_score >= -0.2:
                return 0.35
            return 0.1
        # contraction
        return float(min(max((-cycle_score - 0.2) / 0.9, 0.0), 1.0))

    @staticmethod
    def _estimate_phase_progress(
        sub_phase: str,
        score: float,
        cyclical_defensive: Dict,
        market_breadth: Dict,
    ) -> float:
        """Estimate how far through the current phase we are (0=start, 1=end)."""
        breadth_pct = float(market_breadth.get("breadth_pct") or 50.0)
        trend_3m = float(cyclical_defensive.get("trend_3m_pct") or 0.0)

        if sub_phase == "early_expansion":
            # Strong cyclicals + healthy breadth = early; weakening = later early-cycle
            progress = 0.20
            if breadth_pct < 60:
                progress += 0.15
            if trend_3m < 3:
                progress += 0.10
            progress += max(0.0, (2.0 - score) * 0.08)
            return round(min(max(progress, 0.10), 0.45), 2)

        if sub_phase == "late_expansion":
            # Mid-to-late: narrower breadth and fading cyclical lead push progress up
            progress = 0.55
            if breadth_pct < 50:
                progress += 0.15
            elif breadth_pct > 70:
                progress -= 0.10
            if trend_3m < 0:
                progress += 0.12
            progress += max(0.0, (1.0 - score) * 0.15)
            return round(min(max(progress, 0.45), 0.90), 2)

        # Contraction: deeper negative score + narrow market = further into contraction
        progress = 0.35
        if breadth_pct < 40:
            progress += 0.20
        progress += min(0.35, abs(score) * 0.15)
        if trend_3m > 0:
            progress += 0.10  # cyclicals recovering → late contraction
        return round(min(max(progress, 0.15), 0.95), 2)

    @property
    def signals(self) -> Dict:
        return self._signals
