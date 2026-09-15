"""The interpreter: agreement-agnostic, deterministic, and the only thing here
that ever executes.

Two properties are load-bearing.

*It returns the evaluated tree, not a number.* Pass/fail and headroom fall out
of the root, but the trace is what a banker argues about ("why is your EBITDA
different from the borrower's?") and what lets you diff two evaluations when a
fact is restated or a definition is corrected.

*It refuses rather than guesses.* A missing line item or an unfilled judgment
node yields INDETERMINATE with the gap named. Indeterminate is not a degraded
pass -- operationally it is the most important state, because it drives the
chase-the-borrower workflow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

from .dsl import COMPARATORS, Node, dependencies, typecheck
from .facts import Facts

DEFAULT_LTM_PERIODS = 4


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"      # an input or judgment is missing
    NOT_APPLICABLE = "not_applicable"    # a springing test that did not spring


@dataclass(frozen=True)
class Gap:
    """Something the evaluation needed and did not have."""

    kind: str          # input | judgment | schedule | period
    name: str
    reason: str

    def __str__(self) -> str:
        return f"{self.kind}:{self.name} ({self.reason})"


@dataclass
class _Ctx:
    facts: Facts
    defs: dict[str, Node]
    index: int
    gaps: list[Gap] = field(default_factory=list)

    def at(self, index: int) -> "_Ctx":
        return _Ctx(self.facts, self.defs, index, self.gaps)

    def gap(self, kind: str, name: str, reason: str) -> None:
        """Record a missing input once. The same line item is consumed by every
        leg of a trailing window and by several covenants; the chase list wants
        one entry per genuinely distinct gap."""
        entry = Gap(kind, name, reason)
        if entry not in self.gaps:
            self.gaps.append(entry)


def _money(x: float) -> str:
    """Ratios read as multiples; balances read as figures, never as 6.5e+07."""
    return f"{x:,.0f}" if abs(x) >= 1_000 else f"{x:.4g}"


def _trace(node: Node, value: Any, **extra: Any) -> dict:
    out = {"op": node["op"], "value": value}
    if "clause" in node:
        out["clause"] = node["clause"]
    out.update(extra)
    return out


def _eval(node: Node, ctx: _Ctx) -> tuple[Any, dict]:
    op = node["op"]

    if op == "const":
        return node["value"], _trace(node, node["value"])

    if op == "input":
        symbol = node["symbol"]
        from .vocabulary import symbol_type
        from .types import T

        if symbol_type(symbol) is T.STOCK:
            value = ctx.facts.stock(symbol)
            where = f"as at {ctx.facts.test_date}"
        else:
            value = ctx.facts.flow(symbol, ctx.index)
            if 0 <= ctx.index < len(ctx.facts.periods):
                where = f"period ending {ctx.facts.periods[ctx.index].end}"
            else:
                where = "period out of range"
        if value is None:
            ctx.gap("input", symbol, f"not reported for {where}")
        return value, _trace(node, value, symbol=symbol, basis=where)

    if op == "judgment":
        name = node["name"]
        value = ctx.facts.judgments.get(name)
        if value is None:
            ctx.gap("judgment", name, node["prompt"])
        return value, _trace(node, value, name=name, prompt=node["prompt"])

    if op == "ref":
        value, inner = _eval(ctx.defs[node["name"]], ctx)
        return value, _trace(node, value, name=node["name"], definition=inner)

    if op == "schedule":
        match = None
        for entry in node["entries"]:
            start = date.fromisoformat(entry["from"])
            end = date.fromisoformat(entry["to"]) if entry.get("to") else None
            if start <= ctx.facts.test_date and (end is None or ctx.facts.test_date <= end):
                match = entry
                break
        if match is None:
            ctx.gap("schedule", node.get("name", "schedule"),
                    f"no entry covers test date {ctx.facts.test_date}")
            return None, _trace(node, None)
        return match["value"], _trace(node, match["value"], effective_from=match["from"])

    if op == "ltm":
        window = node.get("periods", DEFAULT_LTM_PERIODS)
        total: float | None = 0.0
        legs = []
        for offset in range(window):
            index = ctx.index - offset
            if index < 0:
                ctx.gap("period", f"t-{offset}",
                        f"only {len(ctx.facts.periods)} periods available, "
                        f"{window} needed for the trailing window")
                total = None
                legs.append({"offset": offset, "value": None})
                continue
            value, leg = _eval(node["of"], ctx.at(index))
            legs.append({"offset": offset, "period_end": str(ctx.facts.periods[index].end), **leg})
            if value is None or total is None:
                total = None
            else:
                total += value
        return total, _trace(node, total, window=window, legs=legs)

    # --- n-ary and binary operators below: evaluate children, then combine ---

    def children(key: str = "args") -> tuple[list[Any], list[dict]]:
        values, traces = [], []
        for child in node[key]:
            value, trace = _eval(child, ctx)
            values.append(value)
            traces.append(trace)
        return values, traces

    def binary(a: str, b: str) -> tuple[Any, Any, dict, dict]:
        va, ta = _eval(node[a], ctx)
        vb, tb = _eval(node[b], ctx)
        return va, vb, ta, tb

    if op in {"add", "subtract", "multiply", "greater_of", "lesser_of", "all_of", "any_of"}:
        values, traces = children()
        if any(v is None for v in values):
            return None, _trace(node, None, args=traces)
        result: Any
        if op == "add":
            result = sum(values)
        elif op == "subtract":
            result = values[0]
            for v in values[1:]:
                result -= v
        elif op == "multiply":
            result = 1.0
            for v in values:
                result *= v
        elif op == "greater_of":
            result = max(values)
        elif op == "lesser_of":
            result = min(values)
        elif op == "all_of":
            result = all(values)
        else:
            result = any(values)
        return result, _trace(node, result, args=traces)

    if op == "divide":
        num, den, tn, td = binary("numerator", "denominator")
        if num is None or den is None:
            return None, _trace(node, None, numerator=tn, denominator=td)
        if den == 0:
            ctx.gap("input", "denominator", "division by zero")
            return None, _trace(node, None, numerator=tn, denominator=td)
        return num / den, _trace(node, num / den, numerator=tn, denominator=td)

    if op in {"cap", "floor"}:
        of, limit, to, tl = binary("of", "limit")
        if of is None or limit is None:
            return None, _trace(node, None, of=to, limit=tl)
        result = min(of, limit) if op == "cap" else max(of, limit)
        return result, _trace(node, result, of=to, limit=tl, binding=(result != of))

    if op in COMPARATORS:
        left, right, tl, tr = binary("left", "right")
        if left is None or right is None:
            return None, _trace(node, None, left=tl, right=tr)
        symbol = COMPARATORS[op]
        result = {
            ">": left > right, ">=": left >= right,
            "<": left < right, "<=": left <= right, "==": left == right,
        }[symbol]
        return result, _trace(node, result, comparator=symbol, left=tl, right=tr)

    if op == "negate":
        value, trace = _eval(node["of"], ctx)
        result = None if value is None else (not value)
        return result, _trace(node, result, of=trace)

    if op == "if":
        cond, tc = _eval(node["condition"], ctx)
        if cond is None:
            return None, _trace(node, None, condition=tc)
        branch = "then" if cond else "otherwise"
        value, tb = _eval(node[branch], ctx)
        return value, _trace(node, value, condition=tc, taken=branch, branch=tb)

    raise AssertionError(f"interpreter has no case for '{op}' -- typecheck should have caught this")


def evaluate(expr: Node, defs: dict[str, Node], facts: Facts) -> tuple[Any, dict, list[Gap]]:
    """Evaluate a bare expression. Returns (value, trace, gaps)."""
    index = facts.current_index()
    if index is None:
        gap = Gap("period", "current", f"no period ends on or before {facts.test_date}")
        return None, {"op": expr.get("op"), "value": None}, [gap]
    ctx = _Ctx(facts, defs, index)
    value, trace = _eval(expr, ctx)
    return value, trace, ctx.gaps


@dataclass
class CovenantResult:
    covenant_id: str
    name: str
    test_date: date
    status: Status
    actual: float | None = None
    threshold: float | None = None
    comparator: str | None = None
    headroom_pct: float | None = None
    gaps: list[Gap] = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    @property
    def breached(self) -> bool:
        return self.status is Status.FAIL

    def summary(self) -> str:
        if self.status is Status.NOT_APPLICABLE:
            return f"{self.name}: not applicable at {self.test_date}"
        if self.status is Status.INDETERMINATE:
            missing = ", ".join(str(g) for g in self.gaps)
            return f"{self.name}: INDETERMINATE -- missing {missing}"
        head = f" (headroom {self.headroom_pct:+.1%})" if self.headroom_pct is not None else ""
        return (
            f"{self.name}: {self.status.value.upper()} -- "
            f"{_money(self.actual)} {self.comparator} {_money(self.threshold)}{head}"
        )


def evaluate_covenant(covenant: dict, defs: dict[str, Node], facts: Facts) -> CovenantResult:
    """Bind one covenant test spec to a facts snapshot at a test date."""
    index = facts.current_index()
    result = CovenantResult(
        covenant_id=covenant["id"], name=covenant["name"],
        test_date=facts.test_date, status=Status.INDETERMINATE,
        comparator=COMPARATORS[covenant["comparator"]],
    )
    if index is None:
        result.gaps = [Gap("period", "current", f"no period ends on or before {facts.test_date}")]
        return result

    ctx = _Ctx(facts, defs, index)
    trace: dict = {}

    # Springing covenants: the test only exists when its trigger is met.
    if covenant.get("applicability") is not None:
        applicable, applicability_trace = _eval(covenant["applicability"], ctx)
        trace["applicability"] = applicability_trace
        if applicable is None:
            result.gaps, result.trace = ctx.gaps, trace
            return result
        if not applicable:
            result.status, result.trace = Status.NOT_APPLICABLE, trace
            return result

    actual, trace["metric"] = _eval(covenant["metric"], ctx)
    threshold, trace["threshold"] = _eval(covenant["threshold"], ctx)
    result.actual, result.threshold, result.trace, result.gaps = actual, threshold, trace, ctx.gaps

    if actual is None or threshold is None:
        return result

    symbol = result.comparator
    passed = {
        ">": actual > threshold, ">=": actual >= threshold,
        "<": actual < threshold, "<=": actual <= threshold, "==": actual == threshold,
    }[symbol]
    result.status = Status.PASS if passed else Status.FAIL

    # Signed slack against the limit: positive is compliant, negative is a breach.
    # This is the early-warning number; the binary is the audit number.
    if threshold != 0:
        slack = (threshold - actual) if symbol in {"<", "<="} else (actual - threshold)
        result.headroom_pct = slack / abs(threshold)
    return result


def required_inputs(covenant: dict, defs: dict[str, Node]) -> dict[str, set[str]]:
    """What this covenant will need at the next test, known before the period closes."""
    combined: dict[str, set[str]] = {"inputs": set(), "judgments": set()}
    for key in ("metric", "threshold", "applicability"):
        if covenant.get(key) is not None:
            for bucket, names in dependencies(covenant[key], defs).items():
                combined[bucket] |= names
    return combined


def validate_program(defs: dict[str, Node], covenants: list[dict]) -> None:
    """Typecheck every definition and covenant. Call at ingest; a malformed DAG
    must fail here, not at quarter-end."""
    from .types import T, TypeError_

    for name, node in defs.items():
        try:
            typecheck(node, defs)
        except (TypeError_, Exception) as exc:
            raise type(exc)(f"definition '{name}': {exc}") from None

    for covenant in covenants:
        cid = covenant.get("id", "<no id>")
        if covenant["comparator"] not in COMPARATORS:
            raise ValueError(f"covenant '{cid}': unknown comparator {covenant['comparator']!r}")
        metric_type = typecheck(covenant["metric"], defs)
        threshold_type = typecheck(covenant["threshold"], defs)
        if metric_type is not threshold_type and not (
            metric_type.value.endswith("flow") and threshold_type.value.endswith("flow")
        ):
            raise TypeError_(
                f"covenant '{cid}': comparing {metric_type.value} metric against "
                f"{threshold_type.value} threshold"
            )
        if covenant.get("applicability") is not None:
            if typecheck(covenant["applicability"], defs) is not T.BOOL:
                raise TypeError_(f"covenant '{cid}': applicability must be boolean")
