import logging
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_var(
    returns: pd.Series,
    confidence: float = 0.95,
    method: str = "historical",
) -> float:
    if len(returns) < 20:
        return 0.0

    if method == "historical":
        return float(returns.quantile(1 - confidence))
    elif method == "parametric":
        return float(returns.mean() + returns.std() * -1.645)
    else:
        return float(returns.quantile(1 - confidence))


def compute_cvar(
    returns: pd.Series,
    confidence: float = 0.95,
) -> float:
    var_threshold = compute_var(returns, confidence)
    tail = returns[returns <= var_threshold]
    if tail.empty:
        return var_threshold
    return float(tail.mean())


def compute_max_drawdown(close_prices: pd.Series) -> Tuple[float, pd.Timestamp, pd.Timestamp]:
    if len(close_prices) < 2:
        return 0.0, close_prices.index[0], close_prices.index[0]

    peak = close_prices.expanding().max()
    drawdown = (close_prices - peak) / peak
    max_dd = float(drawdown.min())

    trough_idx = drawdown.idxmin()
    peak_idx = close_prices.loc[:trough_idx].idxmax()

    return max_dd, peak_idx, trough_idx


def compute_calmar_ratio(
    returns: pd.Series,
    close_prices: pd.Series,
) -> float:
    if len(returns) < 12:
        return 0.0

    annual_return = float(returns.mean() * 252)
    max_dd, _, _ = compute_max_drawdown(close_prices)

    if max_dd == 0:
        return float("inf") if annual_return > 0 else 0.0

    return annual_return / abs(max_dd)


def compute_omega_ratio(
    returns: pd.Series,
    threshold: float = 0.0,
) -> float:
    gains = returns[returns > threshold].sum()
    losses = abs(returns[returns <= threshold].sum())

    if losses == 0:
        return float("inf") if gains > 0 else 0.0

    return float(gains / losses)


def risk_parity_weights(
    sector_data: Dict[str, pd.DataFrame],
    target_risk: float = 0.15,
) -> Dict[str, float]:
    volatilities: Dict[str, float] = {}
    for sector, df in sector_data.items():
        if df.empty:
            continue
        close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
        returns = close.pct_change().dropna()
        if len(returns) > 60:
            volatilities[sector] = float(returns.std() * np.sqrt(252))

    if not volatilities:
        equal_weight = 1.0 / max(len(sector_data), 1)
        return {s: equal_weight for s in sector_data}

    inv_vol = {s: 1.0 / v for s, v in volatilities.items()}
    total_inv = sum(inv_vol.values())

    weights: Dict[str, float] = {}
    for sector in sector_data:
        if sector in inv_vol:
            raw_weight = inv_vol[sector] / total_inv
            vol = volatilities[sector]
            scaled_weight = raw_weight * target_risk / vol
            weights[sector] = round(scaled_weight, 6)
        else:
            weights[sector] = 0.0

    w_total = sum(weights.values())
    if w_total > 0:
        weights = {s: round(w / w_total, 4) for s, w in weights.items()}

    return weights


def drawdown_protection_rules(
    sector: str,
    sector_df: pd.DataFrame,
    max_allowed_dd: float = -0.15,
    reduce_factor: float = 0.5,
    exit_threshold: float = -0.25,
) -> Dict[str, any]:
    if sector_df.empty:
        return {"action": "hold", "reason": "no_data"}

    close = sector_df.get("close", sector_df.iloc[:, 0] if sector_df.shape[1] == 1 else pd.Series())

    peak = close.expanding().max()
    current_dd = (close.iloc[-1] - peak.iloc[-1]) / peak.iloc[-1]

    if current_dd <= exit_threshold:
        action = "exit"
        factor = 0.0
    elif current_dd <= max_allowed_dd:
        action = "reduce"
        factor = reduce_factor
    else:
        action = "hold"
        factor = 1.0

    return {
        "action": action,
        "current_drawdown": round(float(current_dd), 4),
        "reduce_factor": factor,
        "sector": sector,
    }


def portfolio_risk_metrics(
    sector_data: Dict[str, pd.DataFrame],
    weights: Dict[str, float],
) -> Dict[str, float]:
    daily_returns: Dict[str, pd.Series] = {}
    for sector, df in sector_data.items():
        if df.empty or sector not in weights:
            continue
        close = df.get("close", df.iloc[:, 0] if df.shape[1] == 1 else pd.Series())
        daily_returns[sector] = close.pct_change().dropna()

    if not daily_returns:
        return {"annualized_return": 0.0, "annualized_volatility": 0.0, "sharpe": 0.0, "max_drawdown": 0.0}

    ret_df = pd.DataFrame(daily_returns)
    ret_df = ret_df.dropna()

    weighted_returns = pd.Series(0.0, index=ret_df.index)
    for sector, w in weights.items():
        if sector in ret_df.columns:
            weighted_returns += ret_df[sector] * w

    ann_return = float(weighted_returns.mean() * 252)
    ann_vol = float(weighted_returns.std() * np.sqrt(252))
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0.0

    cum_returns = (1 + weighted_returns).cumprod()
    max_dd, _, _ = compute_max_drawdown(cum_returns)

    return {
        "annualized_return": round(ann_return, 4),
        "annualized_volatility": round(ann_vol, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(max_dd, 4),
    }
