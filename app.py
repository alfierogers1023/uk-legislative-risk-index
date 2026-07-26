"""
UK Legislative Risk Index. Streamlit dashboard.

Run with:
    streamlit run app.py

This is a read-only presentation layer over the real logic in src/, it
does not implement any scoring itself, it just calls:
- src/reporting.py for the cohesion trend over time
- src/indices/scrutiny_index.py + src/indices/composite_index.py for the
  bill scrutiny explorer

All data comes from live UK Parliament open data APIs
(developer.parliament.uk), cached to data/raw/ by the data clients so
repeat views are fast. Some bill-level lookups involve dozens of API calls
(one per stage/amendment page) and can take up to a minute on a bill that
hasn't been looked up before, so the curated shortlist below is pre-warmed and
the common path is fast; anything picked from "browse all bills" may be slow
the first time.

data/raw/ is deliberately committed to git (not gitignored) for exactly the
default view (see scripts/refresh_cache.py). Streamlit Community Cloud's
filesystem is ephemeral and resets on every redeploy/wake-from-sleep, so
without a pre-baked cache every cold start would repeat a multi-minute live
fetch. The cache is refreshed on a schedule (see
.github/workflows/refresh-cache.yml), not truly live. The "data last
refreshed" caption below is read from data/cache_metadata.json so that's
honest rather than silently stale.
"""

import datetime
import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.data_clients.bills_client import GOVERNMENT_BILL, get_bills
from src.indices.composite_index import compute_bill_risk_score, compute_parliament_risk_score
from src.indices.scrutiny_index import compute_relative_friction
from src.reporting import (
    build_comparison_group,
    build_monthly_cohesion_table,
    get_governing_party_and_majority,
    get_parties_by_seat_count,
)

# Curated shortlist of real, currently-in-progress Government Bills, chosen
# so the dashboard's default view loads fast (already cached) rather than
# every visitor waiting on a live multi-stage API fetch.
CURATED_BILLS = {
    3737: "Employment Rights Act 2025",
    4254: "Immigration and Asylum Bill",
    4030: "Railways Bill",
    4123: "Steel Industry (Nationalisation) Act 2026",
    4140: "National Security (State Threats) Act 2026",
}

st.set_page_config(page_title="UK Legislative Risk Index", layout="wide")

CACHE_METADATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache_metadata.json")


def load_cache_metadata():
    """
    Read the timestamp scripts/refresh_cache.py wrote, so the dashboard can
    honestly show how stale its pre-baked cache is instead of implying the
    numbers are live-as-of-now.
    """
    if not os.path.exists(CACHE_METADATA_PATH):
        return None
    with open(CACHE_METADATA_PATH) as f:
        return json.load(f)


@st.cache_data(ttl=3600, show_spinner="Fetching Commons party seat counts...")
def load_parties():
    return get_parties_by_seat_count()


@st.cache_data(ttl=3600, show_spinner="Fetching governing party + Commons division data...")
def load_cohesion_table(party, months_of_history):
    # The monthly table computes its own majority per month internally,
    # since that can genuinely differ for older months, and can be negative
    # for a party that doesn't hold a majority (see build_monthly_cohesion_table).
    return build_monthly_cohesion_table(party, months_of_history)


@st.cache_data(ttl=3600, show_spinner="Fetching current Government Bills list...")
def load_government_bills():
    return {b["bill_id"]: b for b in get_bills(bill_type_id=GOVERNMENT_BILL)}


@st.cache_data(ttl=3600, show_spinner="Computing bill friction against a comparison group, this can take a minute for bills with heavy committee activity...")
def load_bill_relative_friction(bill_id, bill_type_id, introduced_session_id):
    bill = {
        "bill_id": bill_id,
        "bill_type_id": bill_type_id,
        "introduced_session_id": introduced_session_id,
    }
    comparison_group = build_comparison_group(bill, max_group_size=5)
    return compute_relative_friction(bill_id, comparison_group), comparison_group


st.title("UK Legislative Risk Index")
st.caption(
    "A composite political-risk index built entirely from UK Parliament open "
    "data ([developer.parliament.uk](https://developer.parliament.uk/)), "
    "no scraping, no manual data entry, every number below traces back to a "
    "live API call."
)

cache_metadata = load_cache_metadata()
if cache_metadata:
    refreshed_at = datetime.datetime.fromisoformat(cache_metadata["last_refreshed"])
    st.caption(
        f"Default view's data was last refreshed **{refreshed_at.strftime('%d %B %Y')}** "
        f"(refreshed on a schedule, not truly live, see `.github/workflows/refresh-cache.yml`). "
        f"Anything outside the default view (a longer history window, a bill "
        f"not in the curated shortlist) is fetched live when you select it."
    )

with st.sidebar:
    st.header("About this index")
    st.markdown(
        """
This project combines two independent signals into one **Legislative Risk
Score**:

**1. Cohesion**: how often MPs rebel against their own party's majority
position in Commons divisions, normalized by the size of the governing
majority (5% rebelling matters enormously at a majority of 1, and barely at
all at a majority of 170).

**2. Scrutiny**: how much committee time and contested-amendment activity a
bill accumulates relative to similar bills, as a proxy for delay/rewrite
risk.

Both track the single worst event in a window, not just the rolling
average. A rolling average can hide the one rebellion or one heavily-fought
bill that actually matters.

Built as a portfolio project applying the same "combine multiple weak
signals into one composite" methodology used in sovereign risk modelling,
to UK Parliament instead of sovereign states.

**Data sources:** UK Parliament Members API, Commons Votes API, Bills API,
all under the Open Parliament Licence, no API key required.
        """
    )
    st.divider()
    st.caption("Source: github.com, see CLAUDE.md for full methodology notes.")

st.header("1. Government Cohesion")

governing_party, governing_majority = get_governing_party_and_majority()

parties = load_parties()
party_options = [p for p, _ in parties]
selected_party = st.selectbox(
    "Which party's cohesion to track?", options=party_options,
    index=party_options.index(governing_party),
    help="Defaults to the governing party. Picking any other party still "
         "shows its rebellion rate and worst single rebellion, but the "
         "majority-normalized cohesion score only applies to a party that "
         "actually holds a majority.",
)
months_of_history = st.slider("Months of history", min_value=3, max_value=24, value=24)
cohesion_table = load_cohesion_table(selected_party, months_of_history)

latest = cohesion_table.iloc[-1]
worst_row = cohesion_table.loc[cohesion_table["worst_division_rebel_count"].idxmax()]
has_majority = cohesion_table["cohesion_score"].notna().any()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Party", selected_party)
col2.metric("Majority (seats above 50%)", int(latest["majority_size"]))
if has_majority:
    col3.metric("Latest month's cohesion score", f"{latest['cohesion_score']:.3f}")
else:
    col3.metric("Latest month's rebellion rate", f"{latest['rebellion_rate']:.1%}")
col4.metric("Worst single rebellion (window)", f"{int(worst_row['worst_division_rebel_count'])} MPs")

if not has_majority:
    st.caption(
        f"{selected_party} doesn't hold a Commons majority in this window, so "
        f"the majority-normalized cohesion score isn't a meaningful concept "
        f"here (see the sidebar methodology). Showing rebellion rate and the "
        f"worst single rebellion instead, both of which work for any party."
    )

fig = go.Figure()
fig.add_trace(go.Bar(
    x=cohesion_table["month"], y=cohesion_table["worst_division_rebel_count"],
    name="Worst single-division rebel count", marker_color="indianred",
    yaxis="y2", opacity=0.55,
))
if has_majority:
    fig.add_trace(go.Scatter(
        x=cohesion_table["month"], y=cohesion_table["cohesion_score"],
        name="Cohesion score (1 = fully cohesive)", mode="lines+markers",
        line=dict(color="royalblue", width=3), yaxis="y1",
        customdata=cohesion_table["majority_size"],
        hovertemplate="Cohesion: %{y:.3f}<br>Majority that month: %{customdata}<extra></extra>",
    ))
    yaxis_title = "Cohesion score"
    yaxis_range = [0, 1.05]
else:
    fig.add_trace(go.Scatter(
        x=cohesion_table["month"], y=cohesion_table["rebellion_rate"],
        name="Rebellion rate", mode="lines+markers",
        line=dict(color="royalblue", width=3), yaxis="y1",
    ))
    yaxis_title = "Rebellion rate"
    yaxis_range = None
fig.update_layout(
    title=f"{selected_party} cohesion over time (latest majority: {int(latest['majority_size'])}. "
          f"Majority can differ month to month due to by-elections/defections)",
    yaxis=dict(title=yaxis_title, range=yaxis_range),
    yaxis2=dict(title="Worst division rebel count", overlaying="y", side="right"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
    height=450,
)
st.plotly_chart(fig, width="stretch")

st.info(
    f"**Biggest single rebellion in this window:** {int(worst_row['worst_division_rebel_count'])} "
    f"{selected_party} MPs rebelled on *{worst_row['worst_division_title']}* "
    f"({str(worst_row['worst_division_date'])[:10]}). The rolling rebellion "
    f"rate alone would have diluted this into the background."
)
st.caption(
    "Caveat: a large split here can also mean a **free vote** (a conscience "
    "issue with no official party position, e.g. assisted dying) rather "
    "than actual whip-discipline instability. Whip status isn't published "
    "data, so this can't be detected and excluded automatically. Treat a "
    "large number here as a prompt to check what the vote actually was."
)

st.divider()
st.header("2. Bill Scrutiny Explorer")

use_curated = st.toggle("Use curated shortlist (fast)", value=True)

if use_curated:
    bill_id = st.selectbox(
        "Choose a bill", options=list(CURATED_BILLS.keys()),
        format_func=lambda b: CURATED_BILLS[b],
    )
    all_bills = load_government_bills()
    bill = all_bills.get(bill_id)
else:
    st.caption(
        "Browsing all current-session Government Bills. Anything not in "
        "the curated shortlist above will take up to a minute to compute "
        "on first load."
    )
    all_bills = load_government_bills()
    sorted_bills = sorted(all_bills.values(), key=lambda b: b["last_update"], reverse=True)
    bill_id = st.selectbox(
        "Choose a bill", options=[b["bill_id"] for b in sorted_bills],
        format_func=lambda b: all_bills[b]["title"],
    )
    bill = all_bills.get(bill_id)

if bill:
    relative_friction, comparison_group = load_bill_relative_friction(
        bill["bill_id"], bill["bill_type_id"], bill["introduced_session_id"]
    )
    own = relative_friction["own_friction"]

    if own["total_amendments"] == 0:
        st.caption(
            "This bill hasn't reached committee stage yet, so there's no "
            "amendment activity to show. The zeros below are accurate, not missing "
            "data: a bill with no scrutiny activity yet genuinely scores "
            "as lowest risk on the scrutiny side."
        )

    col1, col2, col3 = st.columns(3)
    col1.metric(
        "Committee sitting days (Commons + Lords)",
        own["commons_committee_sitting_days"] + own["lords_committee_sitting_days"],
    )
    col2.metric("Amendments tabled", own["total_amendments"])
    col3.metric("Contested proportion", f"{own['contested_proportion']:.1%}")

    ratio_col1, ratio_col2 = st.columns(2)
    days_ratio = relative_friction["committee_sitting_days_ratio"]
    contest_ratio = relative_friction["contested_proportion_ratio"]
    ratio_col1.metric(
        "Committee time vs. comparison group",
        f"{days_ratio:.1f}x" if days_ratio is not None else "n/a",
        help=f"Compared against {relative_friction['comparison_group_size']} other "
             f"Government Bills from the same session.",
    )
    ratio_col2.metric(
        "Contested-amendment rate vs. comparison group",
        f"{contest_ratio:.1f}x" if contest_ratio is not None else "n/a",
    )

    stages_with_amendments = [
        s for s in own["stage_breakdown"] if s["total_amendments"] > 0
    ]
    if stages_with_amendments:
        stage_labels = [
            f"{s['stage_description']} ({s['house']})" for s in stages_with_amendments
        ]
        contested = [s["contested_amendments"] for s in stages_with_amendments]
        not_contested = [
            s["total_amendments"] - s["contested_amendments"]
            for s in stages_with_amendments
        ]
        timeline_fig = go.Figure()
        timeline_fig.add_trace(go.Bar(
            x=stage_labels, y=not_contested, name="Not contested (agreed on the nod, etc.)",
            marker_color="lightsteelblue",
        ))
        timeline_fig.add_trace(go.Bar(
            x=stage_labels, y=contested, name="Contested (division, withdrawn)",
            marker_color="indianred",
        ))
        timeline_fig.update_layout(
            title="Amendment activity across this bill's lifecycle (by stage, chronological)",
            barmode="stack", height=350,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(timeline_fig, width="stretch")

    bill_risk_score = compute_bill_risk_score(
        bill_id=bill["bill_id"],
        comparison_group=comparison_group,
        governing_party=governing_party,
        start_date=cohesion_table.iloc[0]["month"] + "-01",
        end_date=datetime.date.today().isoformat(),
        majority_size=governing_majority,
    )
    st.metric("Composite bill risk score (1 = lowest risk)", f"{bill_risk_score:.2f}")

    with st.expander("What is this comparing against?"):
        st.write(
            f"Comparison group: {relative_friction['comparison_group_size']} other "
            f"Government Bills introduced in the same Parliamentary session, "
            f"bill IDs {comparison_group}."
        )
        st.write(
            "A ratio above 1.0 means this bill is facing more friction than "
            "the average bill of its type this session; below 1.0 means less."
        )

st.divider()
parliament_risk_score = compute_parliament_risk_score(
    governing_party=governing_party,
    start_date=cohesion_table.iloc[0]["month"] + "-01",
    end_date=datetime.date.today().isoformat(),
    majority_size=governing_majority,
    live_bill_friction_ratios=(
        [relative_friction["contested_proportion_ratio"]]
        if bill and relative_friction.get("contested_proportion_ratio") is not None
        else []
    ),
)
st.header("3. Composite Parliament Risk Score")
st.metric(
    "Whole-Parliament Legislative Risk Score (1 = lowest risk)",
    f"{parliament_risk_score:.2f}",
    help="70% cohesion / 30% scrutiny, fixed Phase 1 weights, not yet "
         "validated against real outcomes. See CLAUDE.md.",
)
