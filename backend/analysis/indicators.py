"""Composite leading index and nowcasting (data-source agnostic).

These tools build synthetic indicators from multiple time series.
They accept pre-fetched DataFrames — no data fetching dependency.
"""

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from backend.data.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class CompositeLeadingIndex:
    """Builds a composite leading index (CLI) from multiple economic indicators using PCA.

    Accepts a dict of {name: pd.DataFrame} with a 'value' column.
    """

    def __init__(self, cache: Optional[CacheManager] = None) -> None:
        self.cache = cache or CacheManager()
        self._components: Optional[pd.DataFrame] = None
        self._weights: Optional[Dict[str, float]] = None
        self._clf: Optional[pd.Series] = None

    def build_from_series(self, data: Dict[str, pd.Series]) -> pd.Series:
        """Build CLI from a dict of monthly pd.Series."""
        monthly_dfs = []
        for name, series in data.items():
            monthly = series.resample("MS").mean().ffill()
            monthly.name = name
            monthly_dfs.append(monthly)

        if not monthly_dfs:
            return pd.Series(dtype=float)

        combined = pd.concat(monthly_dfs, axis=1).dropna()
        if len(combined) < 12:
            logger.warning(f"Only {len(combined)} months of data — CLI may be unreliable")

        growth_cols = {f"{col}_mom": combined[col].pct_change() for col in combined.columns}
        growth_df = pd.DataFrame(growth_cols).dropna()

        if growth_df.empty or growth_df.shape[1] < 2:
            return pd.Series(dtype=float)

        scaler = StandardScaler()
        scaled = scaler.fit_transform(growth_df)

        n_components = min(3, growth_df.shape[1])
        pca = PCA(n_components=n_components)
        pca.fit(scaled)

        first_pc = pca.components_[0]
        self._weights = dict(zip(growth_df.columns, first_pc))
        cli_raw = np.dot(scaled, first_pc)
        cli = pd.Series(cli_raw, index=growth_df.index, name="CLI")
        cli = (cli - cli.mean()) / cli.std()
        self._components = growth_df
        self._clf = cli

        logger.info(f"CLI built: {len(cli)} months, explained variance: {pca.explained_variance_ratio_[0]:.2%}")
        return cli

    @property
    def cli(self) -> Optional[pd.Series]:
        return self._clf

    @property
    def weights(self) -> Optional[Dict[str, float]]:
        return self._weights

    def get_direction_signal(self, lookback: int = 6) -> Dict[str, float]:
        if self._clf is None or len(self._clf) < lookback + 1:
            return {"signal": 0.0, "momentum": 0.0, "acceleration": 0.0}
        recent = self._clf.iloc[-lookback:]
        momentum = recent.iloc[-1] - recent.iloc[0]
        acceleration = recent.diff().iloc[-lookback // 2:].mean() - recent.diff().iloc[:lookback // 2].mean()
        return {"signal": float(momentum), "momentum": float(momentum), "acceleration": float(acceleration)}


class NowcastingModel:
    """Estimates current-quarter GDP growth using higher-frequency indicators.

    Accepts pre-fetched DataFrames directly.
    """

    def __init__(self, cache: Optional[CacheManager] = None) -> None:
        self.cache = cache or CacheManager()

    def nowcast(
        self,
        gdp_growth: pd.Series,
        monthly_indicators: Dict[str, pd.Series],
    ) -> pd.DataFrame:
        """Estimate current-quarter GDP growth from monthly bridge variables."""
        gdp_quarterly = gdp_growth.resample("QS").last().dropna()
        results: list = []

        for i, q_date in enumerate(gdp_quarterly.index):
            if i < 4:
                results.append({
                    "quarter": q_date,
                    "gdp_growth": gdp_quarterly.iloc[i],
                    "nowcast": gdp_quarterly.iloc[i],
                    "lower_bound": gdp_quarterly.iloc[i] * 0.8,
                    "upper_bound": gdp_quarterly.iloc[i] * 1.2,
                })
                continue

            q_start = q_date - pd.DateOffset(months=3)
            month_vals: Dict[str, float] = {}
            for name, series in monthly_indicators.items():
                in_q = series[(series.index >= q_start) & (series.index < q_date)]
                if len(in_q) >= 1:
                    month_vals[name] = float(in_q.mean())

            if not month_vals:
                nowcast = gdp_quarterly.iloc[i - 1]
            else:
                corr_weights: Dict[str, float] = {}
                for name in month_vals:
                    m_resampled = monthly_indicators[name].resample("QS").mean()
                    aligned = pd.concat([gdp_quarterly, m_resampled], axis=1).dropna()
                    if aligned.shape[1] == 2 and len(aligned) > 4:
                        c = aligned.corr().iloc[0, 1]
                        corr_weights[name] = abs(c) if not np.isnan(c) else 0.3

                total_w = sum(corr_weights.values()) or 1.0
                nowcast = sum(month_vals[n] * corr_weights.get(n, 0.3) / total_w for n in month_vals)

            prev = gdp_quarterly.iloc[i - 1]
            nowcast = 0.5 * nowcast + 0.5 * prev
            std_est = gdp_quarterly.iloc[:i].std()

            results.append({
                "quarter": q_date,
                "gdp_growth": gdp_quarterly.iloc[i],
                "nowcast": float(nowcast),
                "lower_bound": float(nowcast - 1.96 * std_est),
                "upper_bound": float(nowcast + 1.96 * std_est),
            })

        return pd.DataFrame(results)
