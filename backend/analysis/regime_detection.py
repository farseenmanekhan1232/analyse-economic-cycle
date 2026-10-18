"""Economic regime detection.

Decoupled from specific data sources. Accepts pre-computed DataFrames.
Can work with either GDP growth data or market-derived signals.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from backend.data.cache_manager import CacheManager
from backend.models.schemas import RegimeProbabilities

logger = logging.getLogger(__name__)

SUB_PHASE_SECTORS = {
    "early_expansion": ["BANK", "PVT_BANK", "AUTO", "REALTY", "CONSUMER_DURABLES", "INFRA"],
    "late_expansion": ["ENERGY", "METAL", "OIL_GAS", "IT"],
    "contraction": ["PHARMA", "FMCG", "HEALTHCARE", "IT", "MEDIA"],
}


class RegimeDetector:
    """Detect economic regimes from GDP or market-derived phase data.

    Accepts a DataFrame with a 'phase' column ('expansion'/'contraction')
    or a 'growth_rate' column (GDP style). Decoupled from data sources.
    """

    def __init__(self, cache: Optional[CacheManager] = None) -> None:
        self.cache = cache or CacheManager()
        self._gdp_data: Optional[pd.DataFrame] = None
        self._phases: Optional[pd.DataFrame] = None
        self._sub_phase: str = "expansion"
        self._phase_progress: float = 0.0

    def fit_from_phases(self, phase_df: pd.DataFrame) -> pd.DataFrame:
        """Fit using a DataFrame that already has a 'phase' column."""
        if phase_df.empty or "phase" not in phase_df.columns:
            logger.error("Phase DataFrame missing 'phase' column")
            return pd.DataFrame()

        self._gdp_data = phase_df.copy()
        self._phases = phase_df.copy()
        self._compute_sub_phase(phase_df, phase_df.get("growth_rate", pd.Series(dtype=float)))
        return self.build_probability_frame(phase_df)

    def fit_from_growth(self, gdp_df: pd.DataFrame) -> pd.DataFrame:
        """Fit using a DataFrame with 'growth_rate' column (classic GDP approach)."""
        if gdp_df.empty or "growth_rate" not in gdp_df.columns:
            logger.error("GDP DataFrame missing 'growth_rate' column")
            return pd.DataFrame()

        gdp = gdp_df.copy()
        growth = gdp["growth_rate"]

        gdp["phase"] = "expansion"
        for i in range(1, len(gdp)):
            prev = growth.iloc[i - 1]
            curr = growth.iloc[i]
            if pd.notna(prev) and pd.notna(curr) and prev < 0 and curr < 0:
                gdp.iloc[i - 1, gdp.columns.get_loc("phase")] = "contraction"
                gdp.iloc[i, gdp.columns.get_loc("phase")] = "contraction"

        self._gdp_data = gdp
        self._phases = gdp
        self._compute_sub_phase(gdp, growth)
        return self.build_probability_frame(gdp)

    @classmethod
    def derive_phases_from_cyclical_ratio(
        cls,
        sector_data: Dict[str, pd.DataFrame],
        threshold: float = 0.0,
    ) -> pd.DataFrame:
        """Derive expansion/contraction phases from cyclical vs defensive relative performance.

        No GDP data needed. Uses Kite sector data to infer cycle phases.
        Returns a DataFrame indexed by date with 'phase' and 'growth_rate' columns.
        """
        from backend.analysis.market_signals import CYCLICAL_SECTORS, DEFENSIVE_SECTORS

        closes: Dict[str, pd.Series] = {}
        for key, df in sector_data.items():
            if df.empty:
                continue
            col = "close" if "close" in df.columns else df.columns[0]
            series = df[col].dropna()
            # Deduplicate index (Kite chunked fetches can produce overlaps)
            closes[key] = series[~series.index.duplicated(keep="last")]

        if not closes:
            return pd.DataFrame()

        all_closes = pd.DataFrame(closes).dropna(how="all")

        cyc = [s for s in CYCLICAL_SECTORS if s in all_closes.columns]
        dfn = [s for s in DEFENSIVE_SECTORS if s in all_closes.columns]
        if not cyc or not dfn:
            return pd.DataFrame()

        cyc_idx = all_closes[cyc].mean(axis=1)
        dfn_idx = all_closes[dfn].mean(axis=1)
        ratio_series = cyc_idx / dfn_idx

        # Resample to quarterly for phase labeling
        quarterly_ratio = ratio_series.resample("QE").last().dropna()
        quarterly_ret = quarterly_ratio.pct_change().dropna()

        phase_df = pd.DataFrame({"ratio": quarterly_ratio, "growth_rate": quarterly_ret}, index=quarterly_ratio.index)
        phase_df["phase"] = "expansion"

        for i in range(1, len(phase_df)):
            if phase_df["growth_rate"].iloc[i] < threshold:
                phase_df.iloc[i, phase_df.columns.get_loc("phase")] = "contraction"

        return phase_df

    def _compute_sub_phase(self, gdp: pd.DataFrame, growth: pd.Series) -> None:
        phases = gdp["phase"]
        current_phase = phases.iloc[-1]

        if current_phase == "contraction":
            self._sub_phase = "contraction"
            durations = self._phase_durations(phases, "contraction")
            if durations:
                avg_dur = sum(durations) / len(durations)
                self._phase_progress = min(durations[-1] / max(avg_dur, 1), 1.0)
        else:
            if growth.empty or len(growth) < 4:
                self._sub_phase = "early_expansion"
                self._phase_progress = 0.5
            else:
                gdp["growth_ma"] = growth.rolling(4).mean()
                latest = growth.iloc[-1]
                ma_val = gdp["growth_ma"].iloc[-1]
                if pd.isna(ma_val) or latest > ma_val:
                    self._sub_phase = "early_expansion"
                else:
                    self._sub_phase = "late_expansion"

            durations = self._phase_durations(phases, "expansion")
            if durations:
                avg_dur = sum(durations) / len(durations)
                self._phase_progress = min(durations[-1] / max(avg_dur, 1), 1.0)

    @staticmethod
    def _phase_durations(phases: pd.Series, target: str) -> List[int]:
        durations: List[int] = []
        start_idx: Optional[int] = None
        for i in range(len(phases)):
            if phases.iloc[i] == target and start_idx is None:
                start_idx = i
            elif phases.iloc[i] != target and start_idx is not None:
                durations.append(i - start_idx)
                start_idx = None
        if start_idx is not None:
            durations.append(len(phases) - start_idx)
        return durations

    def build_probability_frame(self, gdp: pd.DataFrame) -> pd.DataFrame:
        probs = pd.DataFrame(index=gdp.index)
        for regime in ["expansion", "contraction", "recovery", "trough"]:
            probs[regime] = 0.0
        for idx in gdp.index:
            phase = gdp.loc[idx, "phase"]
            probs.loc[idx] = [1.0, 0.0, 0.0, 0.0] if phase == "expansion" else [0.0, 1.0, 0.0, 0.0]
        self._phases = probs
        return probs

    def get_current_regime(self) -> RegimeProbabilities:
        if self._phases is None or self._phases.empty:
            return RegimeProbabilities(
                record_date=datetime.now().date(),
                recovery=0.0, expansion=1.0, contraction=0.0, trough=0.0,
            )
        latest = self._phases.iloc[-1]
        return RegimeProbabilities(
            record_date=latest.name.date() if hasattr(latest.name, "date") else datetime.now().date(),
            recovery=float(latest.get("recovery", 0) or 0),
            expansion=float(latest.get("expansion", 0) or 0),
            contraction=float(latest.get("contraction", 0) or 0),
            trough=float(latest.get("trough", 0) or 0),
        )

    @property
    def sub_phase(self) -> str:
        return self._sub_phase

    @property
    def phase_progress(self) -> float:
        return self._phase_progress

    @property
    def gdp_data(self) -> Optional[pd.DataFrame]:
        return self._gdp_data

    def get_sub_phase_description(self) -> str:
        descriptions = {
            "early_expansion": "Growth is accelerating. Cyclicals & rate-sensitives favored.",
            "late_expansion": "Growth is decelerating. Commodities & quality favored.",
            "contraction": "Economic contraction. Defensives & quality favored.",
        }
        return descriptions.get(self._sub_phase, "")

    def get_sub_phase_sector_map(self) -> Dict[str, list]:
        return SUB_PHASE_SECTORS

    def get_regime_history(self) -> pd.DataFrame:
        return self._phases.copy() if self._phases is not None else pd.DataFrame()
