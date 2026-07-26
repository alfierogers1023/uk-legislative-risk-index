"""
Composite Legislative Risk Score: combines cohesion_index and
scrutiny_index into a single score.

This module is a thin combination layer, not where the real logic lives.

Two natural outputs:
- Parliament-level score over time: how stable/gridlocked is government
  right now (driven mainly by cohesion, informed by aggregate scrutiny
  levels across all live bills).
- Bill-level score: how likely is this specific bill to pass on schedule
  (driven mainly by that bill's scrutiny/friction score, informed by
  current government cohesion as context).

Phase 1 decision (see CLAUDE.md): use fixed, documented weights — do not
build context-dependent weighting (e.g. "cohesion matters more near a
confidence vote") yet, that requires event detection on top of an index
that hasn't run once. Once real numbers exist, pick the fixed split
deliberately and record the reasoning here rather than leaving it
unexplained. Dynamic weighting is a Phase 1.5 idea at earliest.

Weights chosen for Phase 1 (equal split, revisit once real numbers exist):
- Parliament-level score: 70% cohesion, 30% scrutiny (cohesion is the
  primary "is government stable" signal; aggregate scrutiny is context).
- Bill-level score: 70% scrutiny, 30% cohesion (scrutiny is the primary
  "will this bill pass on schedule" signal; cohesion is context — a bill
  faces more risk when the government backing it is shakier).
These are arbitrary-but-documented starting points, not validated weights.

Depends on:
- src/indices/cohesion_index.py
- src/indices/scrutiny_index.py
"""

from src.indices.cohesion_index import compute_cohesion_score
from src.indices.scrutiny_index import compute_relative_friction

PARLIAMENT_LEVEL_COHESION_WEIGHT = 0.7
PARLIAMENT_LEVEL_SCRUTINY_WEIGHT = 0.3

BILL_LEVEL_SCRUTINY_WEIGHT = 0.7
BILL_LEVEL_COHESION_WEIGHT = 0.3


def compute_parliament_risk_score(
    governing_party, start_date, end_date, majority_size, live_bill_friction_ratios
):
    """
    Compute the whole-Parliament Legislative Risk Score over a date range.

    Args:
        governing_party, start_date, end_date, majority_size: passed
            straight through to cohesion_index.compute_cohesion_score.
        live_bill_friction_ratios: list of contested_proportion_ratio
            values (from scrutiny_index.compute_relative_friction) for
            bills currently in progress — the caller decides which bills
            count as "live" and builds each one's comparison group, this
            function just aggregates the ratios it's given. Pass an empty
            list if no bills are currently in progress.

    Returns:
        float in [0, 1] where 1 = lowest risk (fully cohesive government,
        low aggregate scrutiny) and 0 = highest risk.
    """
    cohesion_score = compute_cohesion_score(
        governing_party, start_date, end_date, majority_size
    )

    if live_bill_friction_ratios:
        avg_friction_ratio = sum(live_bill_friction_ratios) / len(
            live_bill_friction_ratios
        )
        # A ratio of 1.0 (average friction) maps to a neutral scrutiny
        # score of 0.5; higher-than-average friction pulls it towards 0,
        # lower-than-average friction pulls it towards 1 — clamped both
        # ends so a well-below-average ratio can't push the score past 1.
        scrutiny_score = max(0.0, min(1.0, 1 - (avg_friction_ratio - 1) * 0.5))
    else:
        scrutiny_score = 1.0

    return (
        PARLIAMENT_LEVEL_COHESION_WEIGHT * cohesion_score
        + PARLIAMENT_LEVEL_SCRUTINY_WEIGHT * scrutiny_score
    )


def compute_bill_risk_score(
    bill_id, comparison_group, governing_party, start_date, end_date, majority_size
):
    """
    Compute the Legislative Risk Score for a specific bill as of a given
    date range.

    Args:
        bill_id, comparison_group: passed to
            scrutiny_index.compute_relative_friction.
        governing_party, start_date, end_date, majority_size: passed to
            cohesion_index.compute_cohesion_score, as context for how
            stable the backing government currently is.

    Returns:
        float in [0, 1] where 1 = lowest risk (low relative friction,
        cohesive government) and 0 = highest risk.
    """
    relative_friction = compute_relative_friction(bill_id, comparison_group)
    friction_ratio = relative_friction["contested_proportion_ratio"]

    if friction_ratio is None:
        # Comparison group had zero contested amendments on average — this
        # bill's own contest level (if any) can't be expressed as a ratio
        # against a zero baseline, so treat it as neutral.
        scrutiny_score = 0.5
    else:
        # Clamped both ends — see compute_parliament_risk_score for why the
        # upper clamp matters (a below-average friction_ratio would
        # otherwise push this past 1).
        scrutiny_score = max(0.0, min(1.0, 1 - (friction_ratio - 1) * 0.5))

    cohesion_score = compute_cohesion_score(
        governing_party, start_date, end_date, majority_size
    )

    return (
        BILL_LEVEL_SCRUTINY_WEIGHT * scrutiny_score
        + BILL_LEVEL_COHESION_WEIGHT * cohesion_score
    )
