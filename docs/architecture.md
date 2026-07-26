# Parkhu Data Collector — Architecture & Coding Standards

This document is the Track-2 contract for the collector after Phase 0–2.
Trading rules in `config/risk.py` and swing gates are **out of scope** unless
a test proves a bug.

## Layers and dependency direction

```
run.py                  # thin CLI entrypoint
  └─ pipeline/          # orchestration only
       ├─ registry.py   # AgentSpec lists (collectors + derived)
       └─ runner.py     # collect → derive → watchlist → report → zip

brief/     → derived/ → collectors (I/O) → infra (utils, yf_history, github_models, publish)
config/    # settings, universe, risk, publish (shared config)
```

**Rules**

1. `brief` may import `derived` and `config`. It must not call NSE/Yahoo/TV directly.
2. `derived` may read CSVs via helpers and `config`. It must not own HTTP sessions
   except optional free-tier GitHub Models via `collector.infra.github_models`
   (`news_classify` only; ≤1 batched call/day; never paid billing / BYOK).
3. Collectors own I/O. They never import `brief` or `pipeline`.
4. No circular imports between `collector.*` packages.
5. `scripts/quality.py` / `quality.yml` stay ruff/vulture/jscpd — no Models.

## Agent contract

Every agent / derived step exposes:

```python
def collect(date: str | None = None) -> dict:
    ...
```

Return shape (required keys):

| Key | Type | Meaning |
|-----|------|---------|
| `agent` | str | Stable label |
| `status` | `"ok"` \| `"partial"` \| `"error"` | Health |
| `rows` | int | Rows written (0 on failure) |
| `error` | str (optional) | Human-readable failure |

**Never raise past the runner.** The runner catches `Exception`, records
`status=error`, and continues so one feed cannot abort the day.

## Schema contract

- Output column lists are named `COLUMNS` (or a typed schema constant).
- **No duplicate names** in `COLUMNS`.
- When building `pd.DataFrame(rows, columns=COLUMNS)`, every key written into
  `rows` that is meant to persist must appear in `COLUMNS` (Phase 0–2 bug class).
- Prefer `collector.schema.assert_unique_columns(COLUMNS)` at module import or
  in tests for wide tables like `stock_analysis`.

## Session policy

- `collection_date` — calendar day the cron/process ran (IST).
- `session_date` — trading day the numbers describe (`settings.session_date`).
- `is_trading_day` — weekday only today (no holiday calendar yet).
- Weekend runs may still write `output/<date>/` but must stamp the above and log a warning.

## Performance

- One TradingView scan per process (`tradingview._scan_rows` cache).
- Shared Yahoo bar cleaning via `collector.yf_history.clean_daily_history`.
- Derived steps read local CSVs; they do not re-scan the universe over HTTP.

## Security (CI)

- Workflow may commit `output/`, `logs/`, `trades/` as the data bot.
- Prefer path-scoped `git add` (already the case); never commit secrets or `.env`.
- Code changes should land via PR; data commits are automatic and separate.
- Branch protection on `main` for code is recommended; data bot pushes remain
  the intentional exception for generated artifacts.

## Retired modules

Yahoo per-symbol agents superseded by TradingView live under
`collector/_retired/`. Do not re-wire them into `pipeline.registry` without a
documented need.

## Quality scanners

```bash
pip install -r requirements-dev.txt
python -m scripts.quality          # ruff + vulture + jscpd
python -m scripts.quality --fast   # ruff + vulture only
```

| Tool | Catches |
|------|---------|
| **ruff** | lint, unused imports, bug patterns, format drift |
| **vulture** | dead / unused Python symbols |
| **jscpd** | copy-pasted blocks (duplication %) |

CI: `.github/workflows/quality.yml` on push/PR. Daily collect workflow still runs
`pytest` before `run.py`.
