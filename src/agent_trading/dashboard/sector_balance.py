"""A deterministic, auditable soft penalty on concentrated candidate lists."""

from collections import Counter
from dataclasses import replace

from . import scoring, spec


def sector_penalty(scores: list[scoring.Score], sectors: dict[str, str | None], size: int) -> list[scoring.Score]:
    """Rerank copies once using the unadjusted, eligible top-list composition.

    The same penalty applies to all candidates in an overrepresented sector,
    including challengers outside the original cutoff. No iterative oscillation
    and no cumulative deduction when invoked again on adjusted scores.
    """
    raw = [replace(s, composite=s.raw_composite if s.raw_composite is not None else s.composite) for s in scores]
    baseline = scoring.rank(raw)[: max(0, size)]
    if not baseline:
        return []
    normalized = {t: v.strip().casefold() if isinstance(v, str) else "unknown" for t, v in sectors.items()}
    counts = Counter(normalized.get(s.ticker, "unknown") for s in baseline)
    threshold = spec.RESILIENCE_RULES["sector_threshold"]
    maximum = spec.RESILIENCE_RULES["sector_max_penalty_points"]
    adjusted = []
    for s in raw:
        if s.composite is None or s.excluded_reason:
            continue
        sector = normalized.get(s.ticker, "unknown")
        share = counts[sector] / len(baseline)
        penalty = 0.0 if sector in {"", "unknown", "n/a"} else maximum * max(0, share - threshold) / (1 - threshold)
        penalty = round(min(s.composite, penalty), 2)
        flags = [f for f in s.flags if not f.startswith("Sector concentration penalty:")]
        if penalty:
            flags.append(
                f"Sector concentration penalty: -{penalty:.2f} points; {sectors[s.ticker]} is {share:.0%} of the raw top list"
            )
        adjusted.append(
            replace(
                s,
                raw_composite=s.composite,
                sector_penalty=penalty,
                composite=round(s.composite - penalty, 2),
                flags=flags,
            )
        )
    return scoring.rank(adjusted)
