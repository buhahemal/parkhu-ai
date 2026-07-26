# Kill criterion (Step 7)

Pre-committed **pause for review** bar for the live suggestion ledger.
Set before results so a cold streak cannot be rationalized away in real time.

## Bar (defaults)

| Rule | Env | Default |
|------|-----|---------|
| Minimum closed suggestions before the bar applies | `PARKHU_KILL_MIN_CLOSED` | 20 |
| Pause if win rate &lt; this % | `PARKHU_KILL_MIN_WIN_RATE_PCT` | 40 |
| Pause if average return &lt; this % | `PARKHU_KILL_MIN_AVG_RETURN_PCT` | 0 |

Logic (OR): after `closed ≥ min_closed`, pause if **win rate** or **avg return** breaches the floor.

Implemented in [`research/kill_criterion.py`](../research/kill_criterion.py) from
`positions.realised_stats()`. Surfaced as `analytics.kill_status` in `research_pack.json`
and as a **Kill** pill on the desk status ribbon.

## What pause means

- Stop **new** risk / ideas until a deliberate review.
- Existing open suggestions still follow the ledger review loop.
- Do **not** loosen gates mid-drawdown to “make the sample look better.”

## What it is not

- Not a guarantee of edge (Epic A–B may still show no OOS edge).
- Not a reason to change live funnel honesty before ablation / expectancy evidence.
- Below `min_closed`, status is `insufficient_sample` — treat the ledger as a log only.
