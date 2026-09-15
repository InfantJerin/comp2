"""The facts snapshot: line-item values for a borrower, bound to a test date.

A DAG alone is a spec. It becomes computable only when bound to facts at a
date -- which is what lets the same program run against many periods, and many
programs run against one compliance certificate.

Flows are held per fiscal period so that ``ltm`` is a real trailing aggregate
rather than an annualisation fudge. Stocks are point-in-time as at the test
date.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Period:
    """One fiscal period's flow values, plus where they came from."""

    end: date
    flows: dict[str, float]
    source_document_id: str | None = None


@dataclass
class Facts:
    test_date: date
    periods: list[Period]                      # chronological, oldest first
    stocks: dict[str, float] = field(default_factory=dict)
    judgments: dict[str, float] = field(default_factory=dict)
    entity: str = ""
    source_document_id: str | None = None

    def __post_init__(self) -> None:
        self.periods = sorted(self.periods, key=lambda p: p.end)

    def current_index(self) -> int | None:
        """Index of the most recent period ending on or before the test date."""
        eligible = [i for i, p in enumerate(self.periods) if p.end <= self.test_date]
        return eligible[-1] if eligible else None

    def flow(self, symbol: str, index: int) -> float | None:
        if index < 0 or index >= len(self.periods):
            return None
        return self.periods[index].flows.get(symbol)

    def stock(self, symbol: str) -> float | None:
        return self.stocks.get(symbol)


def facts_from_dict(raw: dict) -> Facts:
    """Build a snapshot from a compliance-certificate-shaped payload."""
    return Facts(
        test_date=date.fromisoformat(raw["test_date"]),
        periods=[
            Period(
                end=date.fromisoformat(p["end"]),
                flows=dict(p.get("flows", {})),
                source_document_id=p.get("source_document_id"),
            )
            for p in raw.get("periods", [])
        ],
        stocks=dict(raw.get("stocks", {})),
        judgments=dict(raw.get("judgments", {})),
        entity=raw.get("entity", ""),
        source_document_id=raw.get("source_document_id"),
    )
