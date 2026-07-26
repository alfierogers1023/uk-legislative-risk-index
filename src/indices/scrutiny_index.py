"""
Scrutiny sub-index: legislative friction from Bills API data.

Core idea: for a given bill, measure how much time and contest it's
accumulating relative to similar bills (same type, same stage) — e.g. days
spent in committee, number of amendments tabled, proportion of amendments
that were contested rather than accepted on the nod. High relative friction
= elevated risk of delay, substantial rewrite, or failure.

This is the sub-index designed to be continuously live: unlike cohesion
(which is only interesting around rare events), there are always bills in
progress, so this always has a current answer for "how much friction is
legislation facing right now."

Depends on:
- src/data_clients/bills_client.py for stage/amendment data

Does not depend on cohesion_index.py — keep independent.

Design decisions made here (see CLAUDE.md for reasoning), resolving the
open questions the original stub left:

- Comparison baseline: this module does NOT decide which bills are
  "comparable" — that's a modelling choice that belongs to the caller
  (composite_index.py or a notebook), since it depends on what you're
  trying to answer (same bill_type_id via bills_client.get_bill_types is
  the obvious starting point, since a Government Bill and a Private
  Member's Bill have very different normal friction levels). This module
  just does the relative-scoring math once given a comparison group of
  bill_ids.
- "Committee time" is measured as sitting-day COUNT, not calendar days
  elapsed. The API gives sitting dates, not explicit stage start/end
  dates, and sitting-day count is a more direct, less noisy proxy for
  actual committee scrutiny than calendar span (which is dominated by
  recess and scheduling, not scrutiny).
- "Contested" amendments are those the API recorded a real decision on
  through debate: Agreed, Withdrawn, or NegativedOnDivision. NotCalled,
  NotSelected, and NoDecision mean the amendment was never actually
  reached/engaged with (a Speaker/chair selection or time constraint, not
  friction) — verified against a real bill's amendment data on 2026-07-26,
  where all six of these decision values occur. Known limitation: "Agreed"
  doesn't distinguish "agreed on the nod" from "agreed after a division" —
  the API doesn't expose that distinction, so this proxy will slightly
  overstate contest on bills with many uncontroversial but formally-voted
  amendments.
"""

from src.data_clients.bills_client import get_bill_amendments, get_bill_stages

CONTESTED_DECISIONS = {"Agreed", "Withdrawn", "NegativedOnDivision"}
NOT_REACHED_DECISIONS = {"NoDecision", "NotCalled", "NotSelected"}


def compute_bill_friction(bill_id):
    """
    Compute a friction breakdown for a single bill based on its stage
    timing and amendment activity so far.

    Args:
        bill_id: Parliament bill id.

    Returns:
        dict: {
            bill_id,
            commons_committee_sitting_days, lords_committee_sitting_days,
            total_amendments, contested_amendments, contested_proportion,
        }
        contested_proportion is 0.0 if no amendments have been tabled yet
        (e.g. bill hasn't reached committee).
    """
    stages = get_bill_stages(bill_id)

    commons_committee_days = 0
    lords_committee_days = 0
    total_amendments = 0
    contested_amendments = 0

    for stage in stages:
        if stage["description"] == "Committee stage":
            if stage["house"] == "Commons":
                commons_committee_days += len(stage["sitting_dates"])
            elif stage["house"] == "Lords":
                lords_committee_days += len(stage["sitting_dates"])

        amendments = get_bill_amendments(bill_id, stage["bill_stage_id"])
        total_amendments += len(amendments)
        contested_amendments += sum(
            1 for a in amendments if a["decision"] in CONTESTED_DECISIONS
        )

    contested_proportion = (
        contested_amendments / total_amendments if total_amendments > 0 else 0.0
    )

    return {
        "bill_id": bill_id,
        "commons_committee_sitting_days": commons_committee_days,
        "lords_committee_sitting_days": lords_committee_days,
        "total_amendments": total_amendments,
        "contested_amendments": contested_amendments,
        "contested_proportion": contested_proportion,
    }


def compute_relative_friction(bill_id, comparison_group):
    """
    Compute a bill's friction relative to a comparison group of similar
    bills, rather than as an absolute number.

    Args:
        bill_id: Parliament bill id.
        comparison_group: list of bill_ids to compare against. Choosing
            this list is a deliberate modelling decision left to the
            caller — e.g. bills with the same bill_type_id from the same
            or a recent session (see bills_client.get_bills). Do not pass
            "all bills ever" as a default — a Government Bill compared
            against the entire historical mix of bill types isn't a
            meaningful baseline.

    Returns:
        dict: {
            bill_id,
            own_friction: compute_bill_friction(bill_id)'s result,
            comparison_group_size,
            comparison_group_avg_committee_sitting_days (Commons + Lords summed),
            comparison_group_avg_contested_proportion,
            committee_sitting_days_ratio,   # own / comparison average
            contested_proportion_ratio,     # own / comparison average
        }
        A ratio of 1.5 means 50% more friction than the comparison group's
        average on that metric. Ratios are None if the comparison group's
        average for that metric is 0 (can't meaningfully express "relative
        to zero").
    """
    own_friction = compute_bill_friction(bill_id)
    own_committee_days = (
        own_friction["commons_committee_sitting_days"]
        + own_friction["lords_committee_sitting_days"]
    )

    comparison_friction = [compute_bill_friction(b) for b in comparison_group]
    group_size = len(comparison_friction)

    if group_size == 0:
        raise ValueError(
            "compute_relative_friction needs a non-empty comparison_group — "
            "an empty group has no baseline to compare against."
        )

    avg_committee_days = sum(
        f["commons_committee_sitting_days"] + f["lords_committee_sitting_days"]
        for f in comparison_friction
    ) / group_size
    avg_contested_proportion = sum(
        f["contested_proportion"] for f in comparison_friction
    ) / group_size

    return {
        "bill_id": bill_id,
        "own_friction": own_friction,
        "comparison_group_size": group_size,
        "comparison_group_avg_committee_sitting_days": avg_committee_days,
        "comparison_group_avg_contested_proportion": avg_contested_proportion,
        "committee_sitting_days_ratio": (
            own_committee_days / avg_committee_days
            if avg_committee_days > 0
            else None
        ),
        "contested_proportion_ratio": (
            own_friction["contested_proportion"] / avg_contested_proportion
            if avg_contested_proportion > 0
            else None
        ),
    }
