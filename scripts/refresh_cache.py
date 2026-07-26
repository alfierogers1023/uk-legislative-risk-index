"""
Refresh the committed data/raw/ cache that app.py relies on.

Why this exists: Streamlit Community Cloud's filesystem is ephemeral — it
resets on every redeploy and whenever the app wakes from sleep after being
idle. Without a pre-baked cache, every cold start would repeat the same
multi-minute live API fetch that a fresh local run does, which is a bad
first impression for anyone clicking the link on a CV. So instead of only
gitignoring data/raw/ as regenerated scratch space, this project commits a
deliberately-scoped slice of it: exactly what the dashboard's default view
needs, no more.

Run this locally (or let the scheduled GitHub Action in
.github/workflows/refresh-cache.yml run it) and commit the result:

    python3 scripts/refresh_cache.py
    git add data/raw/ data/cache_metadata.json
    git commit -m "Refresh cached dashboard data"

This bakes the full 24-month slider range (matching the current Parliament's
duration so far — Labour took office 2024-07-05) and the curated bill
shortlist, so the WHOLE default UI is fast. It does NOT bake every possible
"browse all bills" selection — a non-curated bill still hits the live API,
same as it always has, an accepted, clearly-labelled slower path.
"""

import datetime
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.data_clients.bills_client import GOVERNMENT_BILL, get_bills
from src.indices.scrutiny_index import compute_relative_friction
from src.reporting import (
    build_comparison_group,
    build_monthly_cohesion_table,
    get_governing_party_and_majority,
)

# Must match app.py's CURATED_BILLS and its slider's max "Months of history".
CURATED_BILL_IDS = [3737, 4254, 4030]
DEFAULT_MONTHS_OF_HISTORY = 24

METADATA_PATH = os.path.join(PROJECT_ROOT, "data", "cache_metadata.json")


def main():
    print("Warming governing party + majority + members list...")
    party, majority_size = get_governing_party_and_majority()
    print(f"  {party}, working majority {majority_size}")

    print(f"Warming {DEFAULT_MONTHS_OF_HISTORY} months of cohesion data "
          f"(majority computed per-month, not just today's snapshot)...")
    build_monthly_cohesion_table(party, DEFAULT_MONTHS_OF_HISTORY)

    print("Warming current Government Bills list...")
    all_bills = {b["bill_id"]: b for b in get_bills(bill_type_id=GOVERNMENT_BILL)}

    for bill_id in CURATED_BILL_IDS:
        bill = all_bills.get(bill_id)
        if bill is None:
            print(f"  WARNING: curated bill {bill_id} not found in current "
                  f"Government Bills list — skipping (may have left this "
                  f"session or the API returned it under a different id).")
            continue
        print(f"  Warming friction data for {bill['title']} ({bill_id})...")
        comparison_group = build_comparison_group(bill, max_group_size=5)
        compute_relative_friction(bill_id, comparison_group)

    metadata = {
        "last_refreshed": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "governing_party": party,
        "working_majority": majority_size,
        "months_of_history_cached": DEFAULT_MONTHS_OF_HISTORY,
        "curated_bill_ids": CURATED_BILL_IDS,
    }
    with open(METADATA_PATH, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Wrote {METADATA_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()
