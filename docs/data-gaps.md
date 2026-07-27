# Parkhu Data Collector — data gaps blocking the KB

> **Status — Phases 0–2 + Phase A accuracy foundations (see notes below).**
>
> | Gap | Status |
> |---|---|
> | #1 daily OHLC | **Partial.** `history/ohlc.csv` + `ohlc_features` + structure levels + OHLC MFE/MAE. Patterns still open. |
> | #2 trade levels 0.67 | **Mitigated.** Structure-based `risk_reward` / brief levels replace the fixed ATR ladder. |
> | #3 pivots unusable | **Mitigated.** Intraday pivots kept for back-compat; swing structure from OHLC + TV highs. |
> | #4 `relative_volume` broken | **Appears resolved** + funnel gate `MIN_RELATIVE_VOLUME=1.0` (sweep still open). |
> | #8 stock options | **Partial.** Env-gated `stock_options.csv` joins PCR/max pain/ATM IV; score weight deferred. |
> | #9 blank `ema20` | **Diagnosed, not fixed.** TradingView's India scan exposes SMA20/SMA100 but no EMA20/EMA100 in the tested field list. `sma20`/`sma100` are now emitted; `ema20`/`ema100` stay null pending `scripts/probe_tv_fields.py`. |
> | #12 sector labels | **Fixed for relative strength.** Mapping now resolves on `industry` before `sector`, adds NIFTY_REALTY/NIFTY_BANK/NIFTY_INFRA, and returns None rather than guessing. LODHA's `rs_vs_sector_1m` corrects from 23.73 to 12.84. The 25% *cap* was already correct — `swing_brief.INDUSTRY_TO_RISK_SECTOR` handles it, so this entry overstated the problem. |
> | #10 US/Asia macro nulls | **Fixed.** yfinance appends a NaN-close row for the in-progress session; `dropna` before `iloc[-1]`. |
> | indices chaining | **Fixed.** De-duplicates by calendar date, records `session_date`/`prev_session_date`, flags `is_stale`. |
> | weekend folders | **Flagged, not stopped.** `report.json` now carries `collection_date`, `session_date` and `is_trading_day`. The cron still writes a weekend folder; suppressing it is a workflow change. |
>
> Also fixed: `institution_score` appeared twice in `stock_analysis.COLUMNS` and
> silently collapsed to one column. `sector_score` now ranks within the resolved
> NIFTY sector instead of TradingView's 94-name "Finance" bucket.
>
> Net effect on `stock_analysis.csv`: **113 columns / 84 populated → 137 / 109.**
> The 28 that remain empty are the ones genuinely blocked on #1, #5, #6, #7, #8.

Findings from running the Parkhu KB gates against `output/2026-07-21` … `output/2026-07-25`
(368-name universe). Ordered by how much each gap costs you, not by effort.

Headline numbers (pre–Phase A; re-check after the next full collect):

- **30 of KB-14's 100 score points cannot be computed at all** (news 15, institutional 10, options 5) —
  options *columns* can now populate via `PARKHU_STOCK_OPTIONS=1`, but the 5-pt weight is still off.
- **`risk_reward` was 0.67 on all rows** under the old ATR ladder — Phase A replaces that with
  structure-based levels; verify variance on the next run.

---

## P0 — the KB cannot run correctly without these

### 1. Daily OHLC history (the single biggest gap) — **Partial (Phase A)**

**Landed:** Full OHLCV lives stock-wise in **`database/ohlc/<SYMBOL>.csv` on GitHub**
(committed by the daily collect job). Warm symbols fetch the last ~5 calendar days
and append/upsert by date; new/missing/short symbols get `period=max` into that CSV.
Dated `output/<date>/history/ohlc.csv` is only a tiny session-slice pack (not full
history). `ohlc_features` and positions MFE/MAE read the per-symbol cache.
`ohlc_features` derives `swing_high_20d`, `swing_low_20d`, `swing_low_50d`, `base_*`,
`breakout_20d_high`, `volume_20d_avg`, `volume_ratio_vs_20d`, `consolidation_atr_pct`
into `stock_analysis.csv`.

**Still open:** cup-and-handle / double-bottom pattern flags, weekly pivots, and fuller
pattern weight in the technical score.

```
output/<date>/history/ohlc.csv
symbol,date,open,high,low,close,volume
```

### 2. Trade levels are non-discriminating — **Mitigated (Phase A)**

The fixed 0.67 ATR ladder in `stock_analysis` is replaced by structure-based levels
(`collector/derived/structure_levels.py`): stop from base/swing low (else MA / ATR
fallback); targets prefer swing high / overhead when they clear `MIN_RR_T1`, else
R-multiples. `risk_reward` / brief `rr_t1` now vary with structure. Relative-volume
gate (`MIN_RELATIVE_VOLUME`, default 1.0) is in the funnel.

### 3. `support1/support2/resistance1/resistance2/pivot` are unusable

These are single-day classic pivots. ICICIBANK on 2026-07-24: close 1428.90, support1
1424.46, resistance1 1432.66 — a **±0.3% band**. For a 3-to-22 trading-day (~1 month)
hold these are noise.

Fix: emit both — keep the intraday pivots but rename them (`pivot_r1_intraday` etc.) and
add weekly/monthly pivots plus swing-structure levels. Requires #1.

### 4. `relative_volume` is broken

Universe stats: min 0.00, **median 0.04, max 0.65**. It should centre near 1.0.
Looks like `volume` and `avg_volume_10d/30d` are in different units, or `volume` is a
partial-session figure written before the close.

KB-03 Ch.4 and Fig 8-1 require a breakout bar at **>1.5–2.0×** the 20-day average.
That rule is currently unenforceable — volume confirmation is simply missing from the
process.

### 5. Promoter holding and pledge — a hard veto with no data

`promoter_holding`, `promoter_pledge`, `insider_buying` are **100% null**.

KB-04 Fig 5-1 makes high-and-rising promoter pledge a **hard veto**, and KB-00 states
governance can veto while valuation can only adjust size. So right now every
recommendation is made with the governance check switched off. That is the most
dangerous of these gaps, not the largest.

Source: NSE/BSE quarterly shareholding-pattern filings (already on your roadmap as
`collector/ownership/`). Quarterly cadence means a small scraper and a cached CSV.

```
output/<date>/ownership.csv
symbol,quarter,promoter_pct,promoter_pct_prev_q,promoter_pledge_pct,
promoter_pledge_pct_prev_q,fii_pct,dii_pct,mf_pct,public_pct,auditor_change_flag
```

---

## P1 — the 30 missing score points

### 6. News sentiment and catalyst classification — 15 points

**Partially addressed.** `collector/derived/news_classify.py` writes `news_enriched.csv`
via keyword rules, and `stock_analysis` joins per-symbol aggregates into
`news_sentiment`, `catalyst_strength`, `major_catalyst`, `risk_event`,
`news_score` / `news_score_final`. `news_count_7d` still comes from `event_risk`
(same-day news window).

Still open: richer classification for unmatched text; multi-day rolling news
history if NSE only returns a thin daily slice. (GitHub Models was retired —
not used here.)

### 7. Institutional activity — 10 points

`institution_score` is entirely null. `fii.csv` has market-wide FII/DII flow (2 rows)
but nothing per stock. `block_deals.csv` had 1 row on 2026-07-24 and is not joined to
`stock_analysis.csv`.

Add: per-stock FII/DII/MF holding and quarter-on-quarter delta (from #5), bulk-deal
history, and a `block_deal_7d` / `bulk_deal_7d` flag joined onto each symbol.

### 8. Stock-level options — 5 points — **Partial (Phase A)**

**Landed:** `stock_options.csv` (env-gated, `PARKHU_STOCK_OPTIONS=1`) fetches NSE Equity
chains for top-N F&O underlyings and joins `pcr` / `max_pain` / `atm_iv` into
`stock_analysis`. Index `options.csv` (NIFTY/BANKNIFTY) unchanged.

**Still open:** `iv_percentile_1y`, full ~215-name coverage in CI, and wiring the
KB-14 options 5 pts into `build_scores`.

### 9. Constant-value scores with no discriminating power

| Column | Actual range across 368 names | Should be |
|---|---|---|
| `macro_score` | constant **30** | function of India VIX, DXY, crude, US 10Y, FII flow, Asia/Europe cues |
| `fno_score` | constant **3** (201 non-null) | scaled 0–100 from OI buildup + turnover rank |
| `smart_money_score` | constant **3** | 0–100 once #7 lands |
| `volume_score` | caps at **33** | 0–100 |
| `technical_score` | maxes at **87** | 0–100, and stop double-counting the capped volume_score |

Also blank throughout: `supertrend`, `ichimoku_signal`, `obv`, `cmf`,
`revenue_surprise`, `profit_surprise`, `guidance`, `order_book_growth`,
`liquidity_sweep`. `supertrend` matters most — KB-08 names it as the trailing-stop
mechanism and KB-09 Ch.3 requires trailing stops, so that rule has no input today.

---

## P2 — the Learning Engine, and quality of life

### 10. No trade outcome history — "expected profit %" is currently a target, not an expectation

Nothing persists yesterday's shortlist or what happened to it. So there is no win rate,
no average R multiple, no MFE/MAE, no way to calibrate. KB-12 (Trade Database) and KB-13
(Learning Engine) both assume this exists.

This is the highest-leverage addition after #1: it converts every number in the morning
brief from a projection into something measurable.

```
trades/open.csv
trade_id,symbol,date_opened,entry,stop,t1,t2,t3,horizon_band_days,score,
conviction,thesis_tag,sector,qty,risk_rupees

trades/closed.csv
trade_id,symbol,date_opened,date_closed,exit_price,exit_reason,
r_multiple,pct_return,days_held,mfe_pct,mae_pct,hit_t1,hit_t2,gap_flag
```

A nightly job walks `open.csv` against the new OHLC (#1), updates MFE/MAE, and closes
rows on stop / target / time-stop. Then the brief can quote a real hit rate.

### 11. No stable pointer to the newest run

**Addressed.** Each collect writes `output/latest/` (uncompressed mirror),
`output/index.json`, and `research_pack.md` / `.json`. See
[`docs/claude-handoff.md`](claude-handoff.md). `latest.zip` remains archive-only.
Note: some LLM sandboxes still block `raw.githubusercontent.com` — then clone or
paste the pack.

### 12. Sector labels come from TradingView's taxonomy, and it breaks the 25% cap

`LODHA` (Lodha Developers, a real-estate developer) is labelled **`Finance`**. On
2026-07-25 the top three names by score were LODHA, ICICIBANK and IIFL — all three
counted as one sector, so IIFL was queued out on the 25% cap even though LODHA is not a
lender in any meaningful sense.

KB-09's sector cap exists to stop hidden single-bet concentration. Wrong labels make it
both too strict (as here) and too loose (a genuine three-lender bet could slip through
under different labels). TradingView's `sector`/`industry` pair is fine for display, but
the cap should run on an NSE/NIFTY sector mapping instead — you already pull the NIFTY
sectoral indices in `sectors.csv`, so add `nse_sector` to `stock_analysis.csv` from the
same mapping used for `rs_vs_sector_1m` and use that for concentration.

### 13. Smaller items

- **Delivery trend**: `delivery.csv` is one day. Add `deliv_pct_5d_avg`, `deliv_pct_20d_avg`
  — a single day's delivery % is noisy as an accumulation filter.
- **Earnings surprise**: `revenue_surprise` / `profit_surprise` blank. KB-05's
  post-earnings-drift setup (T+1 to T+20) needs actual vs estimate.
- **Liquidity floor**: KB-00 Art. II defers numeric liquidity floors to KB-08/KB-09, and
  neither manual defines one. Add `turnover_20d_avg_cr` and an `asm_gsm_flag` so
  KB-02's surveillance exclusion is checkable, then pick a floor and version it per KB-16.
- **`ema20` is null** while ema50/100/200 are populated — likely a one-line bug.
- **`report.json` is listed as `present: false` in `manifest.json`** even though the file
  exists; the manifest is written before the report.

---

## Note on scheduling

You mentioned moving the scan to 5 AM. GitHub Actions cron is **UTC**, so 05:00 IST is
`30 23 * * *` (23:30 UTC the previous day). The workflow currently runs `0 9 * * 0-5`
(09:00 UTC = 14:30 IST). Leave a margin — the run takes ~45 s but Actions queueing can
add several minutes, and my brief fires at 06:09 IST.

---

## What I would do first

1. **OHLC history (#1)** — unblocks #2, #3, #10 and most of the technical score.
2. **Trade log (#10)** — starts accumulating the only data that can validate any of this.
3. **Promoter pledge (#5)** — closes an open governance veto.
4. **News classification (#6)** — keyword path landed; harden coverage / 7d history.

1 and 2 together change the brief from "here are plausible setups" to "here are setups,
and here is how this process has actually performed."
