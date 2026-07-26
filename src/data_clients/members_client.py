"""
Client for the UK Parliament Members API.

Base URL: https://members-api.parliament.uk
OpenAPI spec: https://members-api.parliament.uk/swagger/v1/swagger.json

Responsible for answering: who is/was an MP, which party were they in,
and — critically — which party were they in ON A GIVEN DATE, since party
membership changes (defections, suspensions, expulsions) and matters a lot
for correctly attributing a vote to "rebelled against their party" vs
"voted with the party they were actually in at the time."

Verified against live responses (not guessed) on 2026-07-26:
- GET /api/Members/Search takes House (1=Commons, 2=Lords), IsCurrentMember,
  skip/take (take is capped at 20 per page, so this paginates).
- GET /api/Members/{id}/Biography returns a "partyAffiliations" list with
  {name, id, startDate, endDate} per party held — this is the party history.

Note: votes_client.get_division_votes already returns each MP's party AS
RECORDED AT THE TIME of that specific division, so cohesion_index does not
strictly need to cross-reference this module for historical vote attribution.
get_member_party_history is still useful for spot-checking defections and for
any analysis that isn't keyed off a specific division.
"""

from src.utils.cache import load_cached_response, save_response
from src.utils.http import get_json

BASE_URL = "https://members-api.parliament.uk"

COMMONS = 1
LORDS = 2


def _normalize_party_name(name):
    """
    Members/Search's "latestParty" field records some Labour MPs as
    "Labour (Co-op)" (formally joint Labour & Co-operative Party members)
    — a distinction NEITHER the Commons Votes API's per-vote Party field
    NOR this same endpoint's own Biography/partyAffiliations history uses
    (both just say "Labour", confirmed against live data on 2026-07-26).
    Co-op MPs sit with and take the whip as Labour for every practical
    purpose. Without normalizing this, get_all_members would undercount
    the governing party's seats by however many Co-op MPs there are
    (43 out of 403 Labour seats when this was found) — a large, real error
    in majority-size calculations, not a cosmetic one.
    """
    if name and name.endswith(" (Co-op)"):
        return name[: -len(" (Co-op)")]
    return name


def get_all_members(house=COMMONS, is_current_member=True, use_cache=True):
    """
    Return all members of the given House.

    Args:
        house: COMMONS (1) or LORDS (2).
        is_current_member: True for sitting members only, False includes
            former members too.
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {id, name, party, party_id, constituency,
        membership_start_date, membership_end_date}
    """
    cache_key = f"members_house{house}_current{is_current_member}"
    if use_cache:
        cached = load_cached_response("members_client", cache_key)
        if cached is not None:
            return cached

    all_members = []
    skip = 0
    take = 20  # API-enforced maximum per page

    while True:
        params = {
            "House": house,
            "IsCurrentMember": is_current_member,
            "skip": skip,
            "take": take,
        }
        data = get_json(f"{BASE_URL}/api/Members/Search", params=params)

        for item in data["items"]:
            member = item["value"]
            party = member.get("latestParty")
            house_membership = member.get("latestHouseMembership") or {}
            all_members.append({
                "id": member["id"],
                "name": member["nameDisplayAs"],
                "party": _normalize_party_name(party["name"]) if party else None,
                "party_id": party["id"] if party else None,
                "constituency": house_membership.get("membershipFrom"),
                "membership_start_date": house_membership.get("membershipStartDate"),
                "membership_end_date": house_membership.get("membershipEndDate"),
            })

        if len(data["items"]) < take:
            break
        skip += take

    save_response("members_client", cache_key, all_members)
    return all_members


def get_members_as_of_date(date, house=COMMONS, use_cache=True):
    """
    Return everyone who was a sitting member of the given House on a
    specific date — NOT just current members, and NOT excluding people who
    have since left.

    Uses the API's MembershipInDateRange filter (verified live on
    2026-07-26: passing the same date as both bounds returns exactly who
    was sitting that day — confirmed against a known date, returned 650
    Commons members).

    IMPORTANT: the "party" field returned here is each member's CURRENT
    (latest) party, not necessarily their party on `date` — a member's
    party can change after this date via defection/suspension (e.g. Diane
    Abbott: Labour 2024-05-28 to 2025-07-17, Independent since). Do not use
    this field for historical seat-counting — combine with
    get_member_party_history(member_id) and pick whichever affiliation
    entry actually covers `date` instead.

    Args:
        date: "yyyy-MM-dd" string.
        house: COMMONS (1) or LORDS (2).
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {id, name, constituency} (party deliberately
        omitted — see warning above).
    """
    cache_key = f"members_asof_{date}_house{house}"
    if use_cache:
        cached = load_cached_response("members_client", cache_key)
        if cached is not None:
            return cached

    all_members = []
    skip = 0
    take = 20  # API-enforced maximum per page

    while True:
        params = {
            "MembershipInDateRange.WasMemberOnOrAfter": date,
            "MembershipInDateRange.WasMemberOnOrBefore": date,
            "MembershipInDateRange.WasMemberOfHouse": house,
            "skip": skip,
            "take": take,
        }
        data = get_json(f"{BASE_URL}/api/Members/Search", params=params)

        for item in data["items"]:
            member = item["value"]
            house_membership = member.get("latestHouseMembership") or {}
            all_members.append({
                "id": member["id"],
                "name": member["nameDisplayAs"],
                "constituency": house_membership.get("membershipFrom"),
            })

        if len(data["items"]) < take:
            break
        skip += take

    save_response("members_client", cache_key, all_members)
    return all_members


def get_member_party_history(member_id, use_cache=True):
    """
    Return a member's party affiliation history over time.

    Args:
        member_id: Parliament member id.
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {party, party_id, start_date, end_date}, in the
        order the API returns them (observed as oldest-first, but don't
        rely on that — sort by start_date if order matters).
    """
    cache_key = f"party_history_{member_id}"
    if use_cache:
        cached = load_cached_response("members_client", cache_key)
        if cached is not None:
            return cached

    data = get_json(f"{BASE_URL}/api/Members/{member_id}/Biography")

    affiliations = data["value"]["partyAffiliations"]
    history = [
        {
            "party": a["name"],
            "party_id": a["id"],
            "start_date": a["startDate"],
            "end_date": a["endDate"],
        }
        for a in affiliations
    ]

    save_response("members_client", cache_key, history)
    return history
