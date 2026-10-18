"""Cross-asset relationships using free data sources."""

import logging
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from backend.config import DEFAULT_START_DATE
from backend.data.macro_client import MacroClient
from backend.data.kite_client import KiteClient
from backend.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class CrossAssetAnalyzer:
    """Analyzes cross-asset relationships: oil, VIX, dollar, INR."""

    def __init__(
        self,
        kite: Optional[KiteClient] = None,
        macro: Optional[MacroClient] = None,
        cache: Optional[CacheManager] = None,
    ) -> None:
        self.kite = kite
        self.macro = macro or MacroClient(cache=cache)
        self.cache = cache or CacheManager()
        self._spillover_signals: Dict[str, Dict] = {}

    def analyze(
        self,
        sector_data: Optional[Dict[str, pd.DataFrame]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Dict[str, Dict]:
        start = start or DEFAULT_START_DATE
        end = end or datetime.now().strftime("%Y-%m-%d")

        oil = self.macro.fetch_wti_crude(start, end)
        vix = self.macro.fetch_vix(start, end)
        dxy = self.macro.fetch_dollar_index(start, end)
        inrusd = self.macro.fetch_inrusd(start, end)

        signals: Dict[str, Dict] = {}

        if not oil.empty:
            oil_mom = self._momentum(oil["value"], 6)
            signals["oil"] = {
                "level": float(oil["value"].iloc[-1]),
                "momentum_6m": oil_mom,
                "impact": "bearish_for_importers" if oil_mom > 0.1 else "neutral",
            }

        if not vix.empty:
            signals["vix"] = {
                "level": float(vix["value"].iloc[-1]),
                "risk_environment": self._classify_vix(vix["value"]),
            }

        if not dxy.empty:
            dxy_mom = self._momentum(dxy["value"], 6)
            signals["dollar_index"] = {
                "level": float(dxy["value"].iloc[-1]),
                "momentum_6m": dxy_mom,
                "em_flow_signal": "favorable" if dxy_mom < 0 else "unfavorable",
            }

        if not inrusd.empty:
            inr_mom = self._momentum(inrusd["value"], 6)
            signals["inrusd"] = {
                "level": float(inrusd["value"].iloc[-1]),
                "momentum_6m": inr_mom,
                "exporter_benefit": "positive" if inr_mom > 0.02 else "neutral",
            }

        if sector_data is not None and not oil.empty:
            signals["sector_oil_sensitivity"] = self._compute_oil_sensitivity(sector_data, oil)
        if sector_data is not None and not inrusd.empty:
            signals["sector_fx_sensitivity"] = self._compute_fx_sensitivity(sector_data, inrusd)

        self._spillover_signals = signals
        return signals

    @staticmethod
    def _momentum(series: pd.Series, periods: int) -> float:
        if len(series) < periods + 1:
            return 0.0
        return float((series.iloc[-1] / series.iloc[-(periods + 1)] - 1))

    @staticmethod
    def _classify_vix(vix_series: pd.Series) -> str:
        current = float(vix_series.iloc[-1])
        avg = float(vix_series.iloc[-60:].mean()) if len(vix_series) >= 60 else current
        if current > avg * 1.5:
            return "extreme_fear"
        elif current > avg * 1.2:
            return "fear"
        elif current < avg * 0.7:
            return "complacency"
        return "neutral"

    @staticmethod
    def _compute_oil_sensitivity(sector_data: Dict[str, pd.DataFrame], oil: pd.DataFrame) -> Dict[str, float]:
        oil_ret = oil["value"].pct_change().dropna()
        oil_monthly = oil_ret.resample("MS").mean()
        sensitivity: Dict[str, float] = {}
        for key, df in sector_data.items():
            close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
            sector_ret = close.pct_change().dropna().resample("MS").mean()
            aligned = pd.concat([sector_ret, oil_monthly], axis=1).dropna()
            sensitivity[key] = round(float(aligned.corr().iloc[0, 1]), 3) if len(aligned) >= 12 and aligned.shape[1] >= 2 else 0.0
        return sensitivity

    @staticmethod
    def _compute_fx_sensitivity(sector_data: Dict[str, pd.DataFrame], inrusd: pd.DataFrame) -> Dict[str, float]:
        fx_ret = inrusd["value"].pct_change().dropna()
        sensitivity: Dict[str, float] = {}
        for key, df in sector_data.items():
            close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
            sector_ret = close.pct_change().dropna()
            aligned = pd.concat([sector_ret, fx_ret], axis=1).dropna()
            sensitivity[key] = round(float(aligned.corr().iloc[0, 1]), 3) if len(aligned) >= 20 and aligned.shape[1] >= 2 else 0.0
        return sensitivity

    @property
    def signals(self) -> Dict[str, Dict]:
        return self._spillover_signals


def compute_rolling_correlation(series_a: pd.Series, series_b: pd.Series, window: int = 60) -> pd.Series:
    aligned = pd.concat([series_a, series_b], axis=1).dropna()
    if len(aligned) < window:
        return pd.Series(dtype=float)
    return aligned.iloc[:, 0].rolling(window).corr(aligned.iloc[:, 1])


def detect_divergence(series_a: pd.Series, series_b: pd.Series, lookback: int = 20, threshold: float = 0.3) -> Dict:
    rolling_corr = compute_rolling_correlation(series_a, series_b, lookback)
    if rolling_corr.empty:
        return {"divergence": False, "correlation": 0.0}
    current = float(rolling_corr.iloc[-1])
    avg = float(rolling_corr.mean())
    return {
        "divergence": (avg - current) > threshold,
        "current_correlation": round(current, 3),
        "average_correlation": round(avg, 3),
        "regime_change_signal": "possible" if (avg - current) > threshold else "none",
    }
