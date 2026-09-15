"""Layer 1: the input vocabulary — agreement-agnostic.

These are the canonical line items a compliance certificate maps onto. This is
the DSL's symbol table: an extracted program may only reference identifiers
that appear here. Adding a symbol is a deliberate, versioned act; extraction is
never allowed to invent one.
"""

from __future__ import annotations

from .types import T

VOCABULARY: dict[str, T] = {
    # --- income statement (flows) ---
    "net_income": T.FLOW,
    "interest_expense": T.FLOW,
    "cash_interest_expense": T.FLOW,
    "tax_expense": T.FLOW,
    "depreciation_amortization": T.FLOW,
    "rent_expense": T.FLOW,
    "revenue": T.FLOW,
    "non_recurring_charges": T.FLOW,
    "restructuring_charges": T.FLOW,
    "run_rate_synergies": T.FLOW,
    # --- cash flow (flows) ---
    "capex": T.FLOW,
    "maintenance_capex": T.FLOW,
    "scheduled_principal_payments": T.FLOW,
    "dividends_paid": T.FLOW,
    "equity_cure_contributions": T.FLOW,
    # --- balance sheet (stocks) ---
    "total_debt": T.STOCK,
    "senior_secured_debt": T.STOCK,
    "capital_lease_obligations": T.STOCK,
    "unrestricted_cash": T.STOCK,
    "total_assets": T.STOCK,
    "total_equity": T.STOCK,
    "revolver_commitment": T.STOCK,
    "revolver_drawn": T.STOCK,
    "letters_of_credit_outstanding": T.STOCK,
}


def symbol_type(symbol: str) -> T:
    try:
        return VOCABULARY[symbol]
    except KeyError:
        raise KeyError(
            f"'{symbol}' is not in the input vocabulary. Extraction must map the "
            f"clause onto an existing symbol or emit a judgment node; it may not "
            f"invent identifiers."
        ) from None
