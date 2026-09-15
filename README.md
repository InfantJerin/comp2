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

## Data model

Two formalisms, because there are two different kinds of thing here.

`schema/program.schema.json` — JSON Schema for the extraction contract. The
expression language is a **sum type**, so it is modelled as a recursive
`oneOf` discriminated on `op`, not as an entity. This is the artifact to
constrain the extractor against; it rejects invented operators, judgment nodes
without a prompt, and stray keys.

`schema/model.sql` — the entity model, 19 tables. ASTs live in JSON columns;
everything with identity and a lifecycle is a table. `covenant_dependency` is a
derived index rebuilt from the ASTs at ingest, which is what keeps the
portfolio queryable without normalising every node.

Immutability is the spine: `program_version` is effective-dated and superseded
rather than edited, `fact_snapshot` records restatements as new rows, and
`evaluation` is append-only. An evaluation run three years ago must still be
reproducible against the terms and figures as they then stood.

## Not built yet

- **Delivery / reporting covenants.** "Audited financials within 120 days of
  FYE" is date arithmetic against a fiscal calendar, not a financial
  expression. Modelled in `schema/` (`reporting_obligation`) but no evaluator
  yet; it needs a second one emitting the same `CovenantResult` envelope,
  not a forced fit into this AST.
- **Units, scale and currency.** Statements in thousands vs millions is the
  classic extraction bug. `schema/model.sql` carries `scale` and `currency` on
  every fact value, but the Python interpreter does not yet enforce them.
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
