"""Feature store + IC / ICIR reporting (broker-agnostic)."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


def _closes(panel: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    cols = {}
    for k, df in panel.items():
        if df is None or df.empty:
            continue
        out = df.copy()
        out.index = pd.to_datetime(out.index).normalize()
        out = out[~out.index.duplicated(keep="last")].sort_index()
        col = "close" if "close" in out.columns else out.columns[0]
        cols[k] = out[col].astype(float)
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index().ffill()


def residualize_returns(
    asset_ret: pd.Series,
    factors: pd.DataFrame,
) -> pd.Series:
    """OLS residual of asset returns on factor columns (point-in-time expanding optional)."""
    joined = pd.concat([asset_ret.rename("y"), factors], axis=1, join="inner").dropna()
    if len(joined) < max(30, factors.shape[1] + 5):
        return asset_ret * np.nan
    y = joined["y"].values
    X = np.column_stack([np.ones(len(joined)), joined.drop(columns=["y"]).values])
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
    except np.linalg.LinAlgError:
        return asset_ret * np.nan
    return pd.Series(resid, index=joined.index, name=asset_ret.name)


def build_macro_feature_frame(
    sector_closes: pd.DataFrame,
    *,
    vix: Optional[pd.Series] = None,
    momentum_lookback: int = 63,
    breadth_ma: int = 50,
) -> pd.DataFrame:
    """
    Cycle-style emissions for regime HMM / meta-labeler.

    Uses available sector columns; missing groups degrade gracefully.
    """
    if sector_closes.empty:
        return pd.DataFrame()

    c = sector_closes.sort_index().ffill()
    cyclical = [x for x in ("BANK", "AUTO", "REALTY", "METAL", "ENERGY", "INFRA", "PSU_BANK") if x in c.columns]
    defensive = [x for x in ("PHARMA", "FMCG", "HEALTHCARE", "IT", "CONSUMER_DURABLES") if x in c.columns]
    bank = [x for x in ("BANK", "PSU_BANK", "PVT_BANK") if x in c.columns]

    feats: Dict[str, pd.Series] = {}
    if cyclical and defensive:
        ratio = c[cyclical].mean(axis=1) / c[defensive].mean(axis=1)
        feats["cyc_def_mom"] = ratio.pct_change(momentum_lookback)
    if bank:
        feats["credit_mom"] = (c[bank].mean(axis=1) / c.mean(axis=1)).pct_change(momentum_lookback)

    # Breadth: % above MA
    above = pd.DataFrame({col: c[col] > c[col].rolling(breadth_ma).mean() for col in c.columns})
    feats["breadth"] = above.mean(axis=1)

    # Cross-sectional momentum dispersion
    mom = c.pct_change(momentum_lookback)
    feats["mom_dispersion"] = mom.std(axis=1)

    # Realized vol of equal-weight basket
    ew = c.mean(axis=1).pct_change()
    feats["realized_vol"] = ew.rolling(21).std() * np.sqrt(252)

    if vix is not None:
        vs = vix.copy()
        vs.index = pd.to_datetime(vs.index).normalize()
        vs = vs[~vs.index.duplicated(keep="last")]
        feats["vix_z"] = (vs - vs.rolling(60).mean()) / vs.rolling(60).std().replace(0, np.nan)

    out = pd.DataFrame(feats).replace([np.inf, -np.inf], np.nan)
    return out.dropna(how="all")


def build_cross_sectional_features(
    panel: Mapping[str, pd.DataFrame],
    *,
    benchmark: Optional[pd.Series] = None,
    lookbacks: Sequence[int] = (21, 63, 126),
) -> pd.DataFrame:
    """
    Long panel: MultiIndex (date, symbol) with momentum / residual-z / vol features.
    """
    closes = _closes(panel)
    if closes.empty:
        return pd.DataFrame()

    bench = None
    if benchmark is not None:
        bench = benchmark.copy()
        bench.index = pd.to_datetime(bench.index).normalize()
        bench = bench.reindex(closes.index).ffill()
    elif "NIFTY" in closes.columns:
        bench = closes["NIFTY"]

    rows: List[pd.DataFrame] = []
    rets = closes.pct_change()
    for sym in closes.columns:
        r = rets[sym]
        block: Dict[str, Any] = {"symbol": sym}
        feat = pd.DataFrame(index=closes.index)
        feat["symbol"] = sym
        for lb in lookbacks:
            feat[f"mom_{lb}"] = closes[sym].pct_change(lb)
            feat[f"vol_{lb}"] = r.rolling(lb).std() * np.sqrt(252)
        if bench is not None:
            feat["beta_60"] = r.rolling(60).cov(bench.pct_change()) / (
                bench.pct_change().rolling(60).var().replace(0, np.nan)
            )
            resid = residualize_returns(r, pd.DataFrame({"mkt": bench.pct_change()}))
            feat["resid_z_20"] = (resid - resid.rolling(20).mean()) / resid.rolling(20).std().replace(
                0, np.nan
            )
            for lb in lookbacks:
                feat[f"rs_{lb}"] = closes[sym].pct_change(lb) - bench.pct_change(lb)
        # Vol compression
        atr_proxy = (closes[sym].rolling(14).max() - closes[sym].rolling(14).min()) / closes[sym]
        feat["range_compress"] = atr_proxy / atr_proxy.rolling(50).mean()
        rows.append(feat)

    long = pd.concat(rows).dropna(how="all")
    long = long.set_index("symbol", append=True)
    long.index = long.index.set_names(["date", "symbol"])
    return long.sort_index()


def _spearman(a: pd.Series, b: pd.Series) -> float:
    if len(a) < 3:
        return float("nan")
    return float(a.rank().corr(b.rank(), method="pearson"))


def information_coefficient_report(
    features: pd.DataFrame,
    forward_returns: pd.Series,
    *,
    feature_cols: Optional[Iterable[str]] = None,
    rolling_window: int = 60,
) -> pd.DataFrame:
    """
    Spearman IC of each feature vs forward returns.

    `features` and `forward_returns` share index (date) or MultiIndex (date, symbol).
    """
    if features.empty or forward_returns.empty:
        return pd.DataFrame()

    cols = list(feature_cols) if feature_cols else [
        c for c in features.columns if c != "symbol" and features[c].dtype != object
    ]
    y = forward_returns.rename("fwd")
    joined = features.join(y, how="inner")
    records = []
    for col in cols:
        sub = joined[[col, "fwd"]].dropna()
        if len(sub) < 40:
            continue
        if isinstance(sub.index, pd.MultiIndex):
            ics = (
                sub.groupby(level=0)
                .apply(lambda g: _spearman(g[col], g["fwd"]) if len(g) >= 5 else np.nan)
                .dropna()
            )
        else:
            ics = pd.Series(
                [
                    _spearman(
                        sub[col].iloc[i - rolling_window : i],
                        sub["fwd"].iloc[i - rolling_window : i],
                    )
                    for i in range(rolling_window, len(sub) + 1)
                ],
                index=sub.index[rolling_window - 1 :],
            ).dropna()

        if ics.empty:
            continue
        mean_ic = float(ics.mean())
        std_ic = float(ics.std()) if ics.std() and ics.std() > 0 else np.nan
        icir = mean_ic / std_ic if std_ic and np.isfinite(std_ic) else np.nan
        ac = ics.autocorr(lag=1)
        half_life = None
        if ac is not None and 0 < ac < 1:
            half_life = float(np.log(0.5) / np.log(ac))
        records.append(
            {
                "feature": col,
                "ic_mean": round(mean_ic, 4),
                "ic_std": round(std_ic, 4) if std_ic == std_ic else None,
                "icir": round(icir, 4) if icir == icir else None,
                "n_obs": int(len(ics)),
                "ic_decay_halflife": round(half_life, 2) if half_life else None,
                "positive_ic_frac": round(float((ics > 0).mean()), 3),
            }
        )
    return pd.DataFrame(records).sort_values("icir", ascending=False, na_position="last")


def forward_returns_panel(
    panel: Mapping[str, pd.DataFrame],
    horizon: int = 10,
) -> pd.Series:
    closes = _closes(panel)
    if closes.empty:
        return pd.Series(dtype=float)
    fwd = closes.pct_change(horizon).shift(-horizon)
    stacked = fwd.stack()
    stacked.index = stacked.index.set_names(["date", "symbol"])
    return stacked.rename("fwd")


def panel_from_synthetic(
    n_days: int = 400,
    n_assets: int = 8,
    seed: int = 7,
) -> Dict[str, pd.DataFrame]:
    """CI helper — not for promotion."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    names = [f"S{i}" for i in range(n_assets)]
    # Also add sector-like names for macro frame
    sector_names = ["BANK", "IT", "PHARMA", "AUTO", "METAL", "FMCG", "ENERGY", "REALTY"]
    out: Dict[str, pd.DataFrame] = {}
    for i, name in enumerate(sector_names[:n_assets]):
        drift = 0.0003 if i % 2 == 0 else 0.0001
        rets = drift + rng.normal(0, 0.012, n_days)
        close = 100 * np.cumprod(1 + rets)
        out[name] = pd.DataFrame(
            {
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": rng.integers(1e5, 5e5, n_days),
            },
            index=idx,
        )
    return out
