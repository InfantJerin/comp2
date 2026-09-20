Covenant Compilation
20 Sept 2026 · @Jerin
The ask
One quarter, two engineers and one ops or credit partner, to compile 15 sponsor-backed agreements from our own book and measure how often the system is right.
The success criterion is falsifiable, which is the point of stating it: 15 agreements compiled and frozen; every computable covenant reconciled against the borrower's reported figures or against ops' own workings, within a tolerance we set in advance; each agreement reviewed by loan ops in under 30 minutes; and a published error rate per covenant type. If we miss it, we will know precisely where.
It cannot be met without real agreements and real ops time. That is deliberate. Everything below was built on public EDGAR documents alone, and public documents have now taken this as far as they can — the two findings in this memo are both discoveries that we cannot get further without our own data.
What exists today: three real credit agreements compiled and evaluated, a typed evaluation engine, 59 tests, and roughly 700 lines of written analysis. No firm data has touched it.
What it is
A credit agreement is compiled once into a typed graph, a human approves it, and every quarter thereafter is deterministic arithmetic with no model in the loop.
That sentence carries the whole design. Extraction is a build step, not a runtime one. An LLM reads the agreement and emits a graph of named definitions — Consolidated EBITDA, its sixteen add-back clauses, the ratio, the threshold — each node carrying the clause and quote it came from. A reviewer approves it. The artifact is versioned and frozen. Evaluation then binds that graph to a quarter's figures and produces not a number but an evaluated tree: every input, every intermediate, every clause reference, down to the leaves.
Three consequences follow, and they are why this shape rather than another:
1. The same inputs cannot give a different answer next quarter. There is no sampling at evaluation time.
2. A defect is fixed once. It lives in one frozen artifact, not in a prompt that will be re-run against 400 agreements.
3. Every number traces to a quoted clause. Not as a citation bolted on afterwards, but because the citation is the node.
The engine has four statuses, and the third is the one that matters: pass, fail, indeterminate, and not-applicable. Indeterminate means the system was asked for a number it does not have and declined to produce one. Both findings in this memo are cases where declining was the correct answer and guessing would have been expensive.
Three agreements
Three real agreements have been compiled and run, chosen for difficulty rather than convenience.
Agreement
Agent
Covenants extracted
New operators
New vocabulary
Airbnb 2022 revolver
—
2
0
25
Avantor term loan, Amdt 14
Goldman Sachs Bank USA
2
0
9
American Campus Communities
KeyBank
3
1
11
The two columns on the right are the scalability claim, measured rather than asserted. Adding a corporate-credit agreement costs data, not code: Airbnb's sixteen-clause EBITDA and Avantor's eleven both compiled with operators that already existed. The operator set stretched exactly once, at the boundary into commercial real estate, where ACC values property by capitalising net operating income at a rate the contract fixes at 6.25%. That is the per-product module design behaving as predicted — not a language that needs extending for every deal, but one that needs extending when the asset class changes.
The type system earns its place at that boundary. Capitalising an income stream is a division, and division of money by a rate returns money of the numerator's kind — so the valuation came out typed as an income flow and then refused to be added to the book values beside it. The typechecker rejected the extraction at ingest, before any number existed. An untyped representation would have added a flow to a stock, produced a plausible asset value, and been wrong every quarter thereafter with nothing to catch it.
One pattern recurred in all three, and I did not expect it. Every agreement relaxes its leverage threshold for four quarters following an acquisition, on written notice to the agent — Airbnb by 0.5x, Avantor by 0.5x, ACC from 60% to 65%. Three industries, three agents, three for three. Whether the threshold today is 3.50 or 4.00 is not a fact about the document. It is notice history, and nothing in the agreement or the financial statements contains it.
Two ways this gets it wrong
Both of the following are real, both were found by running the system rather than by reasoning about it, and both are the reason I am confident about the design rather than despite it.
The false breach: 3.54 against a 3.50 limit
Avantor's Section 7.11 caps Consolidated First Lien Net Leverage at 3.50:1.00. Goldman is the agent. The engine computed Consolidated EBITDA of $964.1m from the contract's eleven add-back clauses — 3.0% from the $993.8m Avantor reports under its own non-GAAP definition, which is about as close as two different definitions should land — and then returned indeterminate on the leverage covenant.
It refused because the covenant measures first lien debt and Avantor discloses only total gross debt of $3,715.4m. The first-lien tranche is never broken out.
Substituting total net debt — the obvious shortcut, and the one a model in a hurry or an analyst at 7pm takes — gives $3,408.6m / $964.1m = 3.54x against a 3.50x limit. A covenant breach, escalated to a credit committee, on a borrower whose own 10-Q states it was within its covenant requirements. Nothing in the arithmetic is wrong. The substitution is wrong, and correct arithmetic propagates it faithfully into a false alarm.
Four hundredths of a turn separate a system that asks for one number from a system that raises an incident.
The false oracle: 52.1% against a published 42.1%
This one is worse, because it would have corrupted our own testing.
American Campus Communities publishes a quarterly table captioned "Requirement / Current Ratio": Total Debt to Total Asset Value ≤ 60%, current 42.1%. Secured Debt to Total Asset Value ≤ 40%, current 7.1%. Section 5.04 of its credit agreement sets a Leverage Ratio of ≤ 60% and a Secured Debt ratio of ≤ 40%. Identical names, identical thresholds, audited numbers, correct arithmetic.
The table belongs to the unsecured notes, and the denominators are unrelated. The notes use undepreciated book value. The agreement uses capitalised NOI at 6.25%, plus book value for assets held under four quarters, plus unrestricted cash, plus an allocation of unconsolidated entities — and excludes the On-Campus Participating Properties entirely, whose $81m of debt the notes table includes.

Numerator
Denominator
Ratio
Headroom to 60%
Published (notes covenant)
3,750,000
8,903,000
42.1%
17.9 pts
Credit agreement (partial)
3,669,000
7,040,115
52.1%
7.9 pts
Capitalised NOI comes in 21.5% below book value. Had we validated the engine against that table, a correct extraction would have been recorded as a bug, or a broken one blessed as correct — either way wearing the authority of a match. The only tell is one word in a heading and forty lines of definition in a document nobody reads next to the supplemental.
The fix, in both cases
The fix is not cleverer inference. It is a third queue. Pass, fail, and needs a human — so that uncertainty is routed out of the breach queue rather than resolved into it. Precision on breaches stays high because doubt never enters; recall is preserved because nothing is dropped; and the third queue is worked by why the engine stopped rather than agreement by agreement. "Tell me which first-lien number to use" is a two-minute task. Retracting a breach call is not.
Architecture
This is a data structure, not a language. There is no grammar, no parser, no source text, and nothing for a human to write. Definitions are JSON nodes validated by JSON Schema, referencing each other through ref edges. The graph is the artifact.
That matters beyond naming. A graph is queryable across the portfolio — every agreement whose EBITDA adds back unrealised FX — diffable between amendment versions, and renderable for a reviewer who will never read an AST. Expression strings buy none of that.
Twenty-four operators, six value types. The types are flow, trailing flow, stock, ratio, boolean and count. They exist to catch the errors that do not announce themselves: a stock divided by a single quarter's flow quadruples reported leverage and looks entirely plausible. The engine rejects it at ingest.
The vocabulary is closed, and extraction may never add to it. An unrecognised term becomes a queue item carrying the quoted text; a small group decides add-versus-alias and the agreement recompiles. The failure this prevents is not extraction inventing nonsense — it is extraction inventing something reasonable. One agreement gets restructuring_charges, another gets business_optimization_costs, both are defensible readings of near-identical language, and the portfolio is silently incomparable in a way no test catches. At a few hundred agreements that is unrecoverable.
Why not an existing language
The serious alternatives were considered and rejected for one reason each.
Prior art
Why not
Google CEL
Mature and sandboxed, but general. Expressiveness is the problem, not the goal.
ISDA CDM / Rosetta
Right instinct, wrong domain shape: derivatives are standardised, credit agreements are negotiated one at a time.
Catala
Built for prioritised default logic. Recommended here early, then retracted — the reasoning is in the repo's commit history.
DMN / FEEL
Decision tables suit a pricing grid, not a definition graph with sixteen nested clauses.
The argument for building rather than adopting is not that CEL cannot express these covenants. It plainly can. It is that CEL gives a generative model unbounded room, and this design deliberately does the opposite: 24 operators, a fixed symbol table, and a type error for a missing trailing window. The restriction is the product. A clause that does not fit must become an explicit refusal — a judgment node naming what a human has to determine — because there is no way to express a guess.
What we are not building
Four exclusions, each a decision rather than an omission.
Securities-based and margin lending is out of scope. It is a different object wearing the same word. A maintenance LTV tested intraday against a mark-to-market portfolio has no definition graph, no negotiated language, no compliance certificate and no extraction problem worth solving — the paper is standardised. Every mechanism here exists to handle language that was negotiated once and appears nowhere else, and none of it earns its keep against a margin loan. Including it would force a quarterly-certificate architecture to accommodate a price feed, which is the single most distorting requirement we could add. I understand the current expectation runs the other way, and this is the one scope decision in this memo I would most like to discuss.
Incurrence and qualitative covenants are out for this year. Confirmed, and it closes a real research question rather than deferring it.
Unspecified deadlines are not modelled. "Promptly" is the single most common deadline construction in the corpus — 370 occurrences across eight agreements — and it is not computable. Nor are "as soon as available" or "such later date as the Administrative Agent may agree". Roughly 60% of delivery obligations have deadlines the system will not compute. Having extraction guess a number from context was rejected: it produces a figure that looks extracted, cannot be defended against the text, and varies between agreements for no reason. Every obligation is still tracked for arrival; only the date-computable ones are tested for lateness, and the interface must show the difference. The danger is not the gap. It is a green dashboard read as complete coverage when the engine never had an opinion on two-thirds of it.
The relationship-state record is designed, not built. Elections, waivers, cure usage, basket consumption and notice history are facts about the relationship rather than the agreement or the financials, and there is currently nowhere to put them. This is the largest structural gap in the design, and the acquisition-election pattern found in all three agreements means it is required to evaluate a threshold, not merely to enrich one. It is a named phase-two component.
Model risk
This architecture is unusually easy to govern, and that is a consequence of the design rather than a claim about it.
• No model runs at evaluation time. Extraction happens once; the frozen artifact is arithmetic. There is nothing to sample, nothing to drift.
• Every artifact is versioned and human-approved, and amendments trigger full re-extraction against the restated document with a diff shown to the reviewer. Patching a prior graph was rejected: amendments restate definitions by reference, change single words inside clauses, and amend prior amendments.
• Every number traces to a quoted clause, because the citation is the node rather than an annotation.
• The system refuses rather than guesses, and the two findings above are what that looks like in practice.
• Two models must agree. Independent extractions are compared and every disagreement routes to the review queue.
• Correctness is measured, not asserted — see the plan below.
Very little AI tooling in a bank can say any of that. The governance conversation is usually the obstacle; here it is closer to a differentiator, and I would rather raise it now than have it raised later.
Verification is the hard part, and it is harder than it looks
The obvious verification story is to reproduce the borrower's own published covenant ratio. It is a near-perfect oracle and it barely exists. Of sixteen screened public filers, three looked usable. Both of the best two then failed on inspection: Avantor's covenant runs on a first-lien tranche it never discloses, and ACC's published table belongs to a different instrument. For private credit, mid-market, CRE and fund finance there is no oracle at all.
So back-testing is calibration, not verification. On the narrow subset where an oracle exists, we measure how well the cheap signals predict correctness — and that measured relationship is what licenses trusting those signals everywhere else. The claim is not that the engine is correct. It is that we can measure how correct it is, and that the measurement generalises.
The signal that carries the weight is one the agreements supply themselves. Credit agreements are unusually rich in worked examples: the compliance certificate form with its arithmetic, numeric illustrations inside definitions, pricing-grid samples. Extraction emits those as executable assertions alongside the definitions. Unlike public filings, they are available on 100% of the book, private credit included.
The plan
One quarter, three people, one falsifiable number at the end.

Focus
Done when
Weeks 1–4
Compile 15 sponsor-backed agreements from our book; build the ops review surface
Each agreement reviewed in under 30 minutes
Weeks 5–8
Dual extraction, self-extracted assertions, version-to-period pinning
Every computable covenant reconciled or explicitly queued
Weeks 9–12
Measure and publish the error rate per covenant type; decide on ABL as the second module
A number we would defend to audit
Broadly syndicated and sponsor-backed term loans go first. Not because they are the most valuable — ABL probably is — but because they are the only product where the architecture can be proven before four product lines depend on it, and the only one where public filings give any objective signal at all. ABL second; the borrowing base deserves its own design conversation rather than being the thing the framework is discovered on.
What I need: two engineers, one ops or credit partner for roughly two hours a week, and access to 15 real agreements. That is the whole ask, and the third item is the one that matters — it is the only thing this work cannot obtain for itself.
What is true in December that is not true now: we will know the system's error rate on our own paper, by covenant type, measured rather than estimated. If that number is bad, we will know which covenant types are bad and why, and stopping will be a cheap and well-informed decision. If it is good, the case for the second product module writes itself.
Assumptions, stated as assumptions. The 30-minute review budget, loan ops as the reviewing function, and the condition of the current tooling are all things I believe rather than things I have verified. No firm data has been available. Correcting any of them changes the plan and none of them changes the architecture.
Appendices
The design decisions, the gap analysis against Airbnb, the eight-agreement stress-test corpus, and the ACC false-oracle write-up are in the repository, along with 59 tests that pin every number in this memo.
