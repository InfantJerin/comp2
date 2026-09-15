"""Type system for the covenant DSL.

The types are deliberately coarse. They exist to catch the two mistakes that
actually happen when an LLM extracts a definition DAG:

  1. Comparing or summing a stock against a flow (``total_debt + capex``).
  2. Forgetting the trailing-period aggregation (``net_debt / ebitda`` where
     ``ebitda`` is a single quarter rather than LTM).

Anything finer than this buys precision nobody uses.
"""

from __future__ import annotations

from enum import Enum


class T(str, Enum):
    FLOW = "flow"        # period-scoped, summable across periods (net income, capex)
    LTM_FLOW = "ltm_flow"  # a flow already aggregated over a trailing window
    STOCK = "stock"      # point-in-time balance (total debt, cash)
    RATIO = "ratio"      # dimensionless (leverage, a percentage, a multiplier)
    BOOL = "bool"        # result of a comparator; gates springing tests
    COUNT = "count"      # integer-ish (cure uses, days)


MONEY = (T.FLOW, T.LTM_FLOW, T.STOCK)


class TypeError_(Exception):
    """Raised at ingest, never at quarter-end."""


def is_money(t: T) -> bool:
    return t in MONEY
