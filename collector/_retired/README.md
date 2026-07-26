# Retired collectors

These modules are **not** wired into `pipeline.registry`. They were superseded
by the TradingView one-shot scan (price, fundamentals, technicals, earnings)
or by later NSE agents.

| Path | Former role | Replaced by |
|------|-------------|-------------|
| `fundamentals/` | Per-symbol Yahoo fundamentals | `tradingview.csv` |
| `technical/` | Per-symbol pandas-ta indicators | `tradingview.csv` / `stock_analysis.csv` |
| `earnings/` | Per-symbol Yahoo earnings | `tradingview.collect_earnings` |
| `ownership/` | NSE shareholding / pledge | Phase 3+ (gap); not in daily run |
| `market_yahoo.py` | Per-symbol Yahoo prices | `tradingview.csv` |

Do not re-enable without updating `docs/architecture.md` and adding tests.
