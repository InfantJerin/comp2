"""Golden tests for the covenant DSL.

The numeric cases pin the arithmetic a banker would redo by hand. The rejection
cases pin the promise that a malformed or ill-typed extraction fails at ingest
rather than at quarter-end.
"""

import copy
import json
import unittest
from datetime import date
from pathlib import Path

from covenants import Facts, Period, Status, evaluate, load_program
from covenants.dsl import SchemaError, dependencies, typecheck
from covenants.facts import facts_from_dict
from covenants.types import TypeError_

ROOT = Path(__file__).resolve().parent.parent
PROGRAM = load_program(ROOT / "examples" / "acme_lbo.json")
RAW_FACTS = json.loads((ROOT / "examples" / "acme_q4_2027_facts.json").read_text())


def facts(**overrides):
    raw = copy.deepcopy(RAW_FACTS)
    raw.update(overrides)
    return facts_from_dict(raw)


def result(covenant_id, snapshot):
    return next(r for r in PROGRAM.evaluate(snapshot) if r.covenant_id == covenant_id)


class DefinitionArithmetic(unittest.TestCase):
    def value(self, name, snapshot=None):
        value, _, gaps = evaluate(
            {"op": "ref", "name": name}, PROGRAM.definitions, snapshot or facts()
        )
        self.assertEqual(gaps, [], f"unexpected gaps computing {name}")
        return value

    def test_ltm_sums_four_trailing_periods(self):
        self.assertEqual(self.value("ltm_ebitda_pre_addbacks"), 84_000_000)

    def test_addback_cap_binds_at_twenty_percent(self):
        self.assertEqual(self.value("capped_addbacks"), 16_800_000)  # not the 22m claimed
        self.assertEqual(self.value("consolidated_ebitda"), 100_800_000)

    def test_cash_netting_is_capped(self):
        # $90m of cash, netting capped at $75m, against $400m of debt.
        self.assertEqual(self.value("netted_cash"), 75_000_000)
        self.assertEqual(self.value("total_net_debt"), 325_000_000)

    def test_leverage_and_coverage(self):
        self.assertAlmostEqual(self.value("total_net_leverage_ratio"), 3.2242, places=4)
        self.assertAlmostEqual(self.value("fixed_charge_coverage_ratio"), 3.4154, places=4)

    def test_stock_is_point_in_time_not_trailed(self):
        # Net debt must not be four times the balance-sheet figure.
        self.assertEqual(self.value("total_net_debt"), 325_000_000)


class CovenantOutcomes(unittest.TestCase):
    def test_pass_with_headroom(self):
        r = result("cov_total_net_leverage", facts())
        self.assertIs(r.status, Status.PASS)
        self.assertEqual(r.threshold, 4.00)
        self.assertAlmostEqual(r.headroom_pct, (4.00 - 3.2242) / 4.00, places=3)

    def test_threshold_step_down_is_data_not_code(self):
        later = copy.deepcopy(RAW_FACTS)
        later["test_date"] = "2028-12-31"
        for period in later["periods"]:
            period["end"] = "2028-" + period["end"][5:]
        r = result("cov_total_net_leverage", facts_from_dict(later))
        self.assertEqual(r.threshold, 3.50)
        self.assertIs(r.status, Status.PASS)

    def test_breach(self):
        heavy = copy.deepcopy(RAW_FACTS)
        heavy["stocks"]["total_debt"] = 520_000_000
        r = result("cov_total_net_leverage", facts_from_dict(heavy))
        self.assertIs(r.status, Status.FAIL)
        self.assertTrue(r.breached)
        self.assertLess(r.headroom_pct, 0)

    def test_springing_test_does_not_spring_below_trigger(self):
        r = result("cov_springing_senior_leverage", facts())  # 25% utilisation
        self.assertIs(r.status, Status.NOT_APPLICABLE)
        self.assertIsNone(r.actual)

    def test_springing_test_springs_above_trigger(self):
        drawn = copy.deepcopy(RAW_FACTS)
        drawn["stocks"]["revolver_drawn"] = 60_000_000  # 65% utilisation
        r = result("cov_springing_senior_leverage", facts_from_dict(drawn))
        self.assertIs(r.status, Status.PASS)
        self.assertAlmostEqual(r.actual, 225_000_000 / 100_800_000, places=6)


class Indeterminacy(unittest.TestCase):
    """A missing fact is never a pass and never a fail."""

    def test_missing_line_item_names_the_gap(self):
        gapped = copy.deepcopy(RAW_FACTS)
        del gapped["periods"][-1]["flows"]["depreciation_amortization"]
        r = result("cov_total_net_leverage", facts_from_dict(gapped))
        self.assertIs(r.status, Status.INDETERMINATE)
        self.assertIsNone(r.actual)
        self.assertIn("depreciation_amortization", [g.name for g in r.gaps])

    def test_unfilled_judgment_blocks_evaluation(self):
        gapped = copy.deepcopy(RAW_FACTS)
        gapped["judgments"] = {}
        r = result("cov_total_net_leverage", facts_from_dict(gapped))
        self.assertIs(r.status, Status.INDETERMINATE)
        gap = next(g for g in r.gaps if g.kind == "judgment")
        self.assertEqual(gap.name, "extraordinary_items")
        self.assertIn("good faith", gap.reason)

    def test_gaps_are_deduplicated(self):
        gapped = copy.deepcopy(RAW_FACTS)
        gapped["judgments"] = {}
        r = result("cov_total_net_leverage", facts_from_dict(gapped))
        # The judgment is consumed by all four legs of the trailing window.
        self.assertEqual(len([g for g in r.gaps if g.name == "extraordinary_items"]), 1)

    def test_short_history_blocks_the_trailing_window(self):
        short = copy.deepcopy(RAW_FACTS)
        short["periods"] = short["periods"][-2:]
        r = result("cov_total_net_leverage", facts_from_dict(short))
        self.assertIs(r.status, Status.INDETERMINATE)
        self.assertTrue(any(g.kind == "period" for g in r.gaps))

    def test_missing_schedule_entry_is_a_gap_not_a_guess(self):
        early = copy.deepcopy(RAW_FACTS)
        early["test_date"] = "2024-12-31"
        early["periods"] = [
            {"end": f"2024-{m}", "flows": dict(early["periods"][0]["flows"])}
            for m in ("03-31", "06-30", "09-30", "12-31")
        ]
        r = result("cov_total_net_leverage", facts_from_dict(early))
        self.assertIs(r.status, Status.INDETERMINATE)
        self.assertTrue(any(g.kind == "schedule" for g in r.gaps))


class StaticRejection(unittest.TestCase):
    """Everything here must fail at ingest."""

    defs = PROGRAM.definitions

    def test_ltm_of_a_stock(self):
        with self.assertRaises(TypeError_) as cm:
            typecheck({"op": "ltm", "of": {"op": "input", "symbol": "total_debt"}}, {})
        self.assertIn("point-in-time", str(cm.exception))

    def test_double_ltm(self):
        with self.assertRaises(TypeError_):
            typecheck(
                {"op": "ltm", "of": {"op": "ltm", "of": {"op": "input", "symbol": "capex"}}}, {}
            )

    def test_adding_a_stock_to_a_flow(self):
        with self.assertRaises(TypeError_):
            typecheck(
                {"op": "add", "args": [
                    {"op": "input", "symbol": "total_debt"},
                    {"op": "input", "symbol": "capex"},
                ]}, {},
            )

    def test_multiplying_two_money_values(self):
        with self.assertRaises(TypeError_):
            typecheck(
                {"op": "multiply", "args": [
                    {"op": "input", "symbol": "total_debt"},
                    {"op": "input", "symbol": "total_assets"},
                ]}, {},
            )

    def test_stock_divided_by_a_single_period_flow(self):
        # The missing-ltm() bug: net debt over one quarter of EBITDA.
        with self.assertRaises(TypeError_) as cm:
            typecheck(
                {"op": "divide",
                 "numerator": {"op": "ref", "name": "total_net_debt"},
                 "denominator": {"op": "ref", "name": "ebitda_pre_addbacks"}},
                self.defs,
            )
        self.assertIn("wrap the flow in ltm()", str(cm.exception))

    def test_dividing_unlike_windows(self):
        with self.assertRaises(TypeError_):
            typecheck(
                {"op": "divide",
                 "numerator": {"op": "ref", "name": "consolidated_ebitda"},
                 "denominator": {"op": "ref", "name": "ebitda_pre_addbacks"}},
                self.defs,
            )

    def test_legitimate_divisions_still_typecheck(self):
        typecheck(self.defs["total_net_leverage_ratio"], self.defs)   # stock / ltm_flow
        typecheck(self.defs["revolver_utilisation"], self.defs)       # stock / stock
        typecheck(self.defs["fixed_charge_coverage_ratio"], self.defs)  # ltm / ltm

    def test_invented_vocabulary_symbol(self):
        with self.assertRaises(KeyError):
            typecheck({"op": "input", "symbol": "adjusted_widget_margin"}, {})

    def test_invented_operator(self):
        with self.assertRaises(SchemaError) as cm:
            typecheck({"op": "annualise", "of": {"op": "input", "symbol": "capex"}}, {})
        self.assertIn("judgment", str(cm.exception))

    def test_definition_cycle(self):
        defs = {
            "a": {"op": "add", "args": [{"op": "ref", "name": "b"},
                                        {"op": "input", "symbol": "capex"}]},
            "b": {"op": "add", "args": [{"op": "ref", "name": "a"},
                                        {"op": "input", "symbol": "capex"}]},
        }
        with self.assertRaises(SchemaError) as cm:
            typecheck(defs["a"], defs)
        self.assertIn("cycle", str(cm.exception))

    def test_judgment_without_a_prompt(self):
        with self.assertRaises(SchemaError):
            typecheck({"op": "judgment", "name": "x", "type": "flow"}, {})

    def test_comparing_a_ratio_against_money(self):
        with self.assertRaises(TypeError_):
            typecheck(
                {"op": "lte", "left": {"op": "input", "symbol": "total_debt"},
                 "right": {"op": "const", "value": 3.5, "type": "ratio"}}, {},
            )


class Requirements(unittest.TestCase):
    def test_dependencies_are_enumerable_before_the_period_closes(self):
        deps = dependencies(
            {"op": "ref", "name": "total_net_leverage_ratio"}, PROGRAM.definitions
        )
        self.assertEqual(deps["judgments"], {"extraordinary_items"})
        self.assertIn("unrestricted_cash", deps["inputs"])
        self.assertIn("run_rate_synergies", deps["inputs"])
        self.assertNotIn("revolver_drawn", deps["inputs"])

    def test_program_requirements_cover_every_covenant(self):
        self.assertEqual(set(PROGRAM.requirements()), {c["id"] for c in PROGRAM.covenants})


class Trace(unittest.TestCase):
    def test_trace_carries_clause_provenance_and_a_binding_cap(self):
        _, trace, _ = evaluate(
            {"op": "ref", "name": "capped_addbacks"}, PROGRAM.definitions, facts()
        )
        cap = trace["definition"]
        self.assertTrue(cap["binding"])
        self.assertEqual(cap["of"]["value"], 22_000_000)
        self.assertIn("20%", cap["limit"]["definition"]["clause"]["section"])

    def test_input_nodes_record_their_basis(self):
        _, trace, _ = evaluate(
            {"op": "input", "symbol": "unrestricted_cash"}, PROGRAM.definitions, facts()
        )
        self.assertEqual(trace["basis"], "as at 2027-12-31")


class NoPeriods(unittest.TestCase):
    def test_test_date_before_any_reported_period(self):
        snapshot = Facts(test_date=date(2020, 1, 1),
                         periods=[Period(end=date(2027, 3, 31), flows={})])
        r = next(r for r in PROGRAM.evaluate(snapshot) if r.covenant_id == "cov_fccr")
        self.assertIs(r.status, Status.INDETERMINATE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
