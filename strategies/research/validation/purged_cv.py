"""Purged / embargo splits and combinatorial purged paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, List, Sequence, Tuple

import numpy as np
import pandas as pd


@dataclass
class PurgedSplit:
    train_idx: np.ndarray
    test_idx: np.ndarray


def purged_train_test_split(
    n_samples: int,
    *,
    test_ratio: float = 0.2,
    embargo: int = 5,
    purge: int = 5,
) -> PurgedSplit:
    """Single holdout with purge before test and embargo after test."""
    n_test = max(1, int(n_samples * test_ratio))
    test_start = n_samples - n_test
    test_idx = np.arange(test_start, n_samples)
    train_end = max(0, test_start - purge)
    train_idx = np.arange(0, train_end)
    # Embargo: drop train samples that fall within embargo after a prior test — N/A for single split
    # For walk-forward, embargo applies after each test fold (see below)
    return PurgedSplit(train_idx=train_idx, test_idx=test_idx)


def walk_forward_purged(
    n_samples: int,
    *,
    n_splits: int = 5,
    embargo: int = 5,
    purge: int = 5,
) -> List[PurgedSplit]:
    """Anchored walk-forward with purge before each test block and embargo gap."""
    if n_splits < 2 or n_samples < n_splits * 10:
        return [purged_train_test_split(n_samples, embargo=embargo, purge=purge)]
    fold = n_samples // (n_splits + 1)
    splits = []
    for i in range(1, n_splits + 1):
        test_start = fold * i
        test_end = min(n_samples, fold * (i + 1))
        if test_end <= test_start:
            continue
        test_idx = np.arange(test_start, test_end)
        train_end = max(0, test_start - purge)
        train_idx = np.arange(0, train_end)
        # Embargo: remove last `embargo` of train if overlapping info
        if embargo > 0 and len(train_idx) > embargo:
            train_idx = train_idx[:-embargo]
        splits.append(PurgedSplit(train_idx=train_idx, test_idx=test_idx))
    return splits


def combinatorial_purged_paths(
    n_samples: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: int = 3,
    purge: int = 3,
    max_paths: int = 30,
) -> List[PurgedSplit]:
    """
    Combinatorial purged CV (simplified): choose combinations of test groups.
    Caps path count for CI speed.
    """
    from itertools import combinations

    if n_groups < 3 or n_samples < n_groups * 5:
        return walk_forward_purged(n_samples, n_splits=4, embargo=embargo, purge=purge)

    edges = np.linspace(0, n_samples, n_groups + 1, dtype=int)
    groups = [np.arange(edges[i], edges[i + 1]) for i in range(n_groups)]
    paths: List[PurgedSplit] = []
    for test_ids in combinations(range(n_groups), n_test_groups):
        test_idx = np.concatenate([groups[i] for i in test_ids])
        train_parts = []
        for i in range(n_groups):
            if i in test_ids:
                continue
            g = groups[i]
            # Purge near adjacent test groups
            lo, hi = g[0], g[-1]
            for tid in test_ids:
                t0, t1 = groups[tid][0], groups[tid][-1]
                if hi < t0:
                    hi = min(hi, t0 - purge)
                if lo > t1:
                    lo = max(lo, t1 + purge + embargo)
            if hi > lo:
                train_parts.append(np.arange(lo, hi + 1))
        if not train_parts or len(test_idx) < 5:
            continue
        train_idx = np.unique(np.concatenate(train_parts))
        # Remove embargo band around each test block
        mask = np.ones(len(train_idx), dtype=bool)
        for tid in test_ids:
            t0, t1 = groups[tid][0], groups[tid][-1]
            ban_lo, ban_hi = t0 - embargo, t1 + embargo
            mask &= ~((train_idx >= ban_lo) & (train_idx <= ban_hi))
        train_idx = train_idx[mask]
        if len(train_idx) < 10:
            continue
        paths.append(PurgedSplit(train_idx=train_idx, test_idx=np.sort(test_idx)))
        if len(paths) >= max_paths:
            break
    return paths or walk_forward_purged(n_samples, embargo=embargo, purge=purge)


def split_returns_by_index(
    returns: pd.Series,
    split: PurgedSplit,
) -> Tuple[pd.Series, pd.Series]:
    r = returns.reset_index(drop=True)
    return r.iloc[split.train_idx], r.iloc[split.test_idx]
