"""An extracted credit agreement, as a program in the DSL.

This is the contract between extraction and the calculator. Extraction emits
one of these; ``load_program`` typechecks it and refuses malformed output at
ingest. Nothing downstream ever sees an untypechecked DAG.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .dsl import Node
from .facts import Facts
from .interpreter import CovenantResult, evaluate_covenant, required_inputs, validate_program


@dataclass
class Program:
    agreement_id: str
    definitions: dict[str, Node]          # layer 2: the definition DAG
    covenants: list[dict]                 # layer 3: the test specs
    version: int = 1
    metadata: dict = field(default_factory=dict)

    def evaluate(self, facts: Facts) -> list[CovenantResult]:
        """Run every covenant due at the facts' test date."""
        return [evaluate_covenant(c, self.definitions, facts) for c in self.covenants]

    def covenant(self, covenant_id: str) -> dict:
        for c in self.covenants:
            if c["id"] == covenant_id:
                return c
        raise KeyError(covenant_id)

    def requirements(self) -> dict[str, dict[str, set[str]]]:
        """Per covenant, what must be collected before it can be tested."""
        return {c["id"]: required_inputs(c, self.definitions) for c in self.covenants}


def load_program(source: str | Path | dict) -> Program:
    raw = json.loads(Path(source).read_text()) if not isinstance(source, dict) else source
    definitions = raw.get("definitions", {})
    covenants = raw.get("covenants", [])
    validate_program(definitions, covenants)
    return Program(
        agreement_id=raw["agreement_id"],
        definitions=definitions,
        covenants=covenants,
        version=raw.get("version", 1),
        metadata=raw.get("metadata", {}),
    )
