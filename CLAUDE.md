# CLAUDE.md — UK Legislative Risk Index

This file gives Claude Code the context and conventions to build this project.
Read this fully before writing any code.

## What this project is

A composite risk index for UK legislative/government risk, built entirely from
the UK Parliament open data APIs (developer.parliament.uk). It combines two
sub-indices into one score:

1. **Cohesion sub-index** — government stability, derived from Commons division
   (voting) data. Measures how often MPs rebel against their own party whip,
   aggregated over rolling time windows. Rising rebellion rate = falling
   cohesion = rising political risk.

   Two refinements that matter and must not be skipped: (a) a raw rebellion
   rate is meaningless without the size of the governing majority — 5%
   rebelling is existential at a majority of 1 and irrelevant at a majority
   of 170, so cohesion must be scored relative to "how many rebels would it
   take to lose this specific vote," not as an absolute rate; (b) a rolling
   average hides the event that actually matters — one division with 100
   rebels and 50 divisions with 2 rebels each average out to look identical,
   so track the largest single-division rebellion in the window alongside
   the rolling mean, not instead of it.

2. **Scrutiny sub-index** — legislative friction, derived from Bills API data.
   Measures how much committee time and amendment activity a bill accumulates
   relative to bills of similar type/stage, as a proxy for how likely it is to
   be delayed, watered down, or fail. This gives a *continuously live* signal
   (there are always bills in progress), which is the main reason this project
   was chosen over a cohesion-only index — cohesion alone only produces
   interesting signal around rare events (confidence votes, major rebellions).

The two sub-indices combine into a single **Legislative Risk Score**, published
at both a whole-Parliament level (how stable/gridlocked is government right now)
and a bill level (how likely is this specific bill to pass on schedule).

This is the domestic-institutional counterpart to an existing sovereign
shadow-rating model (separate project) — same "multiple weak signals into one
composite" methodology, applied to UK Parliament instead of sovereign states.
Keep that parallel in mind for naming/structure consistency, but do not import
or reference that other project's code.

## Purpose (decided 2026-07-26)

This is a **CV portfolio piece**, not a dashboard-vs-trading-signal question
left open anymore — it's explicitly a dashboard: a Streamlit app (`app.py`)
demonstrating real-data engineering + a defensible risk-modelling
methodology to recruiters/interviewers. That decision shapes priorities:

- Presentation and demo reliability matter as much as the underlying logic.
  A recruiter clicking around should get a responsive dashboard, not wait
  minutes on a live API call — see the curated bill shortlist in `app.py`
  (pre-warmed, cached bills) vs. the "browse all bills" option (live,
  clearly labelled as slower).
- No predictive/market-correlation validation is in scope (that was the
  other branch of this decision, not taken) — validation stays at
  spot-checking real historical events, which is also good portfolio
  material (a recruiter can verify the numbers against public record).
- Deployment: intended to run locally via `streamlit run app.py`, with
  Streamlit Community Cloud as the natural free option for a live link on
  a CV, once there's a GitHub repo to deploy from (not yet initialized as
  git as of 2026-07-26).

## Explicit phasing — do not skip ahead

- **Phase 1 (this repo's actual scope right now): UK only.** Cohesion index +
  scrutiny index + composite. Get this fully working and demoable before
  touching anything else.
- **Phase 2 (later, not yet):** EU Parliament data as either a second composite
  or an extra sub-index (regulatory divergence). The EU Open Data Portal API
  (data.europarl.europa.eu, API v2, JSON-LD) is less mature than the UK one —
  expect more data-cleaning overhead. Do not start this until Phase 1 is solid.
- **Not in scope at all unless asked:** financial interests conflict-mapping.
  Mentioned in project notes as a possible future side-project, not part of
  the index.

## Data sources (Phase 1)

All under the Open Parliament Licence, no API key required for reads.

- **Members API** — `https://members-api.parliament.uk/` — MP identity, party,
  constituency, membership history (needed to know who's in which party at a
  given date, since party membership can change).
- **Commons Votes / Divisions** — reachable via developer.parliament.uk — raw
  division (vote) records: which MPs voted which way on which division.
- **Bills API** — `https://bills-api.parliament.uk/` — bill stages, dates,
  amendments, committee activity. Confirm explicitly whether stage data
  covers Lords stages as well as Commons — do not assume Commons-only. For a
  government with a comfortable Commons majority, real friction and defeats
  usually happen in the Lords, so a Commons-only view would systematically
  understate risk on exactly the bills where risk is real.
- Full endpoint catalogue: `config/api_endpoints.yaml` (fill in exact paths
  from the OpenAPI specs linked at developer.parliament.uk as you go — don't
  guess endpoint shapes, always check the live OpenAPI spec first).

## Code conventions

- The person building this is early into learning Python (started mid-2026).
  Favour clear, explicit, well-commented code over clever/compressed code.
  Plain functions over heavy class hierarchies unless there's a clear reason.
- Every data client function should have a docstring stating: what endpoint
  it hits, what it returns (shape), and any pagination/rate-limit behaviour.
- No hardcoded API responses or fixture data pretending to be real — if an
  endpoint hasn't been verified yet, mark it clearly with a TODO instead of
  guessing its shape.
- Cache raw API responses to `data/raw/` before transforming, so re-runs don't
  hammer the API and so raw data is always inspectable.
- Keep the two sub-indices in independent modules that don't import each
  other — they should be understandable and testable in isolation. Only
  `composite_index.py` combines them.

## Current state of this repo (updated 2026-07-26)

Phase 1 is fully built and verified against live data, plus the dashboard:

- All three data clients (`members_client`, `votes_client`, `bills_client`)
  implemented and confirmed against real live API responses.
- Both sub-indices (`cohesion_index`, `scrutiny_index`) implemented,
  including the majority-normalization, tail-event tracking, and
  Lords-coverage refinements below, and validated against real historical
  events (Safety of Rwanda Bill rebellion, Employment Rights Act friction).
- `composite_index.py` combines them with fixed Phase 1 weights.
- `src/reporting.py` holds logic shared between the visualisation script and
  the dashboard (month-bucketing, governing-party lookup, comparison-group
  selection) — don't duplicate this logic in a new entry point, import it.
- `notebooks/visualise_cohesion_score.py` — static PNG/CSV cohesion trend,
  the original build-order step 7.
- `app.py` — the Streamlit dashboard (the CV portfolio deliverable). Run
  with `streamlit run app.py`. Has a curated, pre-warmed bill shortlist
  (Employment Rights Act 2025, Immigration and Asylum Bill, Railways Bill)
  for a fast default demo, plus a "browse all current Government Bills"
  toggle for live (slower) lookups.
- Known bug fixed 2026-07-26: `compute_parliament_risk_score` and
  `compute_bill_risk_score` in `composite_index.py` originally only clamped
  their scrutiny-score component at the *lower* bound (0.0) — a
  below-average friction ratio (bill/parliament less contested than its
  comparison group) could push the blended score above 1.0, which is out
  of the documented `[0, 1]` range. Both are now clamped `max(0.0, min(1.0,
  ...))`. If you touch this formula again, keep both clamps.

## Suggested next steps

- Not yet a git repo — initialize one before deploying to Streamlit
  Community Cloud for a shareable CV link.
- No scrutiny-index visualisation yet in the dashboard beyond the single
  selected bill's own numbers — a trend view (e.g. average friction across
  all live Government Bills over time) would round this out.
- Composite weights (70/30 each direction) are still documented
  placeholders, not validated against real outcomes — revisit once you've
  watched the numbers move for a while.
- Comparison-group selection (`src/reporting.py:build_comparison_group`) is
  currently "same bill_type_id + same session, first N by whatever order
  the API returns" — deliberately simple, not sorted by any similarity
  measure. Revisit if the ratios it produces start looking arbitrary.
