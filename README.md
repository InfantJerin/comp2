# Covenant evaluation model

A DSL for expressing extracted credit-agreement covenants, and a deterministic
interpreter that evaluates them against borrower financials.

    python3 tutorial.py    # guided walkthrough, one concept per step
    python3 demo.py        # the worked LBO, end to end
    python3 -m unittest discover -s tests -t .

## The four layers

| Layer | Agreement-specific? | Where |
|---|---|---|
| 1. Input vocabulary — canonical line items a compliance certificate maps onto | no | `covenants/vocabulary.py` |
| 2. Definition DAG — each defined term as an expression | **yes, extracted** | `examples/acme_lbo.json` → `definitions` |
| 3. Covenant test specs | **yes, extracted** | `examples/acme_lbo.json` → `covenants` |
| 4. Interpreter | no | `covenants/interpreter.py` |

A new agreement adds data. A new covenant type is a new combination of existing
operators. Only a genuinely new operator touches code.

## Operator algebra

`const` `input` `ref` `judgment` `schedule` · `add` `subtract` `multiply`
`divide` · `ltm` · `cap` `floor` · `greater_of` `lesser_of` ·
`gt` `gte` `lt` `lte` `eq` · `all_of` `any_of` `negate` · `if`

Non-Turing-complete by design: no loops, no recursion, no user-defined
functions. Every program terminates, typechecks at ingest, and has statically
enumerable input dependencies.

## The type system earns its keep

Five types — `flow`, `ltm_flow`, `stock`, `ratio`, `bool` — catch the two
mistakes extraction actually makes:

```python
typecheck({"op": "ltm", "of": {"op": "input", "symbol": "total_debt"}}, {})
# TypeError_: ltm() of a stock: a balance is point-in-time and cannot be trailed.
```

and the same omission in a division:

```
TypeError_: dividing a stock by a single-period flow. A leverage or coverage
ratio measures a balance against a trailing aggregate -- wrap the flow in ltm().
```

## Judgment nodes

Terms that bottom out in "as determined in good faith" are not something
extraction should pretend to resolve. They become an explicit node the
interpreter refuses to evaluate past, surfaced to the tracker as a required
human input — while the surrounding cap is still enforced by the model.

## Three-plus-one statuses

`PASS` · `FAIL` · `INDETERMINATE` · `NOT_APPLICABLE`

`INDETERMINATE` is the operationally important one: it names the missing line
item or judgment, which is the chase-the-borrower work list.
`NOT_APPLICABLE` is a springing test that did not spring.

## Output is the evaluated tree

`CovenantResult.trace` mirrors the AST with every node's resolved value,
operator, inputs consumed, and clause provenance. Pass/fail and headroom fall
out of the root; the trace is what gets argued about and what lets you diff two
evaluations when a fact is restated.

    LTM EBITDA before add-backs           84,000,000
    Add-backs claimed (LTM)               22,000,000
    20% cap                               16,800,000   <- binding: True
    Consolidated EBITDA                  100,800,000

## Not built yet

- **Delivery / reporting covenants.** "Audited financials within 120 days of
  FYE" is date arithmetic against a fiscal calendar, not a financial
  expression. It needs a second evaluator emitting the same `CovenantResult`
  envelope — not a forced fit into this AST.
- **Units, scale and currency.** Statements in thousands vs millions is the
  classic extraction bug. `metadata.scale` is recorded but not enforced;
  values should carry scale and the interpreter should refuse to combine
  mismatched ones.
- **`pro_forma`.** Acquisition/disposal adjustments. Deliberately deferred
  until the operator algebra has been tested against real agreements.
- **Cure and waiver mechanics.** `covenant.cure` is captured as data but not
  executed. A breach is not a default; this belongs in a separate state machine
  consuming breach events.
- **Round-trip validation.** Run an extracted DAG against a historical
  compliance certificate and diff the computed figures against the borrower's.
  A far stronger extraction check than adversarial re-reading, and it fits as a
  third, numeric pass.
- **Immutable evaluation records.** Restatements should produce a new
  evaluation, never mutate one.
