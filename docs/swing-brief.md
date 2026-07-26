# The swing brief

`collector/brief/swing_brief.py` turns the day's derived CSVs into a decision-ready
brief. It runs as the last step of `run.py`, so one `python run.py` produces both the
raw data and the brief.

## Output

```
output/<date>/swing_brief.md      the brief
output/<date>/swing_brief.json    same content, structured + audit trail
output/latest_brief.md            stable path to the newest brief
```

Both files are catalogued in `manifest.json` and committed by the existing
`git add output/` step in `.github/workflows/collect.yml`, so no workflow change is
needed. `swing_brief` also appears in `report.json` under `agents` with its status and
the symbols it selected.

Stable URL to bookmark:

```
https://github.com/buhahemal/parkhu-ai/blob/main/output/latest_brief.md
```

## The suggestion ledger

Every idea is tracked until its hold period ends. `collector/brief/positions.py`
appends each brief's ideas to `trades/open.csv`, and every subsequent run re-checks
each open row against the current price before proposing anything new — managing what
is already on matters more than adding to it.

```
trades/open.csv      live suggestions, with MFE/MAE updated each run
trades/closed.csv    finished suggestions, with return, R multiple and days held
```

Review order is KB-17 SOP-3 exactly:

| # | Check | Action |
|---|---|---|
| 1 | Two or more entry conditions gone | **EXIT — THESIS INVALIDATED** |
| 2 | Price at or below stop | **EXIT — STOP HIT** |
| 3 | Price at/above T3 · T2 · T1 | Full exit · bank more and trail · **bank partial, trail, stop to breakeven** |
| 4 | Held past the T2 horizon and still flat | **EXIT — TIME STOP** (scratch) |
| 5 | One condition gone | **TIGHTEN / REVIEW** |
| 6 | Results now inside 21 days | **EARNINGS AHEAD** — reduce or stand aside (KB-05) |
| 7 | None of the above | **HOLD**, update MFE/MAE |

A name that drops out of the screener universe becomes **NO DATA** with its last known
price carried forward, rather than silently vanishing.

A symbol suggested again while already open is **re-confirmed, not re-opened**
(`reconfirmed_count` increments) — KB-09 Ch.3 allows scaling in on confirmation but
never duplicating a position blindly.

### It is a suggestion ledger, not a broker statement

Rows record what the system recommended, not what you traded. Set the `taken` column
to `y` or `n` yourself if you want the stats to reflect only real fills; the pipeline
never overwrites it after the row is created.

### Measured performance

`trades/closed.csv` is what eventually replaces the projected "expected profit %" with
a real hit rate. Until roughly 20 rows exist the brief prints the numbers *and* says
they are too few to infer anything — a log, not a statistic.

Two limitations while the OHLC gap is open: MFE/MAE are sampled from the daily `cmp`
rather than true intraday extremes, and a stop is only detected if the close breached
it, so a gap through the stop shows the close rather than the fill. The time stop
counts weekdays and does not know NSE holidays, which makes it marginally lenient
rather than premature.

The ledger assumes runs happen in chronological order. Re-running an old date after
newer ones have been processed will interleave the review incorrectly.

**`trades/` must be committed.** The `git add output/ logs/ trades/ database/ohlc/`
step in `collect.yml` carries the ledger and the raw OHLC store between CI runs; drop
`trades/` and open positions / hit rate reset every morning.

## Rules enforced

Every threshold lives in `config/risk.py`, cites its KB source, and is env-overridable.

| Rule | Value | Source |
|---|---|---|
| Risk per trade | 2% of capital | KB-08 Ch.2 |
| Max per stock | 10% of capital | KB-09 Fig 1-1 |
| Max per sector | 25% of capital | KB-09 Fig 1-1 |
| Max positions | 10 | KB-09 Fig 1-1 |
| Min reward:risk to T1 | 1:2 | KB-08 Ch.4 |
| Buy / Watch / Ignore | ≥80 / 70–79 / <70 | KB-14 Fig 3-1 |
| Holding period | 3–22 trading days (~1 month max) | Parkhu swing mandate |
| Stop distance | > 1 ATR | KB-03 Ch.5 |
| ADX for a tradeable trend | > 25 | KB-03 Fig 3-1 |
| RSI band in an uptrend | 40–80 | KB-03 Ch.3 |
| Earnings inside 21 days | stand aside | KB-05 Fig 4-1 |

Position size is `min(2%-risk sizing, 10%-exposure sizing)` — KB-08 Ch.2's
binding-constraint rule. The brief names which cap bound each position.

Zero ideas is a valid outcome. KB-00 requires stating that no recommendation should be
made rather than lowering the bar, so the brief prints the gate funnel instead and
`swing_brief` still reports `status: ok`.

## Configuration

```bash
PARKHU_CAPITAL=200000 python run.py          # total capital, not per trade
PARKHU_TOP_N_IDEAS=3 python run.py
PARKHU_MIN_DELIVERY_PCT=50 python run.py
PARKHU_RUN_DATE=2026-07-21 python run.py     # backfill a past date
```

Or regenerate a brief for one date without re-collecting:

```bash
python -c "from collector.brief import swing_brief; print(swing_brief.collect('2026-07-21'))"
```

## Two deliberate departures from `stock_analysis.csv`

Both are workarounds for gaps in `docs/data-gaps.md`, not permanent design.

**Trade levels are rebuilt.** `stock_analysis.csv` uses a fixed ladder — entry ±0.5 ATR,
stop −1.5 ATR, targets +1/+2/+3 ATR. That makes `risk_reward` exactly **0.67 on all 368
rows**, and KB-08 Ch.4 rejects anything below 1:1, so a literal reading vetoes the entire
universe every day. The brief derives the stop from the nearest moving-average structure
below price with a 0.5 ATR buffer, then sets T1/T2/T3 at 2R/3R/4R.

**Stops do not use `support1`/`resistance1`.** Those are single-day classic pivots roughly
0.3% wide — on 2026-07-24, ICICIBANK closed at ₹1,428.90 with support1 at ₹1,424.46 and
resistance1 at ₹1,432.66. Over a 3-to-22 trading-day (~1 month) hold that is noise.

When structure sits further below price than the risk ceiling allows, the brief falls back
to a 2 ATR volatility stop (KB-08 Fig 3-1 permits an ATR stop "when structure is unclear")
and says so in the idea's invalidation line, because the true invalidation level is then
*below* the stop — the stop can trigger while the thesis is intact.

## What the numbers do and do not mean

- **Expected profit %** is the move to T1, not a probability-weighted expectation. There
  is no trade outcome history yet, so no win rate exists to weight it with.
- **R:R is 2.0 by construction.** T1 is placed at 2R to clear the KB floor. Without OHLC
  history there are no real resistance levels to target, so R:R currently does no
  independent filtering. Once `docs/data-gaps.md` item 1 lands, targets move to genuine
  structure and R:R becomes a real filter again.
- **Hold period** is an ATR √time estimate: days ≈ (target distance ÷ ATR)². It answers
  "is this target reachable inside the mandate", not "when will it hit". Names whose T1
  needs more than **22 trading days (~1 month)** are hard-rejected (`skipped_beyond_horizon`).
- **Scores are provisional.** News (15), institutional (10) and options (5) have no data,
  so 30 of KB-14's 100 points cannot be computed. The remaining weights are renormalised
  and the shortfall is printed in the caveats.
- **No governance check ran.** `promoter_pledge` is empty universe-wide, so KB-04's hard
  veto has no input.

## Sector concentration

KB-09's 25% sector cap runs on a `risk_sector` derived from the TradingView `industry`
column, not the raw `sector`. TradingView files banks, NBFCs, insurers, brokers, REITs and
real-estate developers all under `Finance` — on 2026-07-25 that made LODHA (a developer),
ICICIBANK and IIFL one sector, and queued IIFL out of the brief for no real reason. The
mapping in `INDUSTRY_TO_RISK_SECTOR` splits `Finance` into Banks, NBFC & Capital Markets,
Insurance and Real Estate. Everything else keeps its TradingView sector.

## Adding a new gate

Gates are declared in one block in `build_payload`, each as a name and a mask, and the
survivor count after every gate is recorded in `funnel` and printed when there are no
ideas. Add one line and the funnel documents itself:

```python
gate("turnover >= 50 cr", lambda x: x["turnover_20d_avg_cr"] >= 50)
```

Keep gate order cheapest-first so the funnel stays readable as a narrowing story.
