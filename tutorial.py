"""A guided tour: build up an extracted credit agreement one concept at a time.

Run me:   python3 tutorial.py

Read this file top to bottom alongside the output. Each STEP introduces exactly
one new idea. The borrower is Bluebird Manufacturing Inc, with a $50m revolver
and a $60m term loan.
"""

from datetime import date

from covenants import Facts, Period, evaluate, evaluate_covenant, load_program
from covenants.dsl import dependencies, typecheck
from covenants.interpreter import validate_program
from covenants.types import TypeError_


def banner(n, title):
    print(f"\n{'=' * 72}\nSTEP {n}  {title}\n{'=' * 72}")


# ---------------------------------------------------------------------------
# The facts. In production these come from a parsed compliance certificate.
# Flows are per fiscal quarter; stocks are balances as at the test date.
# ---------------------------------------------------------------------------

QUARTER = {
    "net_income": 2_000_000,
    "interest_expense": 1_500_000,
    "cash_interest_expense": 1_400_000,
    "tax_expense": 600_000,
    "depreciation_amortization": 1_400_000,
    "restructuring_charges": 800_000,
    "run_rate_synergies": 1_200_000,
    "non_recurring_charges": 0,
    "scheduled_principal_payments": 750_000,
    "dividends_paid": 0,
    "maintenance_capex": 900_000,
}

FACTS = Facts(
    entity="Bluebird Manufacturing Inc",
    test_date=date(2027, 12, 31),
    periods=[
        Period(end=date(2027, 3, 31), flows=dict(QUARTER), source_document_id="cc_q1"),
        Period(end=date(2027, 6, 30), flows=dict(QUARTER), source_document_id="cc_q2"),
        Period(end=date(2027, 9, 30), flows=dict(QUARTER), source_document_id="cc_q3"),
        Period(end=date(2027, 12, 31), flows=dict(QUARTER), source_document_id="cc_q4"),
    ],
    stocks={
        "total_debt": 60_000_000,
        "capital_lease_obligations": 0,
        "unrestricted_cash": 30_000_000,
        "revolver_commitment": 50_000_000,
        "revolver_drawn": 15_000_000,
        "letters_of_credit_outstanding": 0,
    },
    judgments={},
)


# ---------------------------------------------------------------------------
banner(1, "The smallest possible covenant: Minimum Liquidity >= $25,000,000")
# ---------------------------------------------------------------------------
# Clause: "Liquidity, being unrestricted cash plus undrawn revolver
#          availability, shall not be less than $25,000,000 at any test date."
#
# Every node is an {"op": ...} object. Leaves are "input" (a symbol from the
# vocabulary) or "const". No LTM here: liquidity is a point-in-time measure,
# so everything involved is a STOCK.

liquidity = {
    "op": "add",
    "clause": {"section": "7.12", "page": 88},
    "args": [
        {"op": "input", "symbol": "unrestricted_cash"},
        {"op": "subtract", "args": [
            {"op": "input", "symbol": "revolver_commitment"},
            {"op": "input", "symbol": "revolver_drawn"},
        ]},
    ],
}

min_liquidity = {
    "id": "cov_min_liquidity",
    "name": "Minimum Liquidity",
    "metric": {"op": "ref", "name": "liquidity"},
    "comparator": "gte",
    "threshold": {"op": "const", "value": 25_000_000, "type": "stock"},
}

defs = {"liquidity": liquidity}
validate_program(defs, [min_liquidity])          # typechecks; raises if wrong
print(evaluate_covenant(min_liquidity, defs, FACTS).summary())
print("   = $30m cash + ($50m commitment - $15m drawn)")


# ---------------------------------------------------------------------------
banner(2, "A computed ratio, and why ltm() is needed")
# ---------------------------------------------------------------------------
# Clause: "Interest Coverage Ratio = Consolidated EBITDA to Interest Expense,
#          in each case for the Test Period of four consecutive fiscal
#          quarters, shall not be less than 2.50:1.00."
#
# EBITDA and interest are FLOWS. The clause says four quarters, so both get
# wrapped in ltm(). Note what ltm() wraps: an *expression*, not just an input.

defs["ebitda_quarterly"] = {
    "op": "add",
    "clause": {"section": "1.01 'Consolidated EBITDA'", "page": 14},
    "args": [
        {"op": "input", "symbol": "net_income"},
        {"op": "input", "symbol": "interest_expense"},
        {"op": "input", "symbol": "tax_expense"},
        {"op": "input", "symbol": "depreciation_amortization"},
    ],
}
defs["ltm_ebitda"] = {"op": "ltm", "of": {"op": "ref", "name": "ebitda_quarterly"}}
defs["ltm_interest"] = {"op": "ltm", "of": {"op": "input", "symbol": "interest_expense"}}
defs["interest_coverage"] = {
    "op": "divide",
    "numerator": {"op": "ref", "name": "ltm_ebitda"},
    "denominator": {"op": "ref", "name": "ltm_interest"},
}

icr = {
    "id": "cov_icr", "name": "Minimum Interest Coverage Ratio",
    "metric": {"op": "ref", "name": "interest_coverage"},
    "comparator": "gte",
    "threshold": {"op": "const", "value": 2.50, "type": "ratio"},
}
validate_program(defs, [icr])
print(evaluate_covenant(icr, defs, FACTS).summary())

# evaluate() runs any bare expression, which is how you inspect intermediates.
for name in ("ebitda_quarterly", "ltm_ebitda", "ltm_interest"):
    value, _, _ = evaluate({"op": "ref", "name": name}, defs, FACTS)
    print(f"   {name:<20} {value:>12,.0f}")
print("   ltm_ebitda is 4 x ebitda_quarterly -- the trailing window, not an annualisation")


# ---------------------------------------------------------------------------
banner(3, "cap(): the cash-netting limit, and how it changes the answer")
# ---------------------------------------------------------------------------
# Clause: "Consolidated Net Debt means Total Debt less unrestricted cash,
#          provided that not more than $10,000,000 of cash may be netted."
#
# cap(of, limit) = min. floor(of, limit) = max. Both operands must be the same
# type, which is why the const declares "stock".

defs["netted_cash"] = {
    "op": "cap",
    "clause": {"section": "1.01 'Consolidated Net Debt' proviso", "page": 19},
    "of": {"op": "input", "symbol": "unrestricted_cash"},
    "limit": {"op": "const", "value": 10_000_000, "type": "stock"},
}
defs["net_debt"] = {
    "op": "subtract",
    "args": [
        {"op": "input", "symbol": "total_debt"},
        {"op": "ref", "name": "netted_cash"},
    ],
}
defs["net_leverage"] = {
    "op": "divide",
    "numerator": {"op": "ref", "name": "net_debt"},
    "denominator": {"op": "ref", "name": "ltm_ebitda"},
}

cash, _, _ = evaluate({"op": "input", "symbol": "unrestricted_cash"}, defs, FACTS)
netted, trace, _ = evaluate({"op": "ref", "name": "netted_cash"}, defs, FACTS)
debt, _, _ = evaluate({"op": "ref", "name": "net_debt"}, defs, FACTS)
print(f"   cash on hand        {cash:>12,.0f}")
print(f"   netting cap         {10_000_000:>12,.0f}   binding: {trace['definition']['binding']}")
print(f"   cash actually netted{netted:>12,.0f}")
print(f"   net debt            {debt:>12,.0f}   (not $30m -- $20m of cash is stranded)")


# ---------------------------------------------------------------------------
banner(4, "schedule(): a step-down threshold is data, not code")
# ---------------------------------------------------------------------------
# Clause 7.11(a) table:
#     through FY2027      3.75x
#     FY2028              3.25x
#     FY2029 and after    3.00x
#
# The schedule is looked up on the *test date*, so the same program gives a
# different threshold each year without any code change.

leverage = {
    "id": "cov_leverage", "name": "Maximum Net Leverage Ratio",
    "metric": {"op": "ref", "name": "net_leverage"},
    "comparator": "lte",
    "threshold": {
        "op": "schedule", "name": "leverage_step_down", "type": "ratio",
        "clause": {"section": "7.11(a) table", "page": 91},
        "entries": [
            {"from": "2026-01-01", "to": "2027-12-31", "value": 3.75},
            {"from": "2028-01-01", "to": "2028-12-31", "value": 3.25},
            {"from": "2029-01-01", "to": None,         "value": 3.00},
        ],
    },
}
validate_program(defs, [leverage])

import copy
for year in (2027, 2028, 2029):
    shifted = copy.deepcopy(FACTS)
    shifted.test_date = date(year, 12, 31)
    shifted.periods = [Period(end=date(year, p.end.month, p.end.day), flows=p.flows)
                       for p in FACTS.periods]
    print("  ", evaluate_covenant(leverage, defs, shifted).summary())
print("   same performance every year; the covenant tightens underneath it")


# ---------------------------------------------------------------------------
banner(5, "judgment(): the clause extraction must not pretend to resolve")
# ---------------------------------------------------------------------------
# Clause: "...plus, without duplication, such other non-recurring items as the
#          Borrower shall determine in good faith, provided that all add-backs
#          under clauses (iv)-(vii) shall not exceed 15% of Consolidated EBITDA
#          before giving effect thereto."
#
# "as the Borrower shall determine in good faith" is not extractable. It
# becomes a judgment node: a named hole a human must fill. The interpreter
# refuses to produce a number until it is filled -- but the 15% cap around it
# is still enforced by the model.

defs["addbacks_quarterly"] = {
    "op": "add",
    "args": [
        {"op": "input", "symbol": "restructuring_charges"},
        {"op": "input", "symbol": "run_rate_synergies"},
        {"op": "judgment", "name": "good_faith_items", "type": "flow",
         "prompt": "Clause 1.01(b)(vii): amount the Borrower has determined in good "
                   "faith to be non-recurring for this quarter. Enter 0 if none.",
         "clause": {"section": "1.01(b)(vii)", "page": 15}},
    ],
}
defs["adjusted_ebitda"] = {
    "op": "add",
    "args": [
        {"op": "ref", "name": "ltm_ebitda"},
        {"op": "cap",
         "of": {"op": "ltm", "of": {"op": "ref", "name": "addbacks_quarterly"}},
         "limit": {"op": "multiply", "args": [
             {"op": "ref", "name": "ltm_ebitda"},
             {"op": "const", "value": 0.15, "type": "ratio"}]}},
    ],
}

value, _, gaps = evaluate({"op": "ref", "name": "adjusted_ebitda"}, defs, FACTS)
print(f"   unfilled -> value is {value}, and the tracker is told exactly what to ask for:")
for gap in gaps:
    print(f"     {gap.kind}: {gap.name}\n       \"{gap.reason}\"")

FACTS.judgments["good_faith_items"] = 300_000
value, trace, gaps = evaluate({"op": "ref", "name": "adjusted_ebitda"}, defs, FACTS)
capped = trace["definition"]["args"][1]
print(f"\n   filled with $300k/quarter ->")
print(f"     add-backs claimed (LTM)  {capped['of']['value']:>12,.0f}")
print(f"     15% cap                  {capped['limit']['value']:>12,.0f}"
      f"   binding: {capped['binding']}")
print(f"     Adjusted EBITDA          {value:>12,.0f}")


# ---------------------------------------------------------------------------
banner(6, "applicability: a springing covenant that only tests when triggered")
# ---------------------------------------------------------------------------
# Clause: "The covenant in this Section 7.11(c) shall be tested only on any
#          test date on which revolver utilisation exceeds 30%."

defs["revolver_utilisation"] = {
    "op": "divide",
    "numerator": {"op": "add", "args": [
        {"op": "input", "symbol": "revolver_drawn"},
        {"op": "input", "symbol": "letters_of_credit_outstanding"}]},
    "denominator": {"op": "input", "symbol": "revolver_commitment"},
}

springing = {
    "id": "cov_springing", "name": "Springing Net Leverage Ratio",
    "applicability": {
        "op": "gt",
        "clause": {"section": "7.11(c)", "page": 92},
        "left": {"op": "ref", "name": "revolver_utilisation"},
        "right": {"op": "const", "value": 0.30, "type": "ratio"},
    },
    "metric": {"op": "ref", "name": "net_leverage"},
    "comparator": "lte",
    "threshold": {"op": "const", "value": 4.00, "type": "ratio"},
}
validate_program(defs, [springing])

print("  ", evaluate_covenant(springing, defs, FACTS).summary(), " <- $15m/$50m = 30%, not above")
drawn = copy.deepcopy(FACTS)
drawn.stocks["revolver_drawn"] = 20_000_000
print("  ", evaluate_covenant(springing, defs, drawn).summary(), " <- $20m/$50m = 40%")
print("   NOT_APPLICABLE is a distinct status. A test that did not spring is not a pass.")


# ---------------------------------------------------------------------------
banner(7, "What the typechecker refuses, at ingest")
# ---------------------------------------------------------------------------

mistakes = [
    ("trailing a balance-sheet figure",
     {"op": "ltm", "of": {"op": "input", "symbol": "total_debt"}}),
    ("adding a stock to a flow",
     {"op": "add", "args": [{"op": "input", "symbol": "total_debt"},
                            {"op": "input", "symbol": "capex"}]}),
    ("forgetting ltm() on the denominator",
     {"op": "divide", "numerator": {"op": "ref", "name": "net_debt"},
      "denominator": {"op": "ref", "name": "ebitda_quarterly"}}),
    ("inventing a vocabulary symbol",
     {"op": "input", "symbol": "adjusted_segment_margin"}),
    ("inventing an operator",
     {"op": "annualise", "of": {"op": "ref", "name": "ebitda_quarterly"}}),
]
for label, node in mistakes:
    try:
        typecheck(node, defs)
        print(f"   {label}: NOT CAUGHT")
    except Exception as exc:
        print(f"   {label}:\n     {type(exc).__name__}: {str(exc).splitlines()[0]}")


# ---------------------------------------------------------------------------
banner(8, "Knowing what to chase, before the quarter closes")
# ---------------------------------------------------------------------------
# Because the language has no recursion, dependencies are statically knowable.

deps = dependencies(defs["adjusted_ebitda"], defs)
print("   Adjusted EBITDA needs these line items from the borrower:")
print("    ", ", ".join(sorted(deps["inputs"])))
print("   ...and these human determinations:")
print("    ", ", ".join(sorted(deps["judgments"])))


# ---------------------------------------------------------------------------
banner(9, "The same thing, loaded from a file instead of built in Python")
# ---------------------------------------------------------------------------
# Everything above was assembled inline for readability. In production the
# extractor emits one JSON document per agreement; load_program typechecks it
# and refuses malformed output before it ever reaches a test date.

program = load_program("examples/acme_lbo.json")
print(f"   {program.agreement_id}: {len(program.definitions)} definitions, "
      f"{len(program.covenants)} covenants -- typechecked at load")
print("   Now try editing examples/acme_lbo.json and re-running: break a type and")
print("   watch it fail at load, not at quarter-end.")
