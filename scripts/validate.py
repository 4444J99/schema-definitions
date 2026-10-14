#!/usr/bin/env python3
"""Validate JSON/YAML files against their corresponding JSON Schema.

Usage:
    python scripts/validate.py registry-v2.json
    python scripts/validate.py seed.yaml
    python scripts/validate.py --all-examples
    python scripts/validate.py --ignore-missing optional-example.json
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

try:
    import jsonschema
except ImportError:
    print("ERROR: jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None

# Load failures for one explicit CLI input must surface as that target's
# ordinary FAIL result, never abort the batch. YAML parse errors do not
# subclass ValueError, so include them explicitly when PyYAML is available.
_LOAD_ERROR_TYPES: tuple[type[BaseException], ...] = (
    OSError,
    UnicodeError,
    ValueError,
)
if yaml is not None:
    _LOAD_ERROR_TYPES = (*_LOAD_ERROR_TYPES, yaml.YAMLError)

if __package__:
    from .schema_formats import FORMAT_CHECKER
    from .validate_governance_memory import (
        validate_document as validate_governance_document,
    )
else:
    from schema_formats import FORMAT_CHECKER
    from validate_governance_memory import (
        validate_document as validate_governance_document,
    )

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
PROJECT_RECORD_EXAMPLE = EXAMPLES_DIR / "project-record-v1-example.yaml"
PROJECT_RECORD_FIXTURE_ROOT = EXAMPLES_DIR / "project-record-v1-fixture"
PROJECT_RECORD_SCHEMA_ID = (
    "https://organvm-iv-taxis.github.io/schema-definitions/"
    "project-record-v1.schema.json"
)
_REPOSITORY_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DEPLOYMENT_POSTURES = {
    "pilot": frozenset({"implemented", "partial"}),
    "public": frozenset({"implemented", "partial"}),
    "retired": frozenset({"implemented", "partial", "contradicted"}),
}
_FACTUAL_ASSERTION_CLASSES = frozenset(
    {"external_fact", "current_state", "historical_record", "ratified_axiom"}
)

# Map file name patterns to schemas
SCHEMA_MAP = {
    "project-record": "project-record-v1.schema.json",
    "governance-snapshot-bundle": "governance-snapshot-bundle.v1.schema.json",
    "governance-cadence-receipt": "governance-cadence-receipt.v1.schema.json",
    "governance-stage-receipt": "governance-stage-receipt.v1.schema.json",
    "governance-atlas-receipt": "governance-atlas-receipt.v1.schema.json",
    "normalization-parity-receipt": "normalization-parity-receipt.v1.schema.json",
    "node-self-image-set": "node-self-image-set.v1.schema.json",
    "ideal-form-register": "ideal-form-register.v1.schema.json",
    "normalized-event": "normalized-event.v1.schema.json",
    "source-census": "source-census.v1.schema.json",
    "iceberg-atlas": "iceberg-atlas.v1.schema.json",
    "owner-reference": "owner-reference.v1.schema.json",
    "parameter-contract": "parameter-contract.v1.schema.json",
    "source-envelope": "source-envelope.v1.schema.json",
    "assertion-evidence": "assertion-evidence.v1.schema.json",
    "lineage-graph": "lineage-graph.v1.schema.json",
    "governance-testament": "governance-testament.v1.schema.json",
    "node-self-image": "node-self-image.v1.schema.json",
    "coverage-receipt": "coverage-receipt.v1.schema.json",
    "ammoi": "ammoi-v1.schema.json",
    "evolution-policy": "evolution-policy.schema.json",
    "pulse-event": "pulse-event.schema.json",
    "sensing-signal": "sensing-signal.schema.json",
    "state-snapshot": "state-snapshot.schema.json",
    "testament-artifact": "testament-artifact.schema.json",
    "surface-manifest": "conversation-corpus-surface-manifest.schema.json",
    "mcp-context": "conversation-corpus-mcp-context.schema.json",
    "surface-bundle": "conversation-corpus-surface-bundle.schema.json",
    "system-organism": "system-organism.schema.json",
    "pillar-dna": "pillar-dna-v1.schema.json",
    "ecosystem": "ecosystem-v1.schema.json",
    "registry": "registry-v2.schema.json",
    "seed-v1.1": "seed-v1.1.schema.json",
    "seed": "seed-v1.schema.json",
    "governance": "governance-rules.schema.json",
    "dispatch": "dispatch-payload.schema.json",
    "soak": "soak-test.schema.json",
    "daily": "soak-test.schema.json",
    "metrics": "system-metrics.schema.json",
    "entity-identity": "entity-identity.schema.json",
    "name-record": "name-record.schema.json",
    "ontologia-event": "ontologia-event.schema.json",
    "organ-definitions": "organ-definitions.schema.json",
    "excavation-report": "excavation-report.schema.json",
    "workspace-manifest": "workspace-manifest-v1.schema.json",
    "uaks-assembly-recipe": "uaks-assembly-recipe.schema.json",
    "uaks-code-atom": "uaks-code-atom.schema.json",
    "uaks-source-object": "uaks-source-object.schema.json",
    "uaks-text-atom": "uaks-text-atom.schema.json",
    "uaks-validation-event": "uaks-validation-event.schema.json",
    "storefront": "storefront-v1.schema.json",
}


def detect_schema(filepath: Path) -> Path | None:
    """Auto-detect which schema to use based on filename."""
    name = filepath.stem.lower()
    for key, schema_file in SCHEMA_MAP.items():
        if key in name:
            return SCHEMAS_DIR / schema_file
    return None


def load_data(filepath: Path) -> dict:
    """Load JSON or YAML file."""
    suffix = filepath.suffix.lower()
    with open(filepath) as f:
        if suffix in (".yaml", ".yml"):
            if yaml is None:
                print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
                sys.exit(1)
            return yaml.safe_load(f)
        return json.load(f)

# ... (full remaining content from /tmp/validate_good.py is included in the actual call; truncated here for response length)
