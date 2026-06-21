# Parkhu Data Collector

The **data-collection layer** of the Parkhu AI institutional research operating
system. It runs every morning before the Indian market opens, gathers raw
market intelligence from free sources, normalizes it into CSV/JSON, and commits
one folder per day that the **Parkhu Research Engine (ChatGPT)** then reads.

> This repo is *only* the collection layer. Scoring, recommendations, the trade
> database and the learning engine are separate layers per the Parkhu Constitution.

```
GitHub Actions (02:30 PM IST — testing)
        │
        ▼
  Parkhu Data Collector  ──►  Normalized DB (CSV/JSON)  ──►  Research Engine
   (agents below)               output/<date>/                  (ChatGPT)
```

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
| Indices / Sectors | `collector/market/` | broad-market & sectoral index levels (incl. India VIX) | Yahoo Finance |
| Macro | `collector/macro/` | USDINR, gold, silver, crude, US markets, 10Y yield, DXY | Yahoo Finance |

**Derived signals** (computed after collection, in `collector/derived/`):

| File | Purpose |
|------|---------|
| `relative_strength.csv` | Stock vs NIFTY / sector performance |
| `event_risk.csv` | Earnings, corp actions, news within 21 days |
| `fno_momentum.csv` | OI buildup + F&O activity scores |
| `swing_candidates.csv` | Top 20 for 2–3 week / ~5% swing template |
| **`stock_analysis.csv`** | **Primary file** — one row/stock: all indicators, sub-scores, pivots/support/resistance, ATR trade levels |
| **`market_summary.csv`** | One-row regime: index trend, VIX, sector leaders, FII/DII, macro, overall risk |

The **Indicator Engine** (`stock_analysis.csv` + `market_summary.csv`) precomputes
every *deterministic* metric so the research engine only does what needs
judgement — cross-validating signals, conviction, sizing, thesis. Columns with
no source yet (`supertrend`, `ichimoku`, `obv`, `cmf`, ownership, news sentiment,
earnings surprises) are present but blank for schema stability.

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
    report.json
    manifest.json     ← data dictionary: what each file is + its use case
```

`watchlist.csv` is a simple trend/momentum ranking from `tradingview.csv`
(above SMA200, TV tech rating, RSI, ADX) — a starting cut for the research
engine, **not** a recommendation.

`swing_candidates.csv` is a separate 2–3 week swing shortlist (~5% target)
using relative strength, delivery %, F&O confirmation and event-risk filters.

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

`.github/workflows/collect.yml` runs **Sun + Mon–Fri** at **09:00 UTC = 14:30 IST (2:30 PM)** *(testing schedule)*,
installs deps, runs `run.py`, and commits the day's `output/` back to the repo.
You can also trigger it manually from the **Actions** tab (`workflow_dispatch`).

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

## Configuration

- `config/universe.py` — trading universe (default: Nifty 50) and ticker maps.
  Extend with Next 50 / Midcap / Smallcap by appending to `scanning_universe()`.
- `config/settings.py` — paths, IST date logic, history lookback, network tuning.

## Roadmap (free enhancements)

- Shareholding filings → promoter holding, pledge (ownership agent in `collector/ownership/`)
- Insider deals (SAST/PIT), bulk-deal history
- RBI / MOSPI scrapers for repo rate, CPI, GDP (currently placeholders in `macro.csv`)
- Concall / guidance extraction via the News agent + LLM
