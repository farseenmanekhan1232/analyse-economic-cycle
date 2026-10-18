"""Triple-barrier labeling (AFML-style)."""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def apply_triple_barrier(
    ohlcv: pd.DataFrame,
    *,
    pt_mult: float = 2.0,
    sl_mult: float = 2.0,
    max_holding: int = 20,
    atr_period: int = 14,
    side: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """
    For each bar t, walk forward until profit-take, stop-loss, or vertical barrier.

    Returns DataFrame indexed like ohlcv with:
      label ∈ {1, -1, 0}  (touch upper / lower / vertical; sign follows side)
      ret, bars_held, touch ('pt'|'sl'|'vb')
    """
    df = ohlcv.copy()
    df.index = pd.to_datetime(df.index).normalize()
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    close = df["close"].astype(float)
    high = df["high"].astype(float) if "high" in df.columns else close
    low = df["low"].astype(float) if "low" in df.columns else close
    atr = _atr(df, atr_period)

    if side is None:
        side = pd.Series(1, index=df.index)
    else:
        side = side.reindex(df.index).fillna(0).astype(int)

    labels = []
    n = len(df)
    idx = df.index
    for i in range(n):
        s = int(side.iloc[i])
        if s == 0 or not np.isfinite(atr.iloc[i]) or atr.iloc[i] <= 0:
            labels.append(
                {"label": 0, "ret": 0.0, "bars_held": 0, "touch": "flat"}
            )
            continue
        entry = float(close.iloc[i])
        pt = entry + s * pt_mult * float(atr.iloc[i])
        sl = entry - s * sl_mult * float(atr.iloc[i])
        end = min(i + max_holding, n - 1)
        touch = "vb"
        exit_px = float(close.iloc[end])
        held = end - i
        for j in range(i + 1, end + 1):
            hi = float(high.iloc[j])
            lo = float(low.iloc[j])
            if s > 0:
                if lo <= sl:
                    touch, exit_px, held = "sl", sl, j - i
                    break
                if hi >= pt:
                    touch, exit_px, held = "pt", pt, j - i
                    break
            else:
                if hi >= sl:
                    touch, exit_px, held = "sl", sl, j - i
                    break
                if lo <= pt:
                    touch, exit_px, held = "pt", pt, j - i
                    break
        ret = s * (exit_px / entry - 1.0)
        if touch == "pt":
            lab = 1
        elif touch == "sl":
            lab = -1
        else:
            lab = 0
        # Meta-label target: success if positive ret
        labels.append(
            {
                "label": lab,
                "bin_success": int(ret > 0),
                "ret": round(ret, 6),
                "bars_held": held,
                "touch": touch,
                "side": s,
            }
        )

    out = pd.DataFrame(labels, index=idx)
    return out
