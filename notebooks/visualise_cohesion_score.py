"""
Visualise the cohesion sub-index over time for the current governing party.

This is the "simple script to visualise the score over time" from CLAUDE.md's
build order (step 7) — a plain script rather than a Jupyter notebook, so it's
easy to read top-to-bottom and run directly:

    python3 notebooks/visualise_cohesion_score.py

The month-bucketing and scoring logic lives in src/reporting.py, shared with
the Streamlit dashboard (app.py) — this script is just the "save a static
PNG/CSV" entry point for it.

Saves a PNG to data/processed/cohesion_score_timeseries.png and the
underlying monthly numbers to data/processed/cohesion_score_timeseries.csv.

This script hits the live Commons Votes API for however many months of
history you ask for — the first run over a new window can take a while
(one HTTP call per division), but results are cached in data/raw/, so
re-running the same window afterwards is fast.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Needed because this script lives in notebooks/, not the project root, so
# Python's default import path doesn't include the root where src/ lives.
sys.path.insert(0, PROJECT_ROOT)

import matplotlib.pyplot as plt

from src.reporting import build_monthly_cohesion_table, get_governing_party_and_majority

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "data", "processed")

MONTHS_OF_HISTORY = 12


def plot_monthly_table(df, party, majority_size):
    """Save a two-panel chart of the monthly table to OUTPUT_DIR."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    fig, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)

    # cohesion_score and rebellion_rate live on very different scales —
    # cohesion_score stays near 1.0 while rebellion_rate is a small
    # fraction, so sharing one 0-1 axis would flatten rebellion_rate into
    # an invisible near-zero line. Give it its own axis instead.
    line_cohesion, = ax_top.plot(df["month"], df["cohesion_score"], marker="o",
                                  color="tab:blue", label="Cohesion score (1 = fully cohesive)")
    ax_top.set_ylim(0, 1.02)
    ax_top.set_ylabel("Cohesion score", color="tab:blue")
    ax_top.set_title(f"{party} cohesion — working majority {majority_size}")
    ax_top.grid(alpha=0.3)

    ax_rate = ax_top.twinx()
    line_rebellion, = ax_rate.plot(df["month"], df["rebellion_rate"], marker="o",
                                    color="tab:orange", label="Rebellion rate (raw, right axis)")
    ax_rate.set_ylabel("Rebellion rate", color="tab:orange")
    ax_rate.set_ylim(bottom=0)

    ax_top.legend(handles=[line_cohesion, line_rebellion], loc="lower left")

    ax_bottom.bar(df["month"], df["worst_division_rebel_count"], color="tab:red")
    ax_bottom.set_title("Worst single-division rebel count per month "
                         "(the tail event a rolling average would hide)")
    ax_bottom.grid(alpha=0.3)
    plt.xticks(rotation=45)

    fig.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, "cohesion_score_timeseries.png")
    fig.savefig(output_path, dpi=150)
    print(f"Saved chart to {output_path}")


if __name__ == "__main__":
    party, majority_size = get_governing_party_and_majority()
    print(f"Governing party: {party}, working majority: {majority_size}")

    table = build_monthly_cohesion_table(party, majority_size, MONTHS_OF_HISTORY)
    for _, row in table.iterrows():
        print(f"{row['month']}: rebellion_rate={row['rebellion_rate']:.4f} "
              f"cohesion_score={row['cohesion_score']:.4f} "
              f"worst_division_rebels={row['worst_division_rebel_count']}")

    csv_path = os.path.join(OUTPUT_DIR, "cohesion_score_timeseries.csv")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    table.to_csv(csv_path, index=False)
    print(f"Saved monthly data to {csv_path}")

    plot_monthly_table(table, party, majority_size)
