"""
Cohesion sub-index: government/party stability from Commons division data.

Core idea: for each division, compare how each MP voted to how their party
majority voted. An MP voting against their own party's majority position is
a "rebellion." Aggregate rebellion rate over a rolling time window (e.g. per
month, or per N divisions) per party, and for the governing party/coalition
specifically.

Rising rebellion rate among governing-party MPs = falling cohesion = rising
political risk. This is the same logic used to flag coalition-government
instability in sovereign risk work, applied to the UK's single governing
party (or coalition).

Two refinements that matter and are implemented here (see CLAUDE.md for the
reasoning):
- Rebellion is scored relative to the governing majority, not as a bare
  rate — 5% rebelling means something completely different at a majority of
  1 versus a majority of 170.
- The largest single-division rebellion in a window is tracked separately
  from the rolling average, since averaging can hide the one event that
  actually matters (one 100-rebel division vs fifty 2-rebel divisions
  average out to look the same).

Depends on:
- src/data_clients/votes_client.py for division/vote data — each vote
  record already includes the member's party AS RECORDED AT THE TIME of
  that division, so this module does not need to separately look up
  members_client's party history for standard rebellion attribution.

Does not depend on scrutiny_index.py — keep these independent so each can
be built, tested, and sanity-checked on its own before combining.
"""

from src.data_clients.votes_client import get_divisions, get_division_votes


def _party_division_breakdown(party, start_date, end_date):
    """
    For every division in the window, work out how the given party voted
    and how many of its own members rebelled against their party's own
    majority position.

    A party's "majority position" is whichever way (Aye/No) more of its
    voting members went on that division — this is a proxy for the party
    line, since official whip instructions aren't published data.
    Members recorded as NoVoteRecorded (absent) are excluded from both the
    majority calculation and the rebel count, since abstention isn't the
    same claim as active defiance.

    Returns:
        list of dicts, one per division the party actually voted in:
        {division_id, date, title, party_votes_cast, rebel_count, rebellion_rate}
        Divisions where the party cast fewer than 2 votes are skipped —
        "rebellion rate" isn't meaningful for a division with 0 or 1 voters.
    """
    breakdown = []

    for division in get_divisions(start_date=start_date, end_date=end_date):
        votes = get_division_votes(division["division_id"])
        party_votes = [
            v for v in votes if v["party"] == party and v["vote"] in ("Aye", "No")
        ]

        if len(party_votes) < 2:
            continue

        aye_count = sum(1 for v in party_votes if v["vote"] == "Aye")
        no_count = len(party_votes) - aye_count
        majority_vote = "Aye" if aye_count >= no_count else "No"
        rebel_count = sum(1 for v in party_votes if v["vote"] != majority_vote)

        breakdown.append({
            "division_id": division["division_id"],
            "date": division["date"],
            "title": division["title"],
            "party_votes_cast": len(party_votes),
            "rebel_count": rebel_count,
            "rebellion_rate": rebel_count / len(party_votes),
        })

    return breakdown


def compute_rebellion_rate(party, start_date, end_date):
    """
    Compute the rebellion rate for a given party over a date range.

    Args:
        party: party name to score (must match the "Party" string used by
            the Commons Votes API, e.g. "Labour", "Conservative").
        start_date, end_date: "yyyy-MM-dd" window to aggregate over.

    Returns:
        float in [0, 1]: total rebel votes / total party votes cast across
        every division in the window (i.e. weighted by how many members
        actually voted each time, not a plain average-of-divisions).
        Returns 0.0 if the party cast no qualifying votes in the window.
    """
    breakdown = _party_division_breakdown(party, start_date, end_date)

    total_votes_cast = sum(d["party_votes_cast"] for d in breakdown)
    if total_votes_cast == 0:
        return 0.0

    total_rebels = sum(d["rebel_count"] for d in breakdown)
    return total_rebels / total_votes_cast


def compute_max_single_division_rebellion(party, start_date, end_date):
    """
    Return the single division within the window where this party had the
    most rebels, not averaged with anything else.

    A rolling average of rebellion rate hides exactly the event a risk
    index should care about: 50 divisions with 2 rebels each and one
    division with 100 rebels can average out to look identical. This
    function exists so that tail event doesn't get smoothed away —
    composite_index.py should treat this as a distinct input, not a
    replacement for compute_rebellion_rate.

    Returns:
        dict {division_id, date, title, party_votes_cast, rebel_count,
        rebellion_rate}, or None if the party cast no qualifying votes in
        the window.
    """
    breakdown = _party_division_breakdown(party, start_date, end_date)
    if not breakdown:
        return None

    return max(breakdown, key=lambda d: d["rebel_count"])


def compute_cohesion_score(party, start_date, end_date, majority_size):
    """
    Turn rebellion into a cohesion score, normalized by how large the
    governing majority is.

    This is not optional: an absolute rebellion rate means something
    completely different depending on majority size. Approximation used
    here (documented, not exact whip arithmetic): each rebel effectively
    swings a vote's margin by two (one lost for the government side, one
    gained for the opposition side), so a rebellion of roughly
    majority_size / 2 is "enough to flip a vote in theory". Per division:

        risk_fraction = min(rebel_count / (majority_size / 2), 1.0)
        cohesion_score = 1 - risk_fraction

    The window's score is the plain average of this across qualifying
    divisions — a simple, transparent choice for a first version, not a
    claim that every division matters equally in reality.

    Args:
        party, start_date, end_date: as in compute_rebellion_rate.
        majority_size: the governing party/coalition's working majority as
            of this window (seats above the 50%-of-voting-members
            threshold — get total seats from members_client.get_all_members
            and subtract). Must be a positive number; a hung parliament
            (majority_size <= 0) isn't handled by this simple formula.

    Returns:
        float in [0, 1], where 1 = no rebellions large enough to matter,
        0 = at least one division saw rebellion at or above the
        vote-flipping threshold. Returns 1.0 if the party cast no
        qualifying votes in the window (no evidence of instability).
    """
    if majority_size <= 0:
        raise ValueError(
            "compute_cohesion_score's majority-normalized formula requires "
            "majority_size > 0 — a hung parliament isn't handled by this "
            "simple version."
        )

    breakdown = _party_division_breakdown(party, start_date, end_date)
    if not breakdown:
        return 1.0

    flip_threshold = majority_size / 2
    scores = [
        1 - min(d["rebel_count"] / flip_threshold, 1.0) for d in breakdown
    ]
    return sum(scores) / len(scores)
