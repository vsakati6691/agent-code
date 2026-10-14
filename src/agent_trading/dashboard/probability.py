"""Probability-of-profit contract and validation gate (spec PROBABILITY_GATE). No model is calibrated yet.

Definitions live in spec.py: probability of profit is the probability that net P/L is positive at expiration
after the stated premium and costs; it is distinct from the probability of finishing in the money. A percentage
can reach a page only through `display()`, and only for a CalibrationRecord that passes `validate()`. The
registry below holds no record, so every contract shows spec.PROBABILITY_NOT_ESTABLISHED. Delta, research scores,
scenario weights and pricing-model outputs never enter this module: there is no code path that turns them into a
probability.

DATA_CONTRACT documents what a future calibration dataset must record for each listed contract so that an
estimate can be scored out of sample. Nothing here fabricates historical chains or reuses the consumed holdout.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date

from . import spec

HORIZON_KEYS = tuple(h.key for h in spec.HORIZONS)


@dataclass(frozen=True)
class CalibrationRecord:
    """Out-of-sample calibration evidence for ONE option type at ONE horizon (spec PROBABILITY_GATE)."""
    model_version: str
    option_type: str                 # "call" or "put"
    horizon: str                     # "3m", "6m" or "12m" (spec.HORIZONS)
    evaluation_start: str            # ISO date of the first expiration in the out-of-sample period
    evaluation_end: str              # ISO date of the last expiration
    sample_size: int                 # resolved contracts (expired, outcome known)
    out_of_sample: bool              # every forecast was stored before its outcome was known
    holdout_consumed: bool           # True when the period overlaps a holdout already used for another decision
    calibration_error: float         # expected calibration error across probability bins (0 = perfect)
    brier_score: float
    uncertainty: dict                # e.g. {"method": "bootstrap", "level": 0.95, "ci_width": 0.08}
    data_source: str
    reliability_bins: tuple = ()     # ((predicted, observed, count), ...)
    notes: str = ""


# (option type, horizon) -> the calibration record that would allow a percentage. None everywhere: not established.
REGISTRY: dict[tuple[str, str], CalibrationRecord | None] = {(k, h): None for k in spec.OPTION_TYPES for h in HORIZON_KEYS}

DATA_CONTRACT = {
    "purpose": "What must be stored, per listed contract, before any probability of profit can be calibrated.",
    "record_fields": (
        "as_of (the snapshot session)", "contract (OCC symbol)", "option_type", "horizon", "underlying",
        "underlying_close_at_as_of", "strike", "expiration", "entry_premium (ask x 100, as published)",
        "fees_assumed", "forecast_probability_of_profit (recorded BEFORE expiration)", "forecast_recorded_at",
        "model_version", "realized_underlying_close_at_expiration", "realized_net_pl (after fees)",
        "outcome (1 when realized_net_pl > 0, else 0)", "resolved_at",
    ),
    "resolution": "A contract resolves only at its expiration with a verified closing price from the same price source "
                  "used for the listing; early exits are not modelled.",
    "storage": "Append-only, one line per listed contract, written at listing time and completed at expiration; "
               "never rewritten, never back-filled from later knowledge.",
    "evaluation": "Per option type and horizon: reliability bins, expected calibration error, Brier score and a "
                  "bootstrap interval, over at least PROBABILITY_GATE['min_evaluation_days'] days and "
                  "PROBABILITY_GATE['min_sample_size'] resolved contracts, on forecasts recorded out of sample.",
}


def _as_dict(rec) -> dict:
    return asdict(rec) if is_dataclass(rec) else dict(rec)


def validate(rec, option_type: str | None = None, horizon: str | None = None) -> list[str]:
    """Every reason `rec` fails the gate (empty = it passes). A missing record fails."""
    g = spec.PROBABILITY_GATE
    if rec is None:
        return ["no calibration record exists"]
    d = _as_dict(rec)
    problems = [f"missing field: {f}" for f in g["required_fields"] if d.get(f) in (None, "")]
    if problems:
        return problems
    if d["option_type"] not in spec.OPTION_TYPES:
        problems.append(f"unknown option type {d['option_type']!r}")
    if d["horizon"] not in HORIZON_KEYS:
        problems.append(f"unknown horizon {d['horizon']!r}")
    if g["per_type_and_horizon"]:
        if option_type and d["option_type"] != option_type:
            problems.append(f"record is for {d['option_type']}s, not {option_type}s")
        if horizon and d["horizon"] != horizon:
            problems.append(f"record is for the {d['horizon']} horizon, not {horizon}")
    if int(d["sample_size"]) < g["min_sample_size"]:
        problems.append(f"sample size {int(d['sample_size'])} below the minimum of {g['min_sample_size']}")
    try:
        days = (date.fromisoformat(str(d["evaluation_end"])) - date.fromisoformat(str(d["evaluation_start"]))).days
    except ValueError:
        days = -1
        problems.append("evaluation period dates unreadable")
    if 0 <= days < g["min_evaluation_days"]:
        problems.append(f"evaluation period of {days} days is shorter than {g['min_evaluation_days']} days")
    if g["require_out_of_sample"] and not d["out_of_sample"]:
        problems.append("forecasts were not recorded out of sample")
    if g["forbid_consumed_holdout"] and d["holdout_consumed"]:
        problems.append("the evaluation period reuses a holdout that was already consumed")
    if float(d["calibration_error"]) > g["max_calibration_error"]:
        problems.append(f"calibration error {float(d['calibration_error']):.3f} above {g['max_calibration_error']}")
    unc = d["uncertainty"]
    if g["require_uncertainty"] and not (isinstance(unc, dict) and unc.get("ci_width") is not None):
        problems.append("no uncertainty interval")
    return problems


def display(option_type: str, horizon: str | None, record: CalibrationRecord | None = None,
            pop: float | None = None, itm: float | None = None) -> dict:
    """What a page may show for one contract.

    `pop` and `itm` are a model's estimates for THIS contract; they are returned only when `record` (or the
    registry entry) passes the gate. Otherwise the statement is spec.PROBABILITY_NOT_ESTABLISHED and both
    percentages are None, whatever was passed in."""
    rec = record if record is not None else REGISTRY.get((option_type, horizon))
    problems = validate(rec, option_type, horizon)
    base = {"definition": spec.PROBABILITY_OF_PROFIT_DEFINITION, "itm_definition": spec.ITM_PROBABILITY_DEFINITION,
            "never_substituted": spec.PROBABILITY_NEVER_SUBSTITUTED}
    if problems or pop is None:
        return {**base, "status": "not_established", "statement": spec.PROBABILITY_NOT_ESTABLISHED,
                "probability_of_profit": None, "probability_itm": None, "model_version": None,
                "evaluation_period": None, "sample_size": None, "calibration_error": None, "brier_score": None,
                "uncertainty": None, "why": problems or ["no estimate was produced for this contract"],
                "missing_data": list(spec.PROBABILITY_MISSING_DATA)}
    d = _as_dict(rec)
    return {**base, "status": "calibrated",
            "statement": (f"Probability of profit {float(pop):.0%} (model {d['model_version']}, calibrated out of "
                          f"sample on {int(d['sample_size'])} resolved {option_type}s, {d['evaluation_start']} to "
                          f"{d['evaluation_end']}; calibration error {float(d['calibration_error']):.3f}; "
                          f"uncertainty ±{float(d['uncertainty']['ci_width']) / 2:.0%})"),
            "probability_of_profit": float(pop), "probability_itm": None if itm is None else float(itm),
            "model_version": d["model_version"], "evaluation_period": [d["evaluation_start"], d["evaluation_end"]],
            "sample_size": int(d["sample_size"]), "calibration_error": float(d["calibration_error"]),
            "brier_score": float(d["brier_score"]), "uncertainty": d["uncertainty"], "why": [], "missing_data": []}


def status_summary() -> dict:
    """Registry status for the methodology page: which (type, horizon) cells have a passing record (none)."""
    cells = {f"{k}-{h}": ("calibrated" if not validate(rec, k, h) else "not established")
             for (k, h), rec in REGISTRY.items()}
    return {"cells": cells, "any_calibrated": any(v == "calibrated" for v in cells.values()),
            "statement": spec.PROBABILITY_NOT_ESTABLISHED, "gate": spec.PROBABILITY_GATE,
            "missing_data": list(spec.PROBABILITY_MISSING_DATA), "data_contract": DATA_CONTRACT}
