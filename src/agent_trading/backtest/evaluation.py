"""Chronological train / validation / holdout splits.

* Train:      the oldest slice; rules are developed here.
* Validation: the next slice; results are checked here.
* Holdout:    the most recent slice. The evaluate-* commands never touch it,
              so it stays available for one final, untuned test.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Splits:
    train: tuple[pd.Timestamp, pd.Timestamp]
    validation: tuple[pd.Timestamp, pd.Timestamp]
    holdout: tuple[pd.Timestamp, pd.Timestamp]


def make_splits(dates: list[pd.Timestamp], warmup: int, train_frac: float, val_frac: float) -> Splits:
    usable = dates[warmup:]
    n = len(usable)
    if n < 120:
        raise ValueError(f"only {n} bars after a {warmup}-bar warm-up; need at least 120 for a three-way split")
    t_end = int(n * train_frac)
    v_end = int(n * (train_frac + val_frac))
    return Splits((usable[0], usable[t_end - 1]), (usable[t_end], usable[v_end - 1]), (usable[v_end], usable[-1]))
