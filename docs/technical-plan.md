# Parkhu AI — Technical Plan

The design rationale behind the brief layer: what each rule is, why it was chosen, what
evidence supports it, and what would have to change to improve it.

`docs/swing-brief.md` is the operator's guide — how to run it and read the output. This
document is the engineer's guide — why it is built this way. Read this before changing a
threshold, adding a gate or replacing a formula.

Every number here was measured against the live universe on **2026-07-21 → 2026-07-26**
(363–369 names), with the defect register re-verified against `output/2026-07-26`. Where a
claim rests on data, the measurement is quoted so you can re-derive it rather than trust
it.

> **Keep this honest.** Several defects recorded during the first pass were fixed by a
> later collector run mid-write, and the text below was corrected rather than left to rot.
> Re-run the checks in §11 before trusting any measurement here; a design doc whose
> evidence has silently expired is worse than no doc.

---

## 1. What this layer is for

The collector produces facts. The knowledge base defines rules. Neither, alone, tells you
what to do on a Monday morning.

The brief layer is the join: it applies the KB's numeric limits to the collector's output
and emits a decision — buy this, this many shares, exit that — with the reasoning
attached. It is deliberately **deterministic**: no LLM, no network, no judgement. Given
the same CSVs it produces the same brief, which is what makes it auditable and what makes
`trades/closed.csv` meaningful as a performance record.

### Layering, and why

```
collector/<agent>/        raw facts from external sources
collector/derived/        deterministic metrics over those facts
collector/brief/          decisions under the KB limits          <- this document
```

The separation exists because the three layers fail differently and change at different
rates. A collector agent fails when NSE rate-limits you. A derived metric fails when a
formula is wrong. A brief fails when a *rule* is wrong. Keeping them apart means a bad
threshold never corrupts stored data — regenerate the brief and the history is intact.

**Consequence worth preserving:** `collector/brief/` never writes to a CSV another layer
reads. It only reads `output/<date>/*.csv` and writes `swing_brief.*` and `trades/*`.
Keep it that way; it is why a brief can be rebuilt for any past date without a re-collect.

---

## 2. The gate funnel

Gates are declared as one ordered list in `build_payload`, each a name and a mask. The
survivor count after every gate is recorded in `funnel` and printed whenever there are no
ideas — so a day with no trade explains itself.

Measured on 2026-07-25:

| # | Gate | Survivors | Cost | Source | Why |
|---|---|---|---|---|---|
| 0 | universe | 363 | — | — | rows with a price |
| 1 | `trend_label == Bullish` | 176 | −187 | KB-01 | swing long only; no counter-trend entries |
| 2 | `cmp > sma200` | 148 | −28 | KB-03 Dow | above the long-term line |
| 3 | `cmp > ema50` | 143 | −5 | KB-03 | above the intermediate line |
| 4 | `adx14 > 25` | 80 | −63 | KB-03 Fig 3-1 | *"ADX > 25 confirms a tradeable trend"* |
| 5 | `rsi14` in 40–80 | 79 | −1 | KB-03 Ch.3 | uptrends hold 40–80; a break of 40 signals regime change |
| 6 | RS > 0 vs NIFTY **and** sector | 64 | −15 | KB-02 | leadership, not drift |
| 7 | `delivery_pct >= 40` | 43 | −21 | CONFIG | accumulation over churn |
| 8 | no earnings within 21d | 16 | −27 | KB-05 Fig 4-1 | *"stand aside (default)"* |
| 9 | `event_risk_score <= 1` | 14 | −2 | CONFIG | corp actions, ex-dates |
| 10 | TV rating not Sell | 14 | −0 | — | cheap contradiction check |

**Order is cheapest-and-broadest first.** Not for speed — the universe is 363 rows — but
because the funnel is *read by a human*. Each line should narrow the story: all stocks →
uptrends → strong uptrends → leaders → accumulated → clean calendar. Reordering makes the
numbers meaningless as an explanation.

### Why these gates and not others

**Trend before momentum.** KB-03 Fig 8-2: in a range, *"technicals unreliable → stand
aside"*. Momentum on a rangebound name is noise, so trend gates come first and momentum
only refines what survives.

**Two RS checks, not one.** A stock can beat the index while lagging its own sector,
which usually means the sector is carrying it. Requiring both isolates genuine leadership.
Gate 6 costs 15 names — real work.

**Delivery % as a quality filter.** Gate 7 costs 21 names, the third-largest cut. Delivery
percentage separates stock actually taken into demat accounts from intraday churn — KB-03
Ch.4 lists it under volume confirmation. The 40% threshold is **not in the KB**; see
§8 CONFIG DECISIONS.

**The earnings gate is the most expensive: 43 → 16.** That is correct, not a bug. Late
July is peak Q1 results season and KB-05 Fig 4-1 makes standing aside the default:
*"Parkhu AI's structural preference is to trade the confirmed drift after results."*
Indian single stocks routinely gap 5–20% on results (KB-00 Art. V), and a 2% risk budget
cannot survive an unhedged 15% gap. Expect this gate to be nearly free in November and
brutal in late January, April, July and October.

### Gates deliberately not implemented

| Not gated | Why not |
|---|---|
| Relative volume > 1.5× | **Newly viable — implement this.** The field was broken when the gates were written (max 0.65, median 0.04) and is now sane on 2026-07-26: min 0.06, median 0.74, max 22.3. See below. |
| Breakout from a base | Requires OHLC history the dataset does not have. |
| MACD confirmation | Available and populated, but it disagrees with the trend gates often enough that adding it as a *gate* would have cut the 2026-07-25 list from 3 to 1. Currently surfaced as a **flag** instead — see §7. |
| Promoter pledge (KB-04 hard veto) | Column is 100% null. The veto cannot run at all. |
| Liquidity floor | KB-00 Art. II defers the number to KB-08/KB-09; **neither manual defines one**. The TradingView screener has **no market-cap floor** (NSE equities only); liquidity is left to delivery / relative-volume gates. |

#### The relative-volume gate is now available — sizing it

KB-03 Ch.4 and Fig 8-1 want a breakout bar at **1.5–2.0×** the 20-day average. Measured
against the 43 names surviving gate 7 on 2026-07-26:

| Threshold | Survivors of 43 |
|---|---|
| ≥ 1.0 | 12 |
| ≥ 1.2 | 7 |
| **≥ 1.5** | **3** |
| ≥ 2.0 | 1 |

KB-03's literal 1.5 leaves three names *before* the earnings and event gates, which would
routinely produce zero ideas. Two defensible readings:

- Apply 1.5 only to names claiming a **breakout** (needs OHLC to identify one), leaving
  continuation setups ungated — closest to KB-03's intent, but blocked on P0.
- Gate at **1.0** now — "at least average participation" — as a weak-volume filter, and
  tighten once OHLC allows the breakout distinction.

The second is implementable today and would be a genuine improvement: nothing currently
stops a name qualifying on a day of below-average participation. Add as
`MIN_RELATIVE_VOLUME` in `config/risk.py`, defaulted to 1.0, and sweep it before fixing
the value. **Verify the field's distribution first** — it was broken once and the fix is
recent, so treat one clean reading as provisional.

---

## 3. Scoring

KB-14 Fig 2-1 allocates 100 points across ten components. Four have no data:

| Component | Weight | Status |
|---|---|---|
| Technical | 20 | live, rebuilt |
| Fundamental | 15 | live |
| Earnings | 15 | live |
| News | 15 | **null** |
| Institutional | 10 | **null** |
| Options | 5 | **null** |
| Sector | 5 | live |
| Relative strength | 5 | live |
| Macro | 5 | **constant 30 — no discriminating power** |

**35 of 100 points cannot be computed.** The choice was between three options:

1. Score out of 65 and compare against a bar built for 100 → nothing ever reaches 80.
2. Impute the missing components → invents evidence, which KB-00 Art. IV forbids.
3. **Drop the dead weights and renormalise the rest to 100**, reporting the shortfall.

Option 3 is implemented. `scoring.weight_unavailable_pct` carries the 35 into the brief so
every consumer can discount confidence. The critical property: **the Buy bar stays at 80**
(KB-14 Fig 3-1). Renormalising the inputs is defensible; moving the bar to fit the
available data is not.

Measured effect: 1–4 Buy-band names per day across the test week — 4, 2, 3, 1, 3. A screen
producing zero most days would be useless; one producing twenty would not be selective.
That range is the sanity check to preserve if you change the weights.

### Why `technical_score` is rebuilt rather than reused

**This rationale has partly expired — revisit it.** The rebuild was introduced because the
collector's `technical_score` maxed at **87 across 368 names**, summing a `volume_score`
itself capped at 33. A component that cannot express its own top value distorts every
comparison built on it. On 2026-07-26 both now reach 100, so that defect is fixed.

What still justifies the rebuild is weaker but real: the local formula is explicit,
weighted to KB-14's own sub-allocation, and changes only when this file changes. What
argues against it is that two technical scores now exist and can silently diverge.

**Recommended:** compare the two across the universe. If they rank names near-identically,
delete the rebuild and use the collector's — one source of truth beats a marginally better
formula. If they diverge materially, document why before keeping both. The brief
recomputes as:

```
technical = 0.40 * trend_score      # KB-03 Ch.7: trend dominates
          + 0.30 * momentum_score   # confirms, does not lead
          + 0.20 * delivery quality # KB-03 Ch.4 volume class
          + 0.10 * ADX scaled       # trend *strength*, distinct from direction
```

The 40/30/20/10 split mirrors KB-14's own technical sub-allocation (trend/structure 7,
volume/delivery 6, momentum 4, pattern 3 out of 20) with pattern dropped — patterns need
OHLC. It is a **CONFIG DECISION**, not a KB formula.

### Relative strength is ranked, not thresholded

`rs_vs_nifty_1m` is an unbounded percentage. Feeding it into a 0–100 score directly would
let one extreme name dominate. It is converted to a **universe percentile**, which is also
what KB-14 means by a cross-sectional factor. Absolute RS still gates at gate 6; the score
only cares about ordering.

---

## 4. Trade levels — the largest deliberate override

### The defect

`stock_analysis.csv` emits a fixed ladder: entry ±0.5 ATR, stop −1.5 ATR, targets
+1/+2/+3 ATR. Therefore:

```
risk_reward = 1.0 ATR / 1.5 ATR = 0.67   on all 368 rows, every day
```

KB-08 Ch.4 rejects anything below 1:1. **A literal implementation vetoes the entire
universe daily.** This is not a tuning problem; the column carries no information — its
variance is zero.

Second defect: `support1`/`resistance1` are classic pivots computed from a single session.
When the gates were written the band was **0.3% wide** — ICICIBANK on 2026-07-24 closed at
₹1,428.90 with support1 ₹1,424.46 and resistance1 ₹1,432.66. On 2026-07-26 the median band
has widened to **2.47%**, so this is materially better than it was.

It is still not swing structure. A 2.5% band on a name with a 16-day horizon and a 7% stop
describes today's session, not the level whose loss disproves the thesis. The override
stands, but the gap has narrowed and is worth re-measuring rather than assumed.

### The replacement, and why each step

```python
structure   = highest moving average below price   # ema50 > sma50 > ema100 > sma200
struct_stop = structure - 0.5 * ATR                # buffer beneath the level
ceiling     = min(3 * ATR, 8% of price)            # most we will risk
if (entry - struct_stop) > ceiling:
    dist = 2 * ATR;  mode = "atr_fallback"         # structure too far to risk
dist  = clamp(dist, 1 * ATR, ceiling)              # KB-03: inside 1 ATR is noise
stop  = entry - dist
T1,T2,T3 = entry + 2R, 3R, 4R
```

**Why moving averages as structure.** KB-08 Fig 3-1 wants the stop *"below the invalidating
level (base, order block, swing low)"*. Swing lows need OHLC. Moving averages are the only
multi-week structure in the dataset, and a trend-following entry does genuinely invalidate
on losing them. This is a substitute, not an equal.

**Why a 0.5 ATR buffer.** A stop exactly at a widely-watched level is where liquidity
pools. The buffer is a CONFIG DECISION.

**Why the ATR fallback matters more than it looks.** When structure sits more than 8%
below price, honouring it would breach the risk ceiling. KB-08 Fig 3-1 permits an ATR stop
*"when structure is unclear"* — an unreachably distant structure is that case. But this
inverts the stop's meaning: the position now exits *above* the level that would actually
disprove the thesis. The brief therefore sets `stop_above_structure` and prints the true
invalidation level. **All three ideas on 2026-07-25 were in this state**, which tells you
the screen is selecting extended names — a real characteristic, surfaced rather than
hidden.

**Why targets are R-multiples, not resistance.** There is no trustworthy resistance in the
dataset (see the 0.3% pivots). T1 is placed at exactly 2R to satisfy KB-08's floor.

The honest consequence, stated in the brief and repeated here: **`rr_t1` is 2.0 by
construction and does no filtering.** It is a floor being met by definition, not evidence
of asymmetry. This is the single weakest part of the design and the first thing that
should change when OHLC lands.

**Why the 52-week high is a flag, not a cap.** Capping T1 at the 52w high was implemented
first and then removed: because T1 is defined as 2R, any cap drags `rr_t1` below 2.0 and
triggers the KB-08 auto-reject. Measured on 2026-07-25 it silently killed 10 of 15
candidates — precisely the breakout names a momentum screen exists to find. Overhead
supply is now reported as `t1_above_52w_high` and `room_to_52w_high_pct`.

> **Design rule this illustrates:** never let an advisory signal feed a hard veto through
> a derived quantity. Flag it, and let the reader weigh it.

### Holding period

```
days_to_target ≈ (target_distance / ATR)²
```

From the random-walk approximation that expected drift over N days scales with ATR·√N.
Inverted, it answers the question KB-02 actually asks: *is this target reachable inside
the mandate?* Clamped to 3–22 trading days (~1 month). Ideas with unclamped T1 hold above
22 days are hard-rejected. It is a feasibility estimate, **not a forecast**, and must
never be presented as one.

---

## 5. Position sizing

KB-08 Fig 2-1 and KB-09 Fig 1-1 give two independent caps, and KB-08 Ch.2 resolves them:
*"the binding constraint is whichever produces the smaller position."*

```
q_risk = floor(capital * 2%  / (entry - stop))   # KB-08 risk budget
q_expo = floor(capital * 10% / entry)            # KB-09 exposure cap
qty    = min(q_risk, q_expo)
```

**At ₹1,00,000 the exposure cap always binds.** For the risk cap to bind, the stop would
have to sit more than 20% away — outside the 8% ceiling by construction. Every idea in the
test week reported `exposure cap (10%/name)`.

Two consequences worth understanding rather than fixing:

- **Realised risk is far below 2%.** A ₹10,000 position with a 7% stop risks ₹700, i.e.
  0.7% of capital. Portfolio heat across 4 positions measured **2.23%**, against a
  theoretical 8%. The system is much more conservative than the KB permits, because the
  KB's caps were written for a larger book.
- **High-priced stocks become untradeable.** One ABBOTINDIA share is ₹28,225 against a
  ₹10,000 cap. Rather than silently dropping these, they are reported under
  `unaffordable_at_this_capital`. Silent filtering by price would be an invisible universe
  bias.

`binding_constraint` is emitted per idea so this is never a mystery.

---

## 6. Sector concentration

KB-09 Fig 5-1 caps any sector at 25%. The purpose is to stop a hidden single bet.

TradingView's `sector` field cannot serve that purpose. Its `Finance` bucket on
2026-07-25 contained:

| Industry | Count |
|---|---|
| Finance/Rental/Leasing | 28 |
| Major Banks | 18 |
| Regional Banks | 7 |
| Investment Managers | 7 |
| Life/Health Insurance | 6 |
| **Real Estate Development** | **6** |
| Real Estate Investment Trusts | 6 |
| … | … |

A real-estate developer and a private bank do not share a risk driver. Measured cost of
getting this wrong: on 2026-07-25, LODHA (developer), ICICIBANK (bank) and IIFL (NBFC) all
counted as `Finance`, and **IIFL was queued out of the brief** for breaching a cap it did
not truly breach. The brief went from 2 ideas to 3 once fixed.

`INDUSTRY_TO_RISK_SECTOR` splits `Finance` into Banks, NBFC & Capital Markets, Insurance
and Real Estate. Everything else keeps its TradingView sector.

> **Overlap warning.** `collector/derived/_utils.py` resolves NIFTY RS benchmarks on
> `industry` before `sector`. The brief's `INDUSTRY_TO_RISK_SECTOR` answers a different
> question — RS wants *"which NIFTY index benchmarks this name"*, concentration wants
> *"which bet is this"*. They are not always the same mapping (a REIT benchmarks against
> NIFTY_REALTY but is a distinct concentration bucket from a developer). **Do not collapse
> them into one table without deciding which question wins.** If they are unified,
> `risk_sector` should remain a separate column derived from the shared industry resolution.

---

## 7. The suggestion ledger

The gap this closes: without outcome tracking, "expected profit 14.4%" is a target wearing
the costume of an expectation. There is no win rate, so nothing weights it.

### Model

```
trades/open.csv     status: open | partial
trades/closed.csv   exit_reason: stop | invalidated | time_stop | t3
```

Review order is KB-17 SOP-3 verbatim, and the order is load-bearing — an invalidated
thesis exits even if price is above T1:

1. two or more entry conditions gone → **EXIT, invalidated**
2. price ≤ stop → **EXIT, stop**
3. price ≥ T3 / T2 / T1 → full exit / bank more / **bank partial, trail, stop to breakeven**
4. held past the T2 horizon → **EXIT, time stop** (KB-08: *"capital has an opportunity cost"*)
5. one condition gone → **TIGHTEN / REVIEW**
6. earnings now inside 21 days → **EARNINGS AHEAD** (KB-05)
7. otherwise → **HOLD**, update MFE/MAE

**Why "two or more conditions" for invalidation.** One broken condition on a volatile name
is noise; requiring two avoids exiting on a single indicator, which KB-00 Art. IV forbids
for entries and the same logic applies to exits. A single break still surfaces as
TIGHTEN/REVIEW.

**Why re-confirm instead of re-open.** ICICIBANK was suggested on four separate days in the
test week. Opening four positions would breach every concentration rule invisibly. KB-09
Ch.3 allows scaling in *on confirmation*, so the ledger increments `reconfirmed_count` and
leaves sizing to the operator.

**Why a suggestion ledger, not a portfolio.** The system does not know what was traded.
Recording suggestions keeps the record honest about what the *process* produced, which is
what needs measuring. The `taken` column is never written by the pipeline after row
creation — set it yourself to filter the stats to real fills.

**Why the stats refuse to be a statistic.** Below 20 closed rows `realised_stats()` returns
a `note` saying the sample is too small. A 33% win rate over 3 trades is not information,
and presenting it as a percentage invites treating it as one.

### Known limits

| Limit | Cause | Effect |
|---|---|---|
| MFE/MAE sampled from daily `cmp` | no OHLC | understates both extremes |
| Stop detected only on close | no intraday | a gap through the stop logs the close, not the fill |
| Time stop counts weekdays | no holiday calendar | marginally lenient, never premature |
| Chronological runs assumed | append-only ledger | re-running an old date after newer ones interleaves wrongly |

---

## 8. CONFIG DECISIONS — ours, not the KB's

KB-16 requires that thresholds the knowledge base does not specify be logged as decisions
rather than presented as rules. These live in `config/risk.py`, marked in comments.

| Constant | Value | Why this value | How to challenge it |
|---|---|---|---|
| `MAX_STOP_ATR` | 3.0 | KB gives a floor (1 ATR) but no ceiling; 3 ATR is a common swing bound | measure stop-hit rate by ATR multiple once ≥50 closed rows exist |
| `MAX_STOP_PCT` | 8.0 | keeps a single stop inside the risk budget at realistic sizes | as above |
| `ATR_FALLBACK_MULT` | 2.0 | midpoint of the 1–3 ATR band | as above |
| `MIN_DELIVERY_PCT` | 40.0 | near the universe median (48.4%); costs 21 names | vary 30/40/50 and compare realised R |
| `MAX_EVENT_RISK_SCORE` | 1.0 | cheap; costs only 2 names | low priority |
| technical sub-weights | 40/30/20/10 | mirrors KB-14's internal 7/6/4/3 with pattern dropped | restore pattern weight when OHLC lands |
| `TOP_N_IDEAS` | 5 | KB caps positions at 10, not new ideas per day | raise if the ledger shows capacity |

Also unspecified by the KB and therefore **not enforced**: portfolio heat cap
(*"well below"* the arithmetic 20%, no figure), minimum cash reserve (*"always
maintained"*, no figure), minimum independence classes for confirmation (Art. IV defers to
KB-14; KB-14 is silent), and any numeric liquidity floor.

---

## 9. Known data defects

Each has a workaround above; this is the register.

Verified against `output/2026-07-26` (364 rows, 18 agents ok).

| # | Defect | Evidence (2026-07-26) | Impact | State |
|---|---|---|---|---|
| 1 | `risk_reward` constant | 0.66/0.67 only | would veto the universe; levels rebuilt | **open** |
| 2 | pivots too narrow | median band 2.47% of price | not swing structure; MA structure used | **narrowed** (was 0.3%) |
| 3 | `relative_volume` broken | min 0.06, median 0.74, max 22.3 | — | **FIXED** — now gate it, see §2 |
| 4 | score points null | news 15, institutional 10, options 5 | scores provisional | **open** |
| 5 | `promoter_pledge` null | 0/364 | **KB-04 governance veto never runs** | **open** |
| 6 | `macro_score` constant | 1 distinct value (30) | no discriminating power | **open** |
| 7 | `fno_score` constant | 3 distinct values | weak but no longer constant | **improved** |
| 8 | `ema20` null | 0/364 | likely one-line bug | **open** |
| 9 | index series does not chain | `prev_close` matches prior `close` on **7 of 34** transitions | `market_regime`, `nifty_pct_change` unreliable | **open** |
| 10 | non-trading-day folders | 25 Jul = Saturday (3 runs), 26 Jul = Sunday | briefs built against non-sessions | **open** |
| 11 | `days_to_earnings` null | 26 of 364 names | KB-05 blackout unverifiable for those | **open** |
| 12 | `technical_score` capped | now reaches 100 | — | **FIXED** — reconsider the rebuild, see §3 |

Also still empty universe-wide: `supertrend`, `obv`, `cmf`, `news_sentiment`, `pcr`.
`supertrend` matters most of these — KB-08 names it as the trailing-stop mechanism and
KB-09 Ch.3 requires trailing stops, so that rule has no input.

Defects 1, 5, 9 and 10 are the open priorities — see §10.

---

## 10. Roadmap, with acceptance criteria

Ordered by leverage. Each item states how you know it is done.

### P0 — daily OHLC history — **Partial (Phase A landed)**

```
output/<date>/history/ohlc.csv
symbol,date,open,high,low,close,volume        # ~250 sessions x 368 names
```

**Landed:** collector + GitHub-backed `database/ohlc/<SYMBOL>.csv` raw store (warm ~5d
incremental fetch; new/short symbols full ~400d backfill); swing/volume features in
`stock_analysis`; structure-based stops/targets; `rr_t1` / `risk_reward` vary with structure.
**Still open:** pattern library (cup/handle etc.) and technical-score pattern weight.

### P0 — relative-volume gate (defect 3) — **Landed (threshold pending sweep)**

`MIN_RELATIVE_VOLUME` (default **1.0**) is in `config/risk.py` and the brief funnel.
**Still open:** record a sweep across 1.0 / 1.2 / 1.5 survivor counts here before locking
the production value.

### P0 — session correctness (defects 9, 10)

**Done when:** a folder for a non-trading day either is not created or carries an explicit
`is_trading_day: false` in `report.json`; the brief refuses to open new positions against
a non-session; and a validator asserts each day's `prev_close` equals the prior session's
`close`, failing the run loudly instead of silently producing a wrong regime.

### P1 — trade outcome depth — **Partial (Phase A)**

**Landed:** when `history/ohlc.csv` is present, `positions.review` uses session high/low
for MFE/MAE, triggers stops on low breach, and sets `gap_flag` on open-through-stop gaps.
**Still open:** ≥20 closed rows for meaningful `realised_stats()`; holiday-aware day counts.

### P1 — promoter pledge (defect 5)

**Done when:** `ownership.csv` populates `promoter_pct`, `promoter_pledge_pct` and their
prior-quarter values, and the brief runs KB-04's veto — a name with high and rising pledge
is rejected outright, not merely down-sized.

### P2 — news classification (15 points)

The text is already collected in `news.csv`; only the classification step is missing.

**Done when:** `news_sentiment`, `catalyst_strength` and `major_catalyst` are populated,
`news_count_7d` reflects a rolling window, and `weight_unavailable_pct` drops from 35 to 20.

### P2 — institutional (10) and options (5) — **Options data prep only (Phase A)**

**Landed:** env-gated `stock_options.csv` (`PARKHU_STOCK_OPTIONS=1`) fills
`pcr` / `max_pain` / `atm_iv` on `stock_analysis` for top F&O names. Scoring weight is
**not** wired yet (avoids Buy-band churn).
**Done when:** `weight_unavailable_pct` ≤ 5 and the provisional-score caveat is removed
(requires institutional feed + options score in `build_scores`).

### P3 — the constant scores (defects 6, 7)

**Done when:** `macro_score` varies with VIX, DXY, crude, US 10Y and FII flow, and
`fno_score` scales 0–100 — verified by a non-zero standard deviation across the universe.

---

## 11. Invariants — do not break these

Regression checks worth keeping as tests. All held across 2026-07-21 → 26.

Re-verify the defect register the same way, since several entries in §9 expired within a
day of being written:

```bash
python - <<'PY'
import pandas as pd, os
D = sorted(x for x in os.listdir("output") if x[:2]=="20" and os.path.isdir(f"output/{x}"))[-1]
d = pd.read_csv(f"output/{D}/stock_analysis.csv")
print(D, len(d), "rows")
for c in ("risk_reward","relative_volume","technical_score","macro_score","fno_score"):
    print(f"  {c:18s} n_unique={d[c].nunique():4d}  min={d[c].min()}  max={d[c].max()}")
for c in ("ema20","promoter_pledge","news_sentiment","pcr","supertrend","obv","cmf"):
    print(f"  {c:18s} non-null={d[c].notna().sum()}")
print("  pivot band % of price (median):",
      round(((d.resistance1-d.support1)/d.cmp*100).median(), 3))
PY
```

```
per idea:   capital_pct        <= 10.01
            risk_pct_of_capital <= 2.01
            rr_t1              >= 1.99
            3 <= hold_days_t1  <= 22   # ~1 month trading-day mandate
            stop_atr_mult      >= 1.0
            parkhu_score       >= 80
            expected_profit_pct_t1 == (t1-entry)/entry*100     (±0.02)
            risk_rupees        == qty*(entry-stop)             (±1)

per brief:  positions          <= 10
            every sector_exposure value <= 25.01
            every watchlist score in [70, 80)

resilience: missing stock_analysis.csv -> status "error", brief file still written
            malformed CSV              -> status "error", no exception
            zero capital               -> no divide-by-zero
            swing_brief never raises (collector resilience contract)
```

Also invariant, and easy to break by accident:

- **`swing_brief` runs last in `run.py`'s `DERIVED`** — it depends on `stock_analysis` and
  `market_summary`, and must precede `write_manifest` and `write_output_zips` so the brief
  is catalogued and packaged.
- **`collect.yml` stages `trades/` and `database/ohlc/`.** Without `trades/` the ledger
  resets every CI run and no position is ever followed up. Without `database/ohlc/` every
  run cold-starts a full Yahoo lookback. Staging `trades/` was missed once already.
- **Review runs before record.** Otherwise today's ideas are reviewed as zero-day-old
  positions and a re-suggested name duplicates instead of re-confirming.
- **Zero ideas is `status: ok`.** KB-00 requires stating that no recommendation should be
  made; treating it as an error would create pressure to lower the bar.

---

## 12. Extension points

**Adding a gate** — one line in `build_payload`; the funnel documents itself:

```python
gate("turnover >= 50 cr", lambda x: x["turnover_20d_avg_cr"] >= 50)
```

Put it in cost order so the funnel still reads as a narrowing story, and add the threshold
to `config/risk.py` rather than inlining it.

**Adding a score component** — populate the column, add the key to `comp` in
`build_scores`. Renormalisation is automatic and `weight_unavailable_pct` drops on its own.

**Changing a threshold** — `config/risk.py` only, with the KB citation or a CONFIG
DECISION note. Every constant is env-overridable, so sweep before you commit:

```bash
for v in 30 40 50; do PARKHU_MIN_DELIVERY_PCT=$v python -c \
  "from collector.brief import swing_brief; print($v, swing_brief.collect('2026-07-25'))"; done
```

**Adding a review action** — extend the `if/elif` chain in `positions.review` in SOP-3
order, and add the label to the table in `docs/swing-brief.md`. Anything that ends a
position must add its reason to `CLOSING`.

**Backfilling** — `PARKHU_RUN_DATE=2026-07-21 python run.py`, or regenerate a brief alone:

```python
from collector.brief import swing_brief; swing_brief.collect("2026-07-21")
```

Remember the ledger assumes chronological order; wipe `trades/` and replay the full
sequence rather than injecting a date into the middle.

---

## 13. The honest summary

What this system does well: it applies the KB's rules consistently, it refuses to produce
ideas when none qualify, it shows its working, and it now remembers what it said.

What it does not yet do: it cannot see a chart. No OHLC means no real support, no real
resistance, no breakout confirmation and no genuine reward-to-risk — the 1:2 floor is met
by definition rather than earned. It cannot check governance, because promoter pledge is
empty. Its regime read sits on an index series that chains correctly a fifth of the time.
It has produced briefs for a Saturday and a Sunday. And it has no measured track record
yet, so every "expected profit %" remains a projection.

Those are stated in every brief's caveats on purpose. The gap between what a number looks
like and what it is worth is where trading systems do their damage.

One last note for whoever extends this. Writing this document took about a day, and in
that time the collector fixed `relative_volume` and `technical_score` underneath it —
two of the defects it was written to explain. Both were caught only because every claim
was re-run against live data before publishing, and one of them turns out to unlock a gate
that is worth adding immediately. Assume the same has happened again by the time you read
this, and re-measure before you build on anything here.
