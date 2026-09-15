"""The DSL: node kinds, the operator algebra, and the static typechecker.

A credit agreement's extracted definitions are a *program* in this language;
the interpreter in ``interpreter.py`` is its only implementation. The language
is deliberately non-Turing-complete -- no loops, no recursion, no user-defined
functions -- so that every program provably terminates, can be typechecked at
ingest, and can have its input dependencies enumerated statically.

Pressure to add recursion will arrive with the first weird agreement. That is
what ``judgment`` nodes are for.
"""

from __future__ import annotations

from typing import Any

from .types import T, TypeError_, is_money
from .vocabulary import symbol_type

Node = dict[str, Any]

ARITHMETIC = {"add", "subtract", "multiply", "divide"}
SELECTORS = {"greater_of", "lesser_of"}
BOUNDS = {"cap", "floor"}
COMPARATORS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "=="}
LOGICAL = {"all_of", "any_of", "negate"}
LEAVES = {"const", "input", "ref", "judgment", "schedule"}

OPERATORS = (
    LEAVES | ARITHMETIC | SELECTORS | BOUNDS | set(COMPARATORS) | LOGICAL | {"ltm", "if"}
)


class SchemaError(Exception):
    """Malformed AST. Raised at ingest, never at quarter-end."""


def _kind(node: Node) -> str:
    if not isinstance(node, dict):
        raise SchemaError(f"expected a node object, got {type(node).__name__}: {node!r}")
    kind = node.get("op")
    if kind is None:
        raise SchemaError(f"node is missing 'op': {node!r}")
    if kind not in OPERATORS:
        raise SchemaError(
            f"unknown operator '{kind}'. Extraction may only emit operators the "
            f"interpreter understands; if a clause does not fit, emit a judgment "
            f"node explaining why."
        )
    return kind


def _declared(node: Node) -> T:
    raw = node.get("type")
    if raw is None:
        raise SchemaError(f"{node['op']} node must declare a 'type': {node!r}")
    try:
        return T(raw)
    except ValueError:
        raise SchemaError(f"unknown type '{raw}' on node {node!r}") from None


def _args(node: Node, key: str = "args", minimum: int = 2) -> list[Node]:
    args = node.get(key)
    if not isinstance(args, list) or len(args) < minimum:
        raise SchemaError(
            f"{node['op']} requires '{key}' to be a list of at least {minimum} nodes"
        )
    return args


def _child(node: Node, key: str) -> Node:
    if key not in node:
        raise SchemaError(f"{node['op']} node is missing '{key}': {node!r}")
    return node[key]


def _same(types: list[T], node: Node) -> T:
    if len(set(types)) != 1:
        raise TypeError_(
            f"{node['op']} requires operands of one type, got "
            f"{[t.value for t in types]}. A stock and a flow are not addable; if "
            f"you meant a trailing aggregate, wrap the flow in ltm()."
        )
    return types[0]


def typecheck(node: Node, defs: dict[str, Node], _stack: tuple[str, ...] = ()) -> T:
    """Return the type of ``node``, raising on any malformed or ill-typed tree."""
    kind = _kind(node)

    if kind == "const":
        if not isinstance(node.get("value"), (int, float)):
            raise SchemaError(f"const needs a numeric 'value': {node!r}")
        return _declared(node)

    if kind == "input":
        symbol = node.get("symbol")
        if not isinstance(symbol, str):
            raise SchemaError(f"input needs a 'symbol': {node!r}")
        return symbol_type(symbol)

    if kind == "judgment":
        if not node.get("name"):
            raise SchemaError(f"judgment needs a stable 'name': {node!r}")
        if not node.get("prompt"):
            raise SchemaError(
                f"judgment '{node.get('name')}' needs a 'prompt' telling the human "
                f"what they are being asked to determine"
            )
        return _declared(node)

    if kind == "schedule":
        entries = node.get("entries")
        if not isinstance(entries, list) or not entries:
            raise SchemaError(f"schedule needs a non-empty 'entries' list: {node!r}")
        for entry in entries:
            if "value" not in entry or "from" not in entry:
                raise SchemaError(f"schedule entry needs 'from' and 'value': {entry!r}")
        return _declared(node)

    if kind == "ref":
        name = node.get("name")
        if name not in defs:
            raise SchemaError(f"ref to undefined term '{name}'")
        if name in _stack:
            raise SchemaError(
                f"definition cycle: {' -> '.join((*_stack, name))}. The DSL has no "
                f"recursion by design."
            )
        return typecheck(defs[name], defs, (*_stack, name))

    if kind in {"add", "subtract"}:
        types = [typecheck(a, defs, _stack) for a in _args(node)]
        t = _same(types, node)
        if t is T.BOOL:
            raise TypeError_(f"cannot {kind} booleans")
        return t

    if kind == "multiply":
        types = [typecheck(a, defs, _stack) for a in _args(node)]
        moneys = [t for t in types if is_money(t)]
        if len(moneys) > 1:
            raise TypeError_("multiplying two money values yields a meaningless unit")
        if not all(is_money(t) or t is T.RATIO for t in types):
            raise TypeError_(f"multiply operands must be money or ratio, got {types}")
        return moneys[0] if moneys else T.RATIO

    if kind == "divide":
        num = typecheck(_child(node, "numerator"), defs, _stack)
        den = typecheck(_child(node, "denominator"), defs, _stack)
        if is_money(num) and is_money(den):
            # A balance over a single period's flow is the missing-ltm() bug:
            # net debt / one quarter of EBITDA quadruples reported leverage.
            # Mixing a raw flow with a trailing one compares unlike windows.
            pair = {num, den}
            if pair == {T.STOCK, T.FLOW}:
                raise TypeError_(
                    "dividing a stock by a single-period flow. A leverage or "
                    "coverage ratio measures a balance against a trailing "
                    "aggregate -- wrap the flow in ltm()."
                )
            if pair == {T.FLOW, T.LTM_FLOW}:
                raise TypeError_(
                    "dividing a single-period flow by a trailing one (or vice "
                    "versa): the two sides cover different windows."
                )
            return T.RATIO
        if is_money(num) and den is T.RATIO:
            return num
        if num is T.RATIO and den is T.RATIO:
            return T.RATIO
        raise TypeError_(f"cannot divide {num.value} by {den.value}")

    if kind == "ltm":
        inner = typecheck(_child(node, "of"), defs, _stack)
        if inner is T.STOCK:
            raise TypeError_(
                "ltm() of a stock: a balance is point-in-time and cannot be trailed. "
                "Net debt is measured at the test date, not summed over four quarters."
            )
        if inner is T.LTM_FLOW:
            raise TypeError_("ltm() applied twice to the same flow")
        if inner is not T.FLOW:
            raise TypeError_(f"ltm() requires a flow, got {inner.value}")
        return T.LTM_FLOW

    if kind in BOUNDS:
        of = typecheck(_child(node, "of"), defs, _stack)
        limit = typecheck(_child(node, "limit"), defs, _stack)
        return _same([of, limit], node)

    if kind in SELECTORS:
        return _same([typecheck(a, defs, _stack) for a in _args(node)], node)

    if kind in COMPARATORS:
        left = typecheck(_child(node, "left"), defs, _stack)
        right = typecheck(_child(node, "right"), defs, _stack)
        if is_money(left) and is_money(right):
            return T.BOOL
        if left is right:
            return T.BOOL
        raise TypeError_(f"cannot compare {left.value} with {right.value}")

    if kind in {"all_of", "any_of"}:
        types = [typecheck(a, defs, _stack) for a in _args(node)]
        if any(t is not T.BOOL for t in types):
            raise TypeError_(f"{kind} requires boolean operands")
        return T.BOOL

    if kind == "negate":
        if typecheck(_child(node, "of"), defs, _stack) is not T.BOOL:
            raise TypeError_("negate requires a boolean operand")
        return T.BOOL

    if kind == "if":
        if typecheck(_child(node, "condition"), defs, _stack) is not T.BOOL:
            raise TypeError_("if() condition must be boolean")
        then = typecheck(_child(node, "then"), defs, _stack)
        otherwise = typecheck(_child(node, "otherwise"), defs, _stack)
        return _same([then, otherwise], node)

    raise SchemaError(f"unhandled operator '{kind}'")


def dependencies(node: Node, defs: dict[str, Node]) -> dict[str, set[str]]:
    """Statically enumerate what a program needs before it can be evaluated.

    Returns ``{"inputs": ..., "judgments": ...}``. This is what the tracker uses
    to build the document-chase list for a borrower *before* the period closes,
    rather than discovering the gap at quarter-end.
    """
    inputs: set[str] = set()
    judgments: set[str] = set()
    seen: set[str] = set()

    def walk(n: Node) -> None:
        kind = _kind(n)
        if kind == "input":
            inputs.add(n["symbol"])
        elif kind == "judgment":
            judgments.add(n["name"])
        elif kind == "ref":
            if n["name"] not in seen:
                seen.add(n["name"])
                walk(defs[n["name"]])
        for key in ("of", "limit", "numerator", "denominator", "condition", "then", "otherwise"):
            if key in n:
                walk(n[key])
        for child in n.get("args", []):
            walk(child)

    walk(node)
    return {"inputs": inputs, "judgments": judgments}
