"""
Shared reporting helpers used by more than one entry point (the
notebooks/visualise_cohesion_score.py script and the Streamlit dashboard in
app.py). Kept here instead of duplicated in each entry point.

This module intentionally sits above src/indices/ and src/data_clients/ (it's
allowed to import both), unlike those two layers which stay decoupled from
each other.
"""

import calendar
import datetime

import pandas as pd

from src.data_clients.bills_client import get_bills
from src.data_clients.members_client import (
    COMMONS,
    get_all_members,
    get_member_party_history,
    get_members_as_of_date,
)
from src.indices.cohesion_index import (
    compute_cohesion_score,
    compute_max_single_division_rebellion,
    compute_rebellion_rate,
)


def get_governing_party_and_majority():
    """
    Work out the current governing party (most Commons seats) and its
    working majority (seats above the 50%-of-members threshold).

    Returns:
        (party_name, majority_size)
    """
    members = get_all_members(house=COMMONS)
    seat_counts = {}
    for m in members:
        seat_counts[m["party"]] = seat_counts.get(m["party"], 0) + 1

    governing_party = max(seat_counts, key=seat_counts.get)
    governing_seats = seat_counts[governing_party]
    total_seats = len(members)
    majority_size = governing_seats - (total_seats - governing_seats)

    return governing_party, majority_size


def _party_as_of(party_history, date):
    """
    Pick whichever entry in a member's party history covers `date`
    ("yyyy-MM-dd" strings, or full ISO timestamps — only the first 10
    characters are compared, since that's all the API guarantees).

    Returns:
        party name, or None if no entry covers the date (shouldn't happen
        for someone confirmed to have been a sitting member that day, but
        callers should not assume it can never happen).
    """
    date = date[:10]
    for entry in party_history:
        start = entry["start_date"][:10]
        end = entry["end_date"][:10] if entry["end_date"] else None
        if start <= date and (end is None or date <= end):
            return entry["party"]
    return None


def get_party_seat_counts_as_of(date, house=COMMONS):
    """
    Return {party_name: seat_count} for a House as of a specific date,
    using each member's party AS OF THAT DATE — not their current party.

    This matters for any multi-month historical window: a member's current
    party can differ from what it was months or years ago (defections,
    whip suspensions — e.g. a real MP in this dataset was Labour from
    2024-05-28 to 2025-07-17, then Independent). Using current party for a
    date before a defection would misattribute that seat.

    Cost: one API call for the as-of-date member list, plus one
    (cached-after-first-use) party-history call per distinct member who
    served during whatever range of dates this ends up being called across
    — cheap on repeat calls for overlapping windows since party history is
    cached per member_id regardless of which date it's being evaluated for.

    Returns:
        dict {party_name: seat_count}
    """
    members = get_members_as_of_date(date, house=house)
    seat_counts = {}
    for member in members:
        history = get_member_party_history(member["id"])
        party = _party_as_of(history, date)
        seat_counts[party] = seat_counts.get(party, 0) + 1
    return seat_counts


def get_majority_as_of(date, party, house=COMMONS):
    """
    Return a party's working majority in a House as of a specific date —
    seats above the 50%-of-members threshold, using historical (not
    current) party affiliation. See get_party_seat_counts_as_of.

    Returns:
        int (can be negative if the party didn't hold a majority that day).
    """
    seat_counts = get_party_seat_counts_as_of(date, house=house)
    total_seats = sum(seat_counts.values())
    party_seats = seat_counts.get(party, 0)
    return party_seats - (total_seats - party_seats)


def month_windows(months_of_history):
    """
    Build a list of (label, start_date, end_date) for each of the last
    `months_of_history` full calendar months, oldest first. The current
    (partial) month is included too, capped at today.
    """
    today = datetime.date.today()
    windows = []

    year, month = today.year, today.month
    for _ in range(months_of_history):
        start = datetime.date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end = min(datetime.date(year, month, last_day), today)

        windows.append((start.strftime("%Y-%m"), start.isoformat(), end.isoformat()))

        month -= 1
        if month == 0:
            month = 12
            year -= 1

    windows.reverse()
    return windows


def build_monthly_cohesion_table(party, months_of_history):
    """
    Compute rebellion rate, cohesion score, and the worst single-division
    rebel count for each of the last `months_of_history` months.

    Majority size is computed PER MONTH (as of that month's start date),
    not passed in as one fixed value — over a multi-month window the
    governing party's majority can genuinely shift (by-elections,
    defections), and normalizing every month against today's majority
    would silently misjudge older months. See get_majority_as_of.

    Returns:
        pandas.DataFrame with columns: month, majority_size, rebellion_rate,
        cohesion_score, worst_division_rebel_count, worst_division_title,
        worst_division_date
    """
    rows = []
    for label, start, end in month_windows(months_of_history):
        majority_size = get_majority_as_of(start, party)
        rebellion_rate = compute_rebellion_rate(party, start, end)
        cohesion_score = compute_cohesion_score(party, start, end, majority_size)
        worst = compute_max_single_division_rebellion(party, start, end)

        rows.append({
            "month": label,
            "majority_size": majority_size,
            "rebellion_rate": rebellion_rate,
            "cohesion_score": cohesion_score,
            "worst_division_rebel_count": worst["rebel_count"] if worst else 0,
            "worst_division_title": worst["title"] if worst else None,
            "worst_division_date": worst["date"] if worst else None,
        })

    return pd.DataFrame(rows)


def build_comparison_group(bill, max_group_size=8):
    """
    Pick a comparison group of bills for scrutiny_index.compute_relative_friction:
    other bills of the same bill_type_id AND the same introduced_session_id
    (see CLAUDE.md — a Government Bill compared against Private Members'
    Bills isn't a meaningful baseline, and scoping to one session keeps the
    API call fast instead of paginating through the entire historical
    archive of that bill type).

    This is the caller-side decision that scrutiny_index deliberately leaves
    open — see its module docstring.

    Args:
        bill: a bill dict as returned by bills_client.get_bills (must include
            bill_id, bill_type_id, introduced_session_id).
        max_group_size: cap on how many comparison bills to fetch friction
            for — each one costs a live API round trip through every stage
            and amendment, so this is capped to keep dashboard interactions
            from taking minutes.

    Returns:
        list of bill_id, excluding the bill itself.
    """
    same_session_and_type_bills = get_bills(
        session_id=bill["introduced_session_id"], bill_type_id=bill["bill_type_id"]
    )
    candidates = [
        b["bill_id"]
        for b in same_session_and_type_bills
        if b["bill_id"] != bill["bill_id"]
    ]
    return candidates[:max_group_size]
