"""
Client for UK Parliament Commons division (voting) data.

Base URL: https://commonsvotes-api.parliament.uk
OpenAPI spec (older Swashbuckle-style discovery path, not the usual
/swagger/v1/swagger.json): https://commonsvotes-api.parliament.uk/swagger/docs/v1

Verified against live responses (not guessed) on 2026-07-26:
- GET /data/divisions.json/search takes queryParameters.skip/take
  (default take is 25), startDate/endDate ("yyyy-MM-dd"). Returns SUMMARY
  records only (no per-member votes).
- GET /data/division/{divisionId}.json returns the full record including
  "Ayes", "Noes", and "NoVoteRecorded" lists. Each entry already includes
  the member's Party AS RECORDED AT THE TIME of that division — so
  cohesion_index can use this directly without needing to cross-reference
  members_client's party history for standard rebellion attribution.

Responsible for answering: for a given division (vote), which MPs voted
which way (Aye/No/NoVoteRecorded)?

This is the raw material for the cohesion sub-index in
src/indices/cohesion_index.py — that module should call these functions
rather than hitting the API directly, so the two stay decoupled.
"""

from src.utils.cache import load_cached_response, save_response
from src.utils.http import get_json

BASE_URL = "https://commonsvotes-api.parliament.uk"


def get_divisions(start_date=None, end_date=None, use_cache=True):
    """
    Return a list of Commons divisions (votes) within a date range.

    This returns summary records only — it does NOT include how each
    individual MP voted. Call get_division_votes(division_id) for that.

    Args:
        start_date, end_date: "yyyy-MM-dd" strings, or None for no bound.
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {division_id, date, title, aye_count, no_count}
    """
    cache_key = f"divisions_{start_date}_{end_date}"
    if use_cache:
        cached = load_cached_response("votes_client", cache_key)
        if cached is not None:
            return cached

    all_divisions = []
    skip = 0
    take = 25

    while True:
        params = {"queryParameters.skip": skip, "queryParameters.take": take}
        if start_date:
            params["queryParameters.startDate"] = start_date
        if end_date:
            params["queryParameters.endDate"] = end_date

        data = get_json(f"{BASE_URL}/data/divisions.json/search", params=params)

        for d in data:
            all_divisions.append({
                "division_id": d["DivisionId"],
                "date": d["Date"],
                "title": d["Title"],
                "aye_count": d["AyeCount"],
                "no_count": d["NoCount"],
            })

        if len(data) < take:
            break
        skip += take

    save_response("votes_client", cache_key, all_divisions)
    return all_divisions


def get_division_votes(division_id, use_cache=True):
    """
    Return how each MP voted on a specific division, including their party
    as recorded at the time of that division.

    Args:
        division_id: id of the division.
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {member_id, name, party, vote}
        vote is one of "Aye", "No", "NoVoteRecorded" (absent/not recorded).
    """
    cache_key = f"division_votes_{division_id}"
    if use_cache:
        cached = load_cached_response("votes_client", cache_key)
        if cached is not None:
            return cached

    data = get_json(f"{BASE_URL}/data/division/{division_id}.json")

    votes = []
    for member in data["Ayes"]:
        votes.append(_vote_record(member, "Aye"))
    for member in data["Noes"]:
        votes.append(_vote_record(member, "No"))
    for member in data.get("NoVoteRecorded", []):
        votes.append(_vote_record(member, "NoVoteRecorded"))

    save_response("votes_client", cache_key, votes)
    return votes


def _vote_record(member, vote):
    """Build a {member_id, name, party, vote} dict from a raw API member entry."""
    return {
        "member_id": member["MemberId"],
        "name": member["Name"],
        "party": member["Party"],
        "vote": vote,
    }
