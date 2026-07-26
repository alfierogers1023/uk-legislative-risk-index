"""
Tests for src/data_clients/members_client.py

These hit the real live Members API rather than fixtures or mocked data —
the whole point of this project is correctness against real Parliament
data, so a test that only proves a hand-written mock matches itself would
prove nothing. Requires network access.
"""

from src.data_clients.members_client import (
    LORDS,
    get_all_members,
    get_member_party_history,
)

STARMER_MEMBER_ID = 4514


def test_get_all_members_returns_current_commons_mps():
    members = get_all_members(use_cache=False)

    # There are 650 Commons seats; a handful may be vacant at any time, so
    # allow some slack either side rather than asserting an exact count.
    assert 600 < len(members) < 660

    ids = [m["id"] for m in members]
    assert len(ids) == len(set(ids)), "member ids should be unique"

    for m in members:
        assert m["id"] and m["name"] and m["constituency"]


def test_get_all_members_house_filter_changes_result():
    commons = get_all_members(use_cache=False)
    lords = get_all_members(house=LORDS, use_cache=False)

    commons_ids = {m["id"] for m in commons}
    lords_ids = {m["id"] for m in lords}
    assert commons_ids.isdisjoint(lords_ids)


def test_get_member_party_history_known_member():
    history = get_member_party_history(STARMER_MEMBER_ID, use_cache=False)

    assert len(history) >= 1
    for affiliation in history:
        assert affiliation["party"]
        assert affiliation["start_date"]
