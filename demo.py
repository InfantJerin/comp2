"""Run the worked example end to end."""

import json
from copy import deepcopy
from datetime import date

from covenants import load_program
from covenants.facts import facts_from_dict

program = load_program("examples/acme_lbo.json")
raw_facts = json.loads(open("examples/acme_q4_2027_facts.json").read())


def run(title, facts):
    print(f"\n{title}\n{'-' * len(title)}")
    for result in program.evaluate(facts):
        print(" ", result.summary())


run("Q4 2027 — complete certificate", facts_from_dict(raw_facts))

stepped = deepcopy(raw_facts)
stepped["test_date"] = "2028-12-31"
for offset, period in enumerate(stepped["periods"]):
    period["end"] = f"2028-{period['end'][5:]}"
run("Q4 2028 — same performance, stepped-down threshold", facts_from_dict(stepped))

missing = deepcopy(raw_facts)
del missing["judgments"]["extraordinary_items"]
del missing["periods"][-1]["flows"]["depreciation_amortization"]
run("Q4 2027 — incomplete certificate", facts_from_dict(missing))

drawn = deepcopy(raw_facts)
drawn["stocks"]["revolver_drawn"] = 60000000
run("Q4 2027 — revolver drawn to 65%, springing test triggered", facts_from_dict(drawn))

print("\nEBITDA build for Q4 2027 (the trace a banker argues about)")
print("-" * 58)
value, trace, _ = __import__("covenants").evaluate(
    {"op": "ref", "name": "consolidated_ebitda"}, program.definitions, facts_from_dict(raw_facts)
)
defn = trace["definition"]
pre = defn["args"][0]["definition"]["value"]
capped = defn["args"][1]
print(f"  LTM EBITDA before add-backs      {pre:>15,.0f}")
print(f"  Add-backs claimed (LTM)          {capped['definition']['of']['value']:>15,.0f}")
print(f"  20% cap                          {capped['definition']['limit']['definition']['value']:>15,.0f}"
      f"   <- binding: {capped['definition']['binding']}")
print(f"  Consolidated EBITDA              {value:>15,.0f}")
