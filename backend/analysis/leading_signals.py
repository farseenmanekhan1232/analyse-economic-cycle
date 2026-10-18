"""Forward-looking signals using free data sources (yfinance + Kite)."""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from backend.config import DEFAULT_START_DATE
from backend.data.cache_manager import CacheManager
from backend.models.schemas import LeadingSignal

logger = logging.getLogger(__name__)


class LeadingSignalAnalyzer:
    """Forward-looking signals: VIX, crude oil, dollar index, INR/USD, India VIX."""

    def __init__(
        self,
        macro=None,
        cache: Optional[CacheManager] = None,
    ) -> None:
        if macro is None:
            from backend.data.macro_client import MacroClient

            macro = MacroClient(cache=cache)
        self.macro = macro
        self.cache = cache or CacheManager()
        self._signals: Dict[str, LeadingSignal] = {}

    def analyze_all(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        india_vix_value: Optional[float] = None,
        india_vix_signal: Optional[str] = None,
    ) -> Dict[str, LeadingSignal]:
        start = start or DEFAULT_START_DATE
        end = end or datetime.now().strftime("%Y-%m-%d")
        self._signals = {}

        for name, fn in [
            ("vix", self._analyze_vix),
            ("crude_oil", self._analyze_crude_oil),
            ("dollar_index", self._analyze_dollar_index),
            ("inrusd", self._analyze_inrusd),
        ]:
            try:
                signal = fn(start, end)
                if signal:
                    self._signals[name] = signal
            except Exception as e:
                logger.warning(f"Failed to analyze {name}: {e}")

        if india_vix_value is not None:
            direction = "bearish" if india_vix_signal in ("fear", "elevated") else "bullish" if india_vix_signal == "complacent" else "neutral"
            confidence = 0.8 if india_vix_signal == "fear" else 0.6 if india_vix_signal == "elevated" else 0.5
            self._signals["india_vix"] = LeadingSignal(
                name="India VIX (NSE)",
                value=round(india_vix_value, 1),
                direction=direction,
                confidence=round(confidence, 2),
                lead_months=1,
            )

        return self._signals

    def _analyze_vix(self, start: str, end: str) -> Optional[LeadingSignal]:
        vix = self.macro.fetch_vix(start, end)
        if vix.empty:
            return None

        vix_series = vix["value"]
        current = float(vix_series.iloc[-1])

        if len(vix_series) >= 21:
            pct_30 = float(vix_series.iloc[-1] / vix_series.iloc[-21:].mean() - 1) * 100
        else:
            pct_30 = 0.0

        if current > 30:
            direction, confidence = "bearish", 0.85
        elif current > 25:
            direction, confidence = "bearish", 0.6
        elif current < 15 and pct_30 < -10:
            direction, confidence = "bullish", 0.6
        elif current < 12:
            direction, confidence = "bullish", 0.7
        else:
            direction, confidence = "neutral", 0.5

        return LeadingSignal(
            name="VIX (US Volatility)",
            value=round(current, 1),
            direction=direction,
            confidence=round(min(max(confidence, 0.0), 1.0), 2),
            lead_months=1,
        )

    def _analyze_crude_oil(self, start: str, end: str) -> Optional[LeadingSignal]:
        oil = self.macro.fetch_wti_crude(start, end)
        if oil.empty:
            return None

        oil_series = oil["value"]
        current = float(oil_series.iloc[-1])
        mom_6 = self._momentum(oil_series, 6)

        if mom_6 > 0.30:
            direction, confidence = "bearish", 0.8
        elif mom_6 > 0.15:
            direction, confidence = "bearish", 0.55
        elif mom_6 < -0.30:
            direction, confidence = "bullish", 0.7
        elif mom_6 < -0.15:
            direction, confidence = "bullish", 0.5
        else:
            direction, confidence = "neutral", 0.5

        return LeadingSignal(
            name="Crude Oil (WTI)",
            value=round(current, 1),
            direction=direction,
            confidence=round(confidence, 2),
            lead_months=2,
        )

    def _analyze_dollar_index(self, start: str, end: str) -> Optional[LeadingSignal]:
        dxy = self.macro.fetch_dollar_index(start, end)
        if dxy.empty:
            return None

        dxy_series = dxy["value"]
        current = float(dxy_series.iloc[-1])
        mom_6 = self._momentum(dxy_series, 6)

        if mom_6 > 0.05:
            direction, confidence = "bearish", 0.7
        elif mom_6 > 0.02:
            direction, confidence = "bearish", 0.5
        elif mom_6 < -0.05:
            direction, confidence = "bullish", 0.7
        elif mom_6 < -0.02:
            direction, confidence = "bullish", 0.5
        else:
            direction, confidence = "neutral", 0.5

        return LeadingSignal(
            name="US Dollar Index",
            value=round(current, 1),
            direction=direction,
            confidence=round(confidence, 2),
            lead_months=3,
        )

    def _analyze_inrusd(self, start: str, end: str) -> Optional[LeadingSignal]:
        inr = self.macro.fetch_inrusd(start, end)
        if inr.empty:
            return None

        inr_series = inr["value"]
        current = float(inr_series.iloc[-1])
        mom_3 = self._momentum(inr_series, 3)

        # INR depreciation (rising INR/USD) = bearish for imports, bullish for IT exports
        if mom_3 > 0.03:
            direction, confidence = "bearish", 0.65
        elif mom_3 < -0.03:
            direction, confidence = "bullish", 0.65
        else:
            direction, confidence = "neutral", 0.5

        return LeadingSignal(
            name="INR/USD Exchange Rate",
            value=round(current, 2),
            direction=direction,
            confidence=round(confidence, 2),
            lead_months=2,
        )

    @staticmethod
    def _momentum(series: pd.Series, months: int) -> float:
        """Calendar-month return using the index, not iloc bar counts.

        yfinance macros are daily; treating `months` as bar offsets was a bug
        (6 ≈ six trading days). Looks back ~21*months trading days as fallback
        when the index is not a DatetimeIndex.
        """
        if series is None or len(series) < 2:
            return 0.0
        current = float(series.iloc[-1])
        if current == 0:
            return 0.0

        idx = series.index
        past_val = None
        if hasattr(idx, "to_pydatetime") or hasattr(idx, "dtype"):
            try:
                last_ts = pd.Timestamp(idx[-1])
                target = last_ts - pd.DateOffset(months=months)
                # Nearest prior point at or before target
                prior = series.loc[:target]
                if not prior.empty:
                    past_val = float(prior.iloc[-1])
            except Exception:
                past_val = None

        if past_val is None:
            bars = max(months * 21, months + 1)
            if len(series) < bars + 1:
                return 0.0
            past_val = float(series.iloc[-(bars + 1)])

        if past_val == 0:
            return 0.0
        return float((current - past_val) / abs(past_val))

    @property
    def signals(self) -> Dict[str, LeadingSignal]:
        return self._signals

    def get_consensus_score(self) -> float:
        if not self._signals:
            return 0.0
        scores: List[float] = []
        dir_map = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
        for signal in self._signals.values():
            scores.append(dir_map[signal.direction] * signal.confidence)
        return float(np.mean(scores)) if scores else 0.0

    def get_sector_bias(self, sector_key: str) -> float:
        """Signed sector bias from macro maps.

        Favored sectors for the active direction get +confidence*0.25;
        sectors favored for the *opposite* direction get a penalty so
        adverse exposure is not ignored.
        """
        if not self._signals:
            return 0.0
        signal_sector_map = {
            "vix": {
                "bullish": ["BANK", "AUTO", "REALTY", "METAL", "ENERGY"],
                "bearish": ["FMCG", "PHARMA", "HEALTHCARE", "IT"],
            },
            "crude_oil": {
                # oil down → consumers; oil up → energy producers
                "bullish": ["AUTO", "REALTY", "CONSUMER_DURABLES", "FMCG"],
                "bearish": ["ENERGY", "OIL_GAS"],
            },
            "dollar_index": {
                "bullish": ["IT", "PHARMA", "METAL", "ENERGY"],
                "bearish": ["BANK", "AUTO", "PSU_BANK", "REALTY"],
            },
            "inrusd": {
                "bullish": ["IT", "PHARMA"],
                "bearish": ["AUTO", "OIL_GAS", "CONSUMER_DURABLES"],
            },
            "india_vix": {
                "bullish": ["BANK", "AUTO", "REALTY", "METAL"],
                "bearish": ["FMCG", "PHARMA", "HEALTHCARE", "IT"],
            },
        }

        opposite = {"bullish": "bearish", "bearish": "bullish"}
        bias = 0.0
        hits = 0
        for name, signal in self._signals.items():
            if name not in signal_sector_map:
                continue
            mapping = signal_sector_map[name]
            direction = signal.direction
            if direction not in ("bullish", "bearish"):
                continue
            weight = signal.confidence * 0.25
            if sector_key in mapping.get(direction, []):
                bias += weight
                hits += 1
            elif sector_key in mapping.get(opposite[direction], []):
                bias -= weight * 0.75
                hits += 1
        if hits == 0:
            return 0.0
        return round(max(min(bias, 1.0), -1.0), 3)
