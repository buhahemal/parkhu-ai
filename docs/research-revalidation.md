# Research revalidation — status

Full-universe walk-forward was deferred after a panel performance/runtime concern.
This document records the **RELIANCE smoke gate** (2022-01-01 → 2025-12-31,
`--step-days 5`, `--top-n 1`) plus the operational prerequisites that did ship.

Artifacts: `output/research/smoke_reliance_*` (gitignored).

## Smoke answers (single name — not decision-grade)

| Question | Smoke finding |
|---|---|
| Does `proxy_funnel` beat baselines? | **No on this sample.** Funnel n=5 exp≈0.07% vs baseline n=15 exp≈0.16% vs random n=39 exp≈−0.26%. Too small / single-name to adopt live edits. |
| Realized RR sweep floor? | At RR 2.0: n=5. At RR ≥3.0: **n=0** (horizon cliff). Do not raise `MIN_RR_T1` from smoke alone. |
| Gates droppable with independent trend? | Single-name ablation is not reliable (ADX/RS show demote_candidate here; pilot on 30 names kept RS). Re-check on full universe. |
| `range_low_vol`? | Smoke recommends disable (n=2, negative). Calendar cost unknown until full-universe regime run. |

**Survivorship bias:** OHLC is today’s listed universe; delisted names are absent.

## What did ship (safe for daily / Actions)

1. **OHLC keep-all (stock-wise)** — full history in `database/ohlc/<SYMBOL>.csv` (never trim); cold/new uses Yahoo `period=max`; dated `history/ohlc.csv` is a tiny pack slice only; ignore-list skips only true no-data exceptions.
2. **Dual daily modes** — `PARKHU_RUN_MODE=post_close` (18:00 IST) and `premarket_context` (06:00 IST, ideas reused, ledger untouched).
3. **Publish validation** — pack schema/session/data_quality checked before promoting `output/latest/`; failed runs keep prior latest.
4. **Research speed path** — vectorized `build_panel`, strategy panel reuse, de-collinearized proxy trend (`SMA50>SMA200`), `rr-sweep` CLI.

## Live decision rules

Unchanged: `MIN_RR_T1=2.0`, trend+ADX both live, RS as-is, 9-component score and 70/80 bands untouched.

## Next

Re-run `run` / `ablation` / `expectancy` / `regime` / `rr-sweep` on the full
`output/research/full_universe_symbols.txt` list with `--step-days 1 --top-n 5`,
then replace this smoke section with exit-criteria answers from those reports.
