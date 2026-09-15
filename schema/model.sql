-- Persistence model for the covenant evaluation engine.
--
-- The central decision: expression ASTs are stored as JSON values, not as rows
-- in a node table. An AST is a *value* with no independent identity or
-- lifecycle -- nobody ever asks "show me node 4471" -- so normalising it costs
-- a recursive CTE on every read and buys nothing the derived indexes below do
-- not already give. Everything that *does* have identity and a lifecycle is a
-- proper table.
--
-- Written in portable SQL; JSON columns are TEXT here and become JSONB on
-- Postgres. Runs as-is on SQLite for prototyping.

-- ===========================================================================
-- Reference data. Global, versioned, agreement-agnostic.
-- ===========================================================================

-- Layer 1. The symbol table of the DSL. Extraction may not invent identifiers,
-- so this table is the closed set an extracted program may reference.
CREATE TABLE vocabulary_symbol (
    code                TEXT PRIMARY KEY,
    value_type          TEXT NOT NULL
                        CHECK (value_type IN ('flow','ltm_flow','stock','ratio','bool','count')),
    label               TEXT NOT NULL,
    description         TEXT,
    introduced_at       TEXT NOT NULL,
    retired_at          TEXT
);

-- The operator algebra, as data, so the extraction prompt and any UI can be
-- generated from the same source the interpreter implements.
CREATE TABLE operator (
    code                TEXT PRIMARY KEY,
    arity               TEXT NOT NULL CHECK (arity IN ('leaf','unary','binary','nary')),
    result_type_rule    TEXT NOT NULL,
    description         TEXT NOT NULL
);

-- ===========================================================================
-- Parties and agreements.
-- ===========================================================================

CREATE TABLE borrower (
    borrower_id         TEXT PRIMARY KEY,
    legal_name          TEXT NOT NULL,
    -- The fiscal calendar is per borrower, not global. Delivery deadlines and
    -- the boundaries of a trailing window both depend on it.
    fiscal_year_end_md  TEXT NOT NULL CHECK (fiscal_year_end_md GLOB '[0-9][0-9]-[0-9][0-9]'),
    reporting_currency  TEXT NOT NULL CHECK (length(reporting_currency) = 3)
);

CREATE TABLE agreement (
    agreement_id        TEXT PRIMARY KEY,
    borrower_id         TEXT NOT NULL REFERENCES borrower(borrower_id),
    facility_name       TEXT NOT NULL,
    deal_type           TEXT,
    signed_date         TEXT NOT NULL
);

-- ===========================================================================
-- The extracted program. Layers 2 and 3.
--
-- Immutable once approved. An amendment produces a NEW version with its own
-- effective window; nothing is edited in place, because an evaluation run three
-- years ago must still be reproducible against the terms as they then stood.
-- ===========================================================================

CREATE TABLE program_version (
    program_version_id  TEXT PRIMARY KEY,
    agreement_id        TEXT NOT NULL REFERENCES agreement(agreement_id),
    version_no          INTEGER NOT NULL,
    -- Effective-dated so a test date selects the terms that governed it.
    effective_from      TEXT NOT NULL,
    effective_to        TEXT,
    status              TEXT NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft','in_review','approved','superseded')),
    source_document_id  TEXT REFERENCES document(document_id),
    amendment_of        TEXT REFERENCES program_version(program_version_id),
    extracted_at        TEXT NOT NULL,
    extracted_by_model  TEXT,
    approved_by         TEXT,
    approved_at         TEXT,
    UNIQUE (agreement_id, version_no),
    CHECK (status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);

-- Layer 2: the definition DAG. One row per defined term; `expr` is its AST.
CREATE TABLE definition (
    definition_id       TEXT PRIMARY KEY,
    program_version_id  TEXT NOT NULL REFERENCES program_version(program_version_id),
    name                TEXT NOT NULL,
    expr                TEXT NOT NULL,          -- JSON: the AST
    value_type          TEXT NOT NULL,          -- result of typecheck(), cached
    clause_section      TEXT,
    clause_page         INTEGER,
    clause_quote        TEXT,
    extraction_conf     REAL CHECK (extraction_conf BETWEEN 0 AND 1),
    UNIQUE (program_version_id, name)
);

-- Layer 3: the test specs.
CREATE TABLE covenant (
    covenant_id         TEXT PRIMARY KEY,
    program_version_id  TEXT NOT NULL REFERENCES program_version(program_version_id),
    covenant_key        TEXT NOT NULL,          -- stable across versions; survives amendments
    name                TEXT NOT NULL,
    metric_expr         TEXT NOT NULL,          -- JSON
    comparator          TEXT NOT NULL CHECK (comparator IN ('gt','gte','lt','lte','eq')),
    threshold_expr      TEXT NOT NULL,          -- JSON; usually a schedule node
    applicability_expr  TEXT,                   -- JSON; NULL means always tested
    frequency           TEXT NOT NULL,
    testing_period      TEXT NOT NULL,
    cure                TEXT,                   -- JSON; consumed by the breach machine
    consequence         TEXT,
    clause_section      TEXT,
    clause_page         INTEGER,
    extraction_conf     REAL CHECK (extraction_conf BETWEEN 0 AND 1),
    UNIQUE (program_version_id, covenant_key)
);

-- Delivery covenants: date arithmetic against the fiscal calendar, evaluated by
-- a separate evaluator that emits the same result envelope.
CREATE TABLE reporting_obligation (
    obligation_id       TEXT PRIMARY KEY,
    program_version_id  TEXT NOT NULL REFERENCES program_version(program_version_id),
    obligation_key      TEXT NOT NULL,
    name                TEXT NOT NULL,
    deliverable         TEXT NOT NULL,
    trigger             TEXT NOT NULL,
    due_days            INTEGER NOT NULL,
    grace_days          INTEGER NOT NULL DEFAULT 0,
    clause_section      TEXT,
    clause_page         INTEGER,
    UNIQUE (program_version_id, obligation_key)
);

-- Derived index, rebuilt from the ASTs at ingest by dependencies(). This is
-- what makes the portfolio queryable without normalising every node:
--   "which agreements cap cash netting?"
--   "which borrowers must supply run_rate_synergies this quarter?"
--   "what breaks if the auditor restates depreciation?"
CREATE TABLE covenant_dependency (
    program_version_id  TEXT NOT NULL REFERENCES program_version(program_version_id),
    covenant_key        TEXT NOT NULL,
    dependency_kind     TEXT NOT NULL CHECK (dependency_kind IN ('input','judgment')),
    dependency_name     TEXT NOT NULL,
    PRIMARY KEY (program_version_id, covenant_key, dependency_kind, dependency_name)
);

-- ===========================================================================
-- What the borrower sends in.
-- ===========================================================================

CREATE TABLE document (
    document_id         TEXT PRIMARY KEY,
    borrower_id         TEXT NOT NULL REFERENCES borrower(borrower_id),
    doc_type            TEXT NOT NULL,
    period_end          TEXT,
    received_at         TEXT NOT NULL,
    file_uri            TEXT NOT NULL,
    sha256              TEXT NOT NULL
);

-- A facts snapshot is immutable. A restatement creates a new snapshot pointing
-- back at the one it supersedes; it never overwrites.
CREATE TABLE fact_snapshot (
    snapshot_id         TEXT PRIMARY KEY,
    borrower_id         TEXT NOT NULL REFERENCES borrower(borrower_id),
    test_date           TEXT NOT NULL,
    source_document_id  TEXT REFERENCES document(document_id),
    restates            TEXT REFERENCES fact_snapshot(snapshot_id),
    created_at          TEXT NOT NULL
);

-- Flows are per fiscal period, which is what makes ltm() a real trailing
-- aggregate. Scale and currency travel with every value: statements reported in
-- thousands against a threshold written in units is the classic extraction bug,
-- and it must be impossible to combine mismatched ones silently.
CREATE TABLE fact_flow (
    snapshot_id         TEXT NOT NULL REFERENCES fact_snapshot(snapshot_id),
    symbol              TEXT NOT NULL REFERENCES vocabulary_symbol(code),
    period_end          TEXT NOT NULL,
    value               REAL NOT NULL,
    scale               TEXT NOT NULL DEFAULT 'units'
                        CHECK (scale IN ('units','thousands','millions')),
    currency            TEXT NOT NULL,
    source_document_id  TEXT REFERENCES document(document_id),
    source_page         INTEGER,
    source_line_label   TEXT,
    extraction_conf     REAL,
    PRIMARY KEY (snapshot_id, symbol, period_end)
);

-- Stocks are point-in-time as at the snapshot's test date.
CREATE TABLE fact_stock (
    snapshot_id         TEXT NOT NULL REFERENCES fact_snapshot(snapshot_id),
    symbol              TEXT NOT NULL REFERENCES vocabulary_symbol(code),
    value               REAL NOT NULL,
    scale               TEXT NOT NULL DEFAULT 'units'
                        CHECK (scale IN ('units','thousands','millions')),
    currency            TEXT NOT NULL,
    source_document_id  TEXT REFERENCES document(document_id),
    source_page         INTEGER,
    source_line_label   TEXT,
    extraction_conf     REAL,
    PRIMARY KEY (snapshot_id, symbol)
);

-- Human determinations for judgment nodes. Who decided, when, and why -- the
-- part of the calculation that is a person's opinion is recorded as such.
CREATE TABLE judgment_value (
    snapshot_id         TEXT NOT NULL REFERENCES fact_snapshot(snapshot_id),
    judgment_name       TEXT NOT NULL,
    value               REAL NOT NULL,
    scale               TEXT NOT NULL DEFAULT 'units',
    currency            TEXT,
    determined_by       TEXT NOT NULL,
    determined_at       TEXT NOT NULL,
    rationale           TEXT,
    PRIMARY KEY (snapshot_id, judgment_name)
);

-- ===========================================================================
-- Scheduling and results.
-- ===========================================================================

-- Generated ahead of time from each covenant's frequency and the borrower's
-- fiscal calendar, so the chase list exists before the period closes.
CREATE TABLE test_event (
    test_event_id       TEXT PRIMARY KEY,
    agreement_id        TEXT NOT NULL REFERENCES agreement(agreement_id),
    covenant_key        TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    test_date           TEXT NOT NULL,
    certificate_due     TEXT,
    state               TEXT NOT NULL DEFAULT 'scheduled'
                        CHECK (state IN ('scheduled','awaiting_data','evaluated','closed')),
    UNIQUE (agreement_id, covenant_key, period_end)
);

-- Append-only. Re-running after a restatement or a corrected definition writes
-- a new row and marks the old one superseded; nothing is updated in place.
CREATE TABLE evaluation (
    evaluation_id       TEXT PRIMARY KEY,
    test_event_id       TEXT NOT NULL REFERENCES test_event(test_event_id),
    program_version_id  TEXT NOT NULL REFERENCES program_version(program_version_id),
    snapshot_id         TEXT NOT NULL REFERENCES fact_snapshot(snapshot_id),
    test_date           TEXT NOT NULL,
    status              TEXT NOT NULL
                        CHECK (status IN ('pass','fail','indeterminate','not_applicable')),
    actual              REAL,
    threshold           REAL,
    comparator          TEXT,
    headroom_pct        REAL,
    trace               TEXT NOT NULL,          -- JSON: the evaluated tree
    gaps                TEXT NOT NULL,          -- JSON: what was missing, if anything
    engine_version      TEXT NOT NULL,
    computed_at         TEXT NOT NULL,
    superseded_by       TEXT REFERENCES evaluation(evaluation_id),
    -- A result without a number is only legitimate when nothing was computable.
    CHECK (status IN ('indeterminate','not_applicable') OR actual IS NOT NULL)
);

-- ===========================================================================
-- Breach lifecycle. A FAIL is not a default; this is a separate state machine
-- consuming breach events, deliberately outside the interpreter.
-- ===========================================================================

CREATE TABLE breach (
    breach_id           TEXT PRIMARY KEY,
    evaluation_id       TEXT NOT NULL REFERENCES evaluation(evaluation_id),
    opened_at           TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'open'
                        CHECK (state IN ('open','cured','waived','defaulted','withdrawn')),
    closed_at           TEXT
);

CREATE TABLE cure_event (
    cure_id             TEXT PRIMARY KEY,
    breach_id           TEXT NOT NULL REFERENCES breach(breach_id),
    cure_type           TEXT NOT NULL CHECK (cure_type IN ('equity_cure','grace_period')),
    amount              REAL,
    applied_at          TEXT NOT NULL,
    applied_by          TEXT NOT NULL,
    document_id         TEXT REFERENCES document(document_id)
);

CREATE TABLE waiver (
    waiver_id           TEXT PRIMARY KEY,
    breach_id           TEXT NOT NULL REFERENCES breach(breach_id),
    granted_at          TEXT NOT NULL,
    granted_by          TEXT NOT NULL,
    expires_at          TEXT,
    document_id         TEXT REFERENCES document(document_id)
);

-- ===========================================================================
-- Indexes for the access patterns that actually happen.
-- ===========================================================================

CREATE INDEX idx_pv_agreement       ON program_version (agreement_id, effective_from);
CREATE INDEX idx_definition_pv      ON definition (program_version_id);
CREATE INDEX idx_covenant_pv        ON covenant (program_version_id);
CREATE INDEX idx_dep_name           ON covenant_dependency (dependency_name);
CREATE INDEX idx_flow_symbol        ON fact_flow (symbol, period_end);
CREATE INDEX idx_snapshot_borrower  ON fact_snapshot (borrower_id, test_date);
CREATE INDEX idx_test_event_due     ON test_event (state, certificate_due);
CREATE INDEX idx_eval_event         ON evaluation (test_event_id, computed_at);
CREATE INDEX idx_eval_status        ON evaluation (status) WHERE superseded_by IS NULL;
CREATE INDEX idx_breach_state       ON breach (state);
