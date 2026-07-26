# UK Legislative Risk Index

A composite political-risk index built entirely from UK Parliament open data
([developer.parliament.uk](https://developer.parliament.uk/)). No scraping,
no manual data entry, every number traces back to a live API call.

**[Live demo](https://uk-legislative-risk-index-tcdkpz6o3rdvognosbhw4x.streamlit.app)**,
built by [Alfie Pearson-Rogers](https://github.com/alfierogers1023).

![Dashboard screenshot](screenshots/dashboard.png)

## Why I built this

I wanted to practice the same "combine multiple weak signals into one
composite" methodology used in quantitative risk modelling, applied
somewhere with genuinely free, well-documented, live data: UK Parliament's
open API. Cohesion (backbench rebellion) and scrutiny (bill friction) are
structurally different signals, one is only interesting around rare events,
the other is always live, and deciding to combine both rather than picking
just one was itself a deliberate design choice, not the first idea I had.

It was also a chance to practice things a toy dataset doesn't force on you:
verifying every endpoint against the live API before writing code against an
assumed shape, handling a real data quirk that silently broke a seat count
for the whole build (see Key Findings below), and thinking about deployment
constraints (Streamlit Community Cloud's ephemeral filesystem resets on
every redeploy) instead of stopping at "it works on my machine."

## Key findings

Things this project actually turned up, not just a working demo:

- **Found and fixed a real bug in the underlying data model.** The Members
  API records some Labour MPs as "Labour (Co-op)", a distinction neither the
  Commons Votes API nor the party-history endpoint makes. Left unhandled,
  this undercounted the governing party's seats by 43 and reported the
  working majority as 71 when the real figure is 157. This had been live
  since the first version of the dashboard until I caught it.
- **Validated against a well-documented real event.** The tail-event tracker
  correctly surfaces the 59-MP Conservative rebellion on the Safety of
  Rwanda Bill (17 January 2024), a real, publicly documented rebellion, not
  a synthetic test case.
- **Found a genuine methodological edge case.** With a wider history window,
  the "biggest rebellion" becomes 160 Labour MPs on the Terminally Ill
  Adults (End of Life) Bill, the real assisted dying vote. That was a free
  vote with no official party position, so calling it a "rebellion" is
  technically wrong. Whip status isn't published data, so this can't be
  detected automatically, only flagged, which the dashboard now does.

## What it measures

Two independent signals, combined into one score:

- **Cohesion**: is the governing party holding together? Measured from
  Commons division (vote) data, how often MPs rebel against their own
  party's majority position, normalized by the size of the governing
  majority (5% rebelling matters enormously at a majority of 1, and barely
  at all at a majority of 170). Also tracks the single worst rebellion in
  a window separately from the rolling average, since an average can hide
  the one event that actually matters.
- **Scrutiny**: how much legislative friction (committee time, contested
  amendments) is a given bill facing relative to similar bills, as a proxy
  for delay/rewrite risk.

Combined into a **Legislative Risk Score**, at both a whole-Parliament level
and a per-bill level.

Validated against real historical events, not just spot-checked on
synthetic data. For example, the dashboard's tail-event tracker correctly
surfaces the well-documented 59-MP Conservative rebellion on the Safety of
Rwanda Bill (17 January 2024) and shows the Employment Rights Act 2025 (a
known heavily-contested bill) at 22x the committee time of a comparison
group.

## Try it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Opens a dashboard with:
1. **Government Cohesion**: monthly trend chart, working majority, and the
   worst single rebellion in the selected window.
2. **Bill Scrutiny Explorer**: pick a bill (a curated, fast-loading
   shortlist by default, or browse any current Government Bill) and see its
   committee time / contested-amendment rate versus a comparison group of
   similar bills.
3. **Composite Parliament Risk Score.**

## Data sources

UK Parliament Developer Hub, https://developer.parliament.uk/ (Members
API, Bills API, Commons Votes API). Open Parliament Licence, no API key
needed.

## Structure

```
app.py                Streamlit dashboard (the main deliverable)
config/               API endpoint config
src/data_clients/     Thin wrappers around each Parliament API
src/indices/          Cohesion, scrutiny, and composite index logic
src/reporting.py       Shared reporting helpers (used by app.py and the notebook script)
src/utils/            Shared helpers (caching, retrying transient API errors)
scripts/refresh_cache.py  Regenerates data/raw/ (see below)
data/raw/              Committed pre-baked cache, deliberate, not an accident (see
                       scripts/refresh_cache.py and .github/workflows/refresh-cache.yml).
                       Streamlit Community Cloud's filesystem is ephemeral, so this
                       cache is what makes cold starts fast instead of a multi-minute
                       live refetch.
data/processed/        Generated chart/CSV output (gitignored, regenerated on run)
notebooks/             Static PNG/CSV visualisation script
tests/                 Tests for data clients and index logic (run against the live API)
```

See `CLAUDE.md` for the full build rationale, methodology decisions, and
known limitations.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python -m pytest tests/    # optional: runs against the live API
streamlit run app.py
```

## License

MIT, see [LICENSE](LICENSE).
