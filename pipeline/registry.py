"""Agent registry — collect / derive steps in execution order."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from collector.tradingview import tradingview
from collector.market import indices, sectors
from collector.smartmoney import smartmoney
from collector.options import options
from collector.derivatives import derivatives
from collector.corpactions import corpactions
from collector.news import news
from collector.macro import macro
from collector.delivery import delivery
from collector.derived import (
    relative_strength,
    event_risk,
    fno_momentum,
    swing_candidates,
    market_summary,
    stock_analysis,
)
from collector.brief import swing_brief


CollectFn = Callable[[str | None], dict[str, Any]]


@dataclass(frozen=True)
class AgentSpec:
    label: str
    collect: CollectFn
    kind: str  # "collector" | "derived"


# Broad price/valuation/technical coverage comes from TradingView (one call).
# Remaining collectors cover NSE-only signals plus index/sector/macro/news.
COLLECTORS: tuple[AgentSpec, ...] = (
    AgentSpec("tradingview", tradingview.collect, "collector"),
    AgentSpec("earnings", tradingview.collect_earnings, "collector"),
    AgentSpec("indices", indices.collect, "collector"),
    AgentSpec("sectors", sectors.collect, "collector"),
    AgentSpec("smartmoney", smartmoney.collect, "collector"),
    AgentSpec("options", options.collect, "collector"),
    AgentSpec("derivatives", derivatives.collect, "collector"),
    AgentSpec("delivery", delivery.collect, "collector"),
    AgentSpec("corpactions", corpactions.collect, "collector"),
    AgentSpec("news", news.collect, "collector"),
    AgentSpec("macro", macro.collect, "collector"),
)

# Order matters: stock_analysis consolidates prior CSVs; swing_brief is last.
DERIVED: tuple[AgentSpec, ...] = (
    AgentSpec("relative_strength", relative_strength.collect, "derived"),
    AgentSpec("event_risk", event_risk.collect, "derived"),
    AgentSpec("fno_momentum", fno_momentum.collect, "derived"),
    AgentSpec("swing_candidates", swing_candidates.collect, "derived"),
    AgentSpec("market_summary", market_summary.collect, "derived"),
    AgentSpec("stock_analysis", stock_analysis.collect, "derived"),
    AgentSpec("swing_brief", swing_brief.collect, "derived"),
)
