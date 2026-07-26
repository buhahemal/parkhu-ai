# Research backtest (Step 1)

Free-first walk-forward test of the swing funnel using **OHLC-proxy** gates only.
Implements Finding #1 from the Parkhu Research Review: measure whether the process
beats a coin flip / naive baseline before changing live gates.

Live selection path (for comparison): [`universe-to-idea.md`](universe-to-idea.md).

## What is implemented

| Piece | Location |
|-------|----------|
| Research OHLC lookback (~5y) | `PARKHU_OHLC_RESEARCH_LOOKBACK=1260`, `PARKHU_OHLC_RESEARCH_PERIOD=5y` in [`config/settings.py`](../config/settings.py) — **daily collect still defaults to 250** |
| Multi-year Yahoo backfill | `python -m scripts.backfill_ohlc_research` |
| Point-in-time features | [`research/features_from_ohlc.py`](../research/features_from_ohlc.py) |
| Walk-forward engine | `python -m research.backtest run --start … --end …` |
| Deferred Steps 2–12 stubs | [`research/deferred.py`](../research/deferred.py) |

## OHLC-proxy vs live funnel

**Included historically** (from free Yahoo bars):

- Universe (has close)
- Trend proxy (`cmp > SMA200` & `EMA50` & ADX) — not identical to TradingView `trend_label`
- `cmp > SMA200`, `cmp > EMA50`
- ADX14 / RSI14 bands (same thresholds as [`config/risk.py`](../config/risk.py))
- RS vs Nifty (1m excess return)
- Relative volume vs 20d
- Structure levels / `MIN_RR_T1` / horizon mandate

**Excluded historically** (no free point-in-time source):

- Delivery %
- Earnings blackout / event risk
- TradingView `tech_rating`
- Live `parkhu_score` components (news, fundamentals, options, …) — ranking uses a simple **proxy_score** (ADX + RS)

Survivorship bias is only partly mitigated (Yahoo + current universe). Residual bias is accepted and documented; a true delist master is imperfect for free.

## Commands

```bash
# 1) Pull multi-year bars (rate-limited; start small)
PARKHU_MAX_SYMBOLS=50 python -m scripts.backfill_ohlc_research

# Or explicit list + index (^NSEI → database/ohlc/NIFTY.csv)
python -m scripts.backfill_ohlc_research --symbols-file /tmp/syms.txt

# 2) Walk-forward OOS report
python -m research.backtest run \
  --start 2022-01-01 --end 2025-12-31 \
  --limit 50 --step-days 5 --top-n 5 \
  --out output/research/backtest_2025-12-31
```

Outputs:

- `summary.md` / `summary.json` — win rate, median, expectancy, max DD, skew per strategy
- `trades.csv` — synthetic fills (stop / T1 / time)

Strategies compared:

1. **proxy_funnel** — full OHLC-proxy gate stack  
2. **baseline_adx_rsi** — ADX+RSI only (+ levels)  
3. **random** — random survivors among level-valid names  

Primary question: does proxy_funnel beat the baselines on **OOS** expectancy / median / drawdown?

## Rate limits

Reuse daily OHLC chunking: `PARKHU_OHLC_CHUNK_SIZE`, `PARKHU_OHLC_CHUNK_SLEEP_S`,
`PARKHU_OHLC_RETRY_WAIT_S`, `PARKHU_OHLC_RETRY_MAX`. Do **not** commit multi-year
full-universe bar dumps unless you explicitly choose to.

## Step 2 — Gate ablation (Epic B)

```bash
python -m research.backtest ablation \
  --start 2022-01-01 --end 2025-12-31 \
  --symbols-file /tmp/parkhu_research_pilot_syms.txt \
  --step-days 5 --top-n 5 \
  --out output/research/ablation_pilot
```

Writes `ablation.md` / `ablation.json`: leave-one-gate-out Δ expectancy vs full funnel,
pairwise exclusion Jaccard, and `recommended_demotions` (research flags only).

Optional research-only demotions (does **not** change the live brief):

```bash
export PARKHU_RESEARCH_DEMOTED_GATES=trend,sma200   # example
export PARKHU_RESEARCH_APPLY_DEMOTIONS=1            # apply in research.backtest run
```

## Step 3 — Hit-rate expectancy (Epic B)

```bash
python -m research.backtest expectancy \
  --start 2022-01-01 --end 2025-12-31 \
  --symbols-file /tmp/parkhu_research_pilot_syms.txt \
  --step-days 5 --top-n 5 \
  --out output/research/expectancy_pilot
```

Segments hit-rate-to-T1-before-stop by ADX / proxy_score buckets and prints the
break-even R:R floor `R = (1-p)/p`. Live `PARKHU_MIN_RR_T1` stays unchanged until
you deliberately adopt a new floor.

## Steps 4–12 (still gated)

| Step | Deliverable |
|------|-------------|
| 4 | Regime-conditioned thresholds |
| 5 | Score deciles + coverage floor |
| 6 | Basket correlation / factor check |
| 7 | Pre-committed kill criterion |
| 8 | Beta adjust + GARCH stops (free `arch`) |
| 9–11 | Regime factors / Value-Quality-LowVol / EV — only after evidence |
| 12 | Inverse-vol → shrinkage MVO (not early MVO on 5–10 names) |

Stubs in [`research/deferred.py`](../research/deferred.py) raise until those steps are built.

**Out of scope:** paid L2 order-book / tick microstructure (wrong timeframe for EOD swings).

## Exit criterion (Step 1)

An OOS `summary.md` exists that answers: *is there any edge vs baseline/random?*  
Do **not** change live gate honesty (“zero ideas is valid”) until ablation / expectancy
evidence says a gate or R:R floor should change.
