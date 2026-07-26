"""
Client for the UK Parliament Bills API.

Base URL: https://bills-api.parliament.uk
OpenAPI spec: https://bills-api.parliament.uk/swagger/v1/swagger.json

Responsible for answering: what stage is a bill at, how long has it spent
at each stage, and how much amendment/committee activity has it accumulated?

Verified against live responses (not guessed) on 2026-07-26:
- GET /api/v1/Bills — Session is an integer sessionId (e.g. 40), not a
  "2024-25"-style string. BillType is a list of billTypeId (see
  get_bill_types) — 1 = Government Bill, which is the key field for
  scrutiny_index's "compare against bills of the same category" baseline.
- GET /api/v1/Bills/{billId}/Stages — each stage record includes "house"
  ("Commons"/"Lords") directly, confirming both Houses are covered, not
  just Commons. This matters because for a government with a comfortable
  Commons majority, real friction/defeats usually happen in the Lords.
  Confirmed on a real bill (Employment Rights Act 2025, billId 3737) which
  shows repeated "Consideration of Lords amendments" / "Consideration of
  Commons amendments and/or reasons" ping-pong stages.
- GET /api/v1/Bills/{billId}/Stages/{billStageId}/Amendments — each
  amendment has a "decision" field (e.g. "NoDecision", and per real usage
  also "Agreed"/"Withdrawn"/"Negatived" etc.) and a "sponsors" list with
  each sponsor's party — this is what feeds "proportion of amendments that
  were contested rather than accepted on the nod" in scrutiny_index, and
  lets government-tabled vs opposition-tabled amendments be told apart.

This is the raw material for the scrutiny sub-index in
src/indices/scrutiny_index.py — that module should call these functions
rather than hitting the API directly.
"""

from src.utils.cache import load_cached_response, save_response
from src.utils.http import get_json

BASE_URL = "https://bills-api.parliament.uk"

GOVERNMENT_BILL = 1  # billTypeId — see get_bill_types()


def _paginate(path, params, use_cache, cache_key):
    """
    Shared pagination helper for this API's Skip/Take-based list endpoints.

    Returns the full concatenated "items" list across all pages, and caches
    it under the given cache_key.
    """
    if use_cache:
        cached = load_cached_response("bills_client", cache_key)
        if cached is not None:
            return cached

    all_items = []
    skip = 0
    take = 50

    while True:
        page_params = {**params, "Skip": skip, "Take": take}
        data = get_json(f"{BASE_URL}{path}", params=page_params)

        all_items.extend(data["items"])

        if len(data["items"]) < take:
            break
        skip += take

    save_response("bills_client", cache_key, all_items)
    return all_items


def get_bill_types(use_cache=True):
    """
    Return all bill types (id, category, name) — e.g. id 1 = "Government
    Bill", category "Public". Needed to group bills into a sane comparison
    baseline for scrutiny — a Government Bill and a Private Member's Bill
    have very different normal friction levels.

    Returns:
        list of dicts: {id, category, name}
    """
    cache_key = "bill_types"
    if use_cache:
        cached = load_cached_response("bills_client", cache_key)
        if cached is not None:
            return cached

    data = get_json(f"{BASE_URL}/api/v1/BillTypes")

    types = [
        {"id": t["id"], "category": t["category"], "name": t["name"]}
        for t in data["items"]
    ]
    save_response("bills_client", cache_key, types)
    return types


def get_bills(session_id=None, bill_type_id=None, use_cache=True):
    """
    Return bills, optionally filtered by parliamentary session or bill type.

    Args:
        session_id: integer sessionId (None = all sessions). Look up the
            current session's id from a known bill or the Sittings endpoint.
        bill_type_id: integer billTypeId, e.g. GOVERNMENT_BILL (None = all
            types).
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {bill_id, title, bill_type_id, introduced_session_id,
        current_house, originating_house, is_act, is_defeated, last_update}
    """
    params = {}
    if session_id is not None:
        params["Session"] = session_id
    if bill_type_id is not None:
        params["BillType"] = bill_type_id

    cache_key = f"bills_session{session_id}_type{bill_type_id}"
    raw_items = _paginate("/api/v1/Bills", params, use_cache, cache_key)

    return [
        {
            "bill_id": b["billId"],
            "title": b["shortTitle"],
            "bill_type_id": b["billTypeId"],
            "introduced_session_id": b["introducedSessionId"],
            "current_house": b["currentHouse"],
            "originating_house": b["originatingHouse"],
            "is_act": b["isAct"],
            "is_defeated": b["isDefeated"],
            "last_update": b["lastUpdate"],
        }
        for b in raw_items
    ]


def get_bill_stages(bill_id, use_cache=True):
    """
    Return the stage history for a specific bill, covering BOTH Commons and
    Lords stages (dates entered/left each stage, e.g. First Reading,
    Committee, Report, Third Reading, and Commons/Lords ping-pong stages).

    Args:
        bill_id: Parliament bill id.
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {bill_stage_id, description, house, sort_order,
        sitting_dates}, in the order the API returns them (observed as
        chronological, i.e. sort_order ascending).
    """
    cache_key = f"stages_{bill_id}"
    raw_items = _paginate(
        f"/api/v1/Bills/{bill_id}/Stages", {}, use_cache, cache_key
    )

    return [
        {
            "bill_stage_id": s["id"],
            "description": s["description"],
            "house": s["house"],
            "sort_order": s["sortOrder"],
            "sitting_dates": [
                sitting["date"] for sitting in s.get("stageSittings", [])
            ],
        }
        for s in raw_items
    ]


def get_bill_amendments(bill_id, bill_stage_id, use_cache=True):
    """
    Return amendments tabled at a specific stage of a specific bill.

    Args:
        bill_id: Parliament bill id.
        bill_stage_id: id of the stage to fetch amendments for (from
            get_bill_stages) — amendments are scoped per-stage, not
            per-bill, since the same bill can have amendments at multiple
            stages (Commons committee, Lords committee, etc.).
        use_cache: if True, reuse a previously cached response instead of
            hitting the API again.

    Returns:
        list of dicts: {amendment_id, decision, sponsor_parties}
        decision is a string like "NoDecision"/"Agreed"/"Withdrawn"/
        "Negatived" — this is what feeds the "contested vs accepted on the
        nod" friction calculation. sponsor_parties is a list of the party
        of each sponsoring member, so government-tabled vs opposition-
        tabled amendments can be told apart.
    """
    cache_key = f"amendments_{bill_id}_{bill_stage_id}"
    path = f"/api/v1/Bills/{bill_id}/Stages/{bill_stage_id}/Amendments"
    raw_items = _paginate(path, {}, use_cache, cache_key)

    return [
        {
            "amendment_id": a["amendmentId"],
            "decision": a["decision"],
            "sponsor_parties": [s["party"] for s in a.get("sponsors", [])],
        }
        for a in raw_items
    ]
