# Parkhu Data Collector

The **data-collection layer** of the Parkhu AI institutional research operating
system. It runs every morning before the Indian market opens, gathers raw
market intelligence from free sources, normalizes it into CSV/JSON, and commits
one folder per day that the **Parkhu Research Engine (ChatGPT)** then reads.

It then applies the Parkhu risk and portfolio limits to that data and commits a
**decision-ready swing brief** — entry, stop, targets, hold period, expected
profit % and rupee position size for each idea.

> The trade database and the learning engine are still separate layers per the
> Parkhu Constitution. See [`docs/data-gaps.md`](docs/data-gaps.md) for what the
> knowledge base asks for that this repo does not yet produce.

```
GitHub Actions (daily, pre-open)
        │
        ▼
  Parkhu Data Collector  ──►  Normalized DB (CSV/JSON)  ──►  Swing Brief
   (agents below)               output/<date>/               swing_brief.md
                                                             latest_brief.md
```

**Read this each morning:**

- **Claude / LLM:** [`output/latest/research_pack.md`](output/latest/research_pack.md) — see [`docs/claude-handoff.md`](docs/claude-handoff.md) (no zip upload).
- **Human brief:** [`output/latest_brief.md`](output/latest_brief.md) — see [`docs/swing-brief.md`](docs/swing-brief.md).
- **Dashboard:** GitHub Pages (`site/`) via workflow **Deploy Parkhu Pages** — edit UI and redeploy without running collect.

## Agents

| Agent | Module | Collects | Source |
|-------|--------|----------|--------|
| TradingView | `collector/tradingview/` | one-call universe snapshot: price, valuation, quality, technicals, Buy/Sell ratings | TradingView screener |
| Earnings | `collector/tradingview/` | TTM revenue/profit/EBITDA/EPS, YoY & QoQ growth, last/next earnings date | TradingView screener (same scan) |
| Smart Money | `collector/smartmoney/` | FII/DII flows, block deals | NSE |
| Options | `collector/options/` | OI, PCR, max pain, ATM IV (NIFTY/BANKNIFTY) | NSE |
| Derivatives | `collector/derivatives/` | OI spurts, most-active contracts & underlyings | NSE |
| Delivery | `collector/delivery/` | delivery %, volume, turnover per symbol | NSE bhavcopy |
| Corp Actions | `collector/corpactions/` | dividends, splits, bonus, buyback, ex-dates | NSE filings |
| News | `collector/news/` | corporate announcements, board meetings | NSE |
| News classify | `collector/derived/news_classify.py` | keyword catalyst/sentiment → `news_enriched.csv` | NSE announcement text |
| Indices / Sectors | `collector/market/` | broad-market & sectoral index levels (incl. India VIX) | Yahoo Finance |
| Macro / Global | `collector/macro/` | USDINR, gold/silver, crude, copper, DXY, Bitcoin; US (S&P/Nasdaq/Dow/VIX/yields); Asia (Nikkei/HangSeng/Shanghai/Kospi/Taiwan/ASX); Europe (FTSE/DAX/Stoxx); EM & India ETFs | Yahoo Finance |

**Derived signals** (computed after collection, in `collector/derived/`):

| File | Purpose |
|------|---------|
| `relative_strength.csv` | Stock vs NIFTY / sector performance |
| `event_risk.csv` | Earnings, corp actions, news within 21 days |
| `news_enriched.csv` | Per-announcement sentiment / catalyst flags (keyword rules) |
| `fno_momentum.csv` | OI buildup + F&O activity scores |
| `swing_candidates.csv` | Top 20 for 2–3 week / ~5% swing template |
| **`stock_analysis.csv`** | **Primary file** — one row/stock: all indicators, sub-scores, pivots/support/resistance, ATR trade levels |
| **`market_summary.csv`** | One-row regime: index trend, VIX, sector leaders, FII/DII, macro, overall risk |

**Brief layer** (`collector/brief/`), runs last:

| File | Purpose |
|------|---------|
| **`swing_brief.md`** | **The brief** — open-position review first, then gated, sized new ideas with entry / stop / T1–T3, R:R, hold period, expected profit % and rupee position size, plus portfolio math, watchlist and gate funnel |
| `swing_brief.json` | Same content structured, including the survivor count after every gate — the audit trail for why a name was or was not recommended |
| `trades/open.csv` | Live suggestions, re-checked every run until the hold period ends (MFE/MAE, days held, action) |
| `trades/closed.csv` | Finished suggestions with return, R multiple and days held — the measured hit rate |

Every idea is tracked to its conclusion. Each run reviews open suggestions against
KB-17 SOP-3 (invalidation → stop → target → time stop → earnings → hold) *before*
proposing anything new. See [`docs/swing-brief.md`](docs/swing-brief.md#the-suggestion-ledger).

The **Indicator Engine** (`stock_analysis.csv` + `market_summary.csv`) precomputes
every *deterministic* metric so the research engine only does what needs
judgement — cross-validating signals, conviction, sizing, thesis. Columns with
no source yet (`supertrend`, `ichimoku`, `obv`, `cmf`, ownership,
earnings surprises) are present but blank for schema stability. News sentiment /
catalyst columns are filled from `news_enriched.csv` when available.

`stock_analysis.csv` also carries a **cross-sectional factor model** (Barra/AQR-style):
`value_z`, `momentum_z`, `quality_z`, `lowvol_z`, `growth_z`, `size_z` are winsorized
z-scores ranking each stock against the universe (mean 0, higher = better), blended
into `composite_factor_z` with a `composite_factor_rank` percentile. These complement
the absolute 0–100 sub-scores: the z-scores say *how a stock ranks vs peers*, the
sub-scores say *whether it clears fixed thresholds*.

> **Design note:** the broad price / valuation / technical / **earnings** layer
> for the whole universe now comes from the **TradingView** snapshot in a single
> call (`earnings.csv` is sliced from the same scan — no extra request). The old
> per-symbol Yahoo agents (`market`, `fundamentals`, `technical`, `earnings`) were
> retired as redundant — their modules remain in `collector/` but are no longer in
> the run. The remaining agents cover what TradingView does not expose (NSE-only
> data: FII/DII, options/OI, corp actions) plus index/sector levels, macro and
> news.

## Daily output

```
output/2026-06-21/
    tradingview.csv   ← ~366-name screener snapshot (price/valuation/technicals/ratings)
    indices.csv       sectors.csv       earnings.csv
    fii.csv           block_deals.csv   options.csv
    oi_spurts.csv     most_active_contracts.csv  most_active_underlying.csv
    corporate_actions.csv
    news.csv          macro.csv         delivery.csv
    relative_strength.csv  event_risk.csv  fno_momentum.csv
    swing_candidates.csv   watchlist.csv
    stock_analysis.csv   ← PRIMARY: one row/stock, all indicators + scores + trade levels
    market_summary.csv   ← one-row market regime
    swing_brief.md       ← THE BRIEF: sized, gated ideas with levels
    swing_brief.json     ← same, structured + audit trail
    research_pack.md/.json ← Claude-sized handoff (regime + ideas + ledger)
    report.json
    manifest.json     ← data dictionary: what each file is + its use case

output/latest/           ← full uncompressed mirror of newest dated folder
output/index.json        ← { latest, pack_url, files… }
output/latest_brief.md   ← stable path to the newest brief
```

`watchlist.csv` is a simple trend/momentum ranking from `tradingview.csv`
(above SMA200, TV tech rating, RSI, ADX) — a starting cut for the research
engine, **not** a recommendation.

`swing_candidates.csv` is a separate 2–3 week swing shortlist (~5% target)
using relative strength, delivery %, F&O confirmation and event-risk filters.

`swing_brief.md` **is** a recommendation, and the only file here that is. It
applies the KB-08/KB-09 hard caps (2% risk per trade, 10% per stock, 25% per
sector, 10 positions) and the KB-14 score bands (Buy ≥80, Watch 70–79) to
`stock_analysis.csv`, then sizes each idea against `PARKHU_CAPITAL`. If nothing
clears the gates it says so and prints the funnel — zero ideas is a valid
outcome under KB-00, not a failed run.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# quick smoke test on 5 symbols
PARKHU_MAX_SYMBOLS=5 python run.py

# full Nifty 50 run
python run.py
```

Environment overrides:

| Var | Effect |
|-----|--------|
| `PARKHU_MAX_SYMBOLS` | cap the universe (e.g. `5` for testing) |
| `PARKHU_RUN_DATE` | force the output date (e.g. `2026-06-20` for backfill) |
| `PARKHU_UNIVERSE` | `nifty50` (default) or `tradingview` — drive the whole pipeline off the TradingView screener (~366 NSE names, mcap ≥ ₹20,000 cr) instead of the static Nifty 50 |

> The **TradingView agent always** writes the full ~366-name `tradingview.csv` in one
> call regardless of `PARKHU_UNIVERSE`. The env var only controls whether the
> *other* (per-symbol) agents iterate the 366 screener names or the Nifty 50.

## Scheduling

`.github/workflows/collect.yml` installs deps, runs `run.py`, and commits the
day's `output/` — including the brief — back to the repo. You can also trigger it
manually from the **Actions** tab (`workflow_dispatch`).

Cron is **UTC**, so subtract 5h30m from the IST time you want:

| Wanted (IST) | Cron |
|---|---|
| 05:00 | `30 23 * * *` |
| 06:00 | `30 0 * * *` |
| 08:00 | `30 2 * * *` |

> **GitHub does not dispatch scheduled runs on time.** Recent runs configured for
> 06:00 IST actually produced data at 09:16 and 09:22 IST — over three hours late.
> Free-tier `schedule` events are best-effort and queue behind paid load. Set the
> cron earlier than you need, and read `generated_at_ist` in `report.json` rather
> than assuming the brief is as fresh as the cron implies.

## Resilience contract

Every agent follows one rule: **never crash the pipeline.** On failure it logs
to `logs/<date>.log`, writes an empty CSV with the correct schema, and reports
its status in `report.json` (`ok` / `partial` / `error`). NSE endpoints
(smart money, options, derivatives, corp actions, news)
are best-effort — NSE rate-limits
bots, so these degrade gracefully rather than failing the run. The collector
uses **curl_cffi** (browser TLS impersonation) plus a multi-page cookie warm-up
to get past NSE's Akamai bot manager; if `curl_cffi` is missing it falls back
to plain `requests` (NSE will then usually 403).

## Architecture

Orchestration lives in [`pipeline/`](pipeline/) (`registry` + `runner`). Coding
standards and layer rules: [`docs/architecture.md`](docs/architecture.md).
Retired Yahoo agents: [`collector/_retired/`](collector/_retired/).

```bash
pytest -q                       # unit tests (also run in CI before collect)
python run.py                   # thin CLI → pipeline.runner
pip install -r requirements-dev.txt
python -m scripts.quality       # ruff + vulture + jscpd (duplication)
```

## Configuration

- `config/universe.py` — trading universe (default: Nifty 50) and ticker maps.
  Extend with Next 50 / Midcap / Smallcap by appending to `scanning_universe()`.
- `config/settings.py` — paths, IST date logic, history lookback, network tuning.
- `config/risk.py` — capital and every risk/portfolio/scoring threshold the brief
  enforces, each citing its KB source. All env-overridable:

  ```bash
  PARKHU_CAPITAL=200000 python run.py     # total capital, not per trade
  PARKHU_TOP_N_IDEAS=3 python run.py
  ```

## Documentation

- [`docs/technical-plan.md`](docs/technical-plan.md) — **the design rationale**: what
  every gate, threshold and formula is, why that value was chosen, the measurement
  behind it, and what would have to change to improve it. Read this before changing
  a rule. Includes the invariants worth keeping as tests and the extension points.
- [`docs/swing-brief.md`](docs/swing-brief.md) — the operator's guide: how the brief
  is built, the suggestion ledger, and where it deliberately overrides
  `stock_analysis.csv`.
- [`docs/data-gaps.md`](docs/data-gaps.md) — what the knowledge base needs that
  this repo does not yet collect, prioritised, with proposed CSV schemas.

## Roadmap (free enhancements)

Ordered by leverage — see [`docs/data-gaps.md`](docs/data-gaps.md) for the detail.

1. **Daily OHLC history** → real support/resistance, breakouts, bases, patterns.
   Unblocks genuine trade levels; today's `risk_reward` is a constant 0.67.
2. **Trade outcome log** (`trades/open.csv`, `trades/closed.csv`) → the first
   measured win rate, which is what turns "expected profit %" from a target into
   an expectation. KB-12 / KB-13.
3. **Shareholding filings** → promoter holding and pledge (`collector/ownership/`).
   KB-04's governance veto currently has no input at all.
4. **News sentiment / catalyst classification** → 15 of KB-14's score points,
   from text already collected in `news.csv`.
5. Per-stock options (PCR, max pain, IV), per-stock FII/DII/MF holdings.
6. Insider deals (SAST/PIT), bulk-deal history.
7. RBI / MOSPI scrapers for repo rate, CPI, GDP (placeholders in `macro.csv`).
8. Concall / guidance extraction via the News agent + LLM.
