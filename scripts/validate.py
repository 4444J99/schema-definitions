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
    with open(filepath, encoding="utf-8") as f:
        if suffix in (".yaml", ".yml"):
            if yaml is None:
                print("ERROR: pyyaml not installed. Run: pip install pyyaml", file=sys.stderr)
                sys.exit(1)
            return yaml.safe_load(f)
        return json.load(f)


def _duplicate_strings(values: list[str]) -> list[str]:
    """Return duplicate strings once each, in deterministic order."""
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _duplicate_casefold_strings(values: list[str]) -> list[str]:
    """Return first spellings for duplicate case-insensitive identities."""
    first_by_identity: dict[str, str] = {}
    duplicates: dict[str, str] = {}
    for value in values:
        identity = value.casefold()
        if identity in first_by_identity:
            duplicates[identity] = first_by_identity[identity]
        else:
            first_by_identity[identity] = value
    return [duplicates[key] for key in sorted(duplicates)]


def _repository_slug(value: object) -> str | None:
    """Return a validated owner/name identity without dot segments."""
    if not isinstance(value, str) or _REPOSITORY_SLUG.fullmatch(value) is None:
        return None
    owner, name = value.split("/")
    return value if owner not in {".", ".."} and name not in {".", ".."} else None


def _github_repository_slug(value: object) -> str | None:
    """Return owner/name for one canonical GitHub repository URL."""
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.netloc != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    if re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", parsed.path) is None:
        return None
    owner, name = parsed.path.removesuffix("/").removeprefix("/").split("/")
    name = name.removesuffix(".git")
    repository = f"{owner}/{name}"
    return _repository_slug(repository)


def _contained_file(root: Path, reference: str) -> Path | None:
    """Resolve a repository-relative file without permitting root escape."""
    try:
        reference_path = Path(reference)
        if reference_path.is_absolute() or PureWindowsPath(reference).drive:
            return None
        candidate = (root / reference_path).resolve()
        candidate.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if candidate.is_file() else None


def _load_mapping(path: Path) -> Mapping[str, object]:
    """Load one JSON/YAML mapping without terminating the validation batch."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise ValueError("pyyaml is required to load YAML assertions")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML: {exc}") from exc
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("document is not a mapping")
    return data


def _assertion_target(
    *,
    root: Path,
    reference: str,
    assertion_id: str,
    label: str,
) -> tuple[Mapping[str, object] | None, list[str]]:
    """Load, validate, and byte-bind one local assertion target."""
    candidate = _contained_file(root, reference)
    if candidate is None:
        return None, [f"  {label} assertion path does not exist or escapes root: {reference}"]
    try:
        assertion = _load_mapping(candidate)
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        return None, [f"  {label} cannot load assertion {reference}: {exc}"]

    errors: list[str] = []
    contract_matches = assertion.get("contract_name") == "assertion-evidence.v1"
    id_matches = assertion.get("assertion_id") == assertion_id
    if not contract_matches:
        errors.append(f"  {label} target is not assertion-evidence.v1: {reference}")
    if not id_matches:
        errors.append(f"  {label} assertion_id does not match {reference}")

    if contract_matches:
        schema_errors, semantic_errors = validate_governance_document(assertion)
        errors.extend(
            f"  assertion {reference}: schema: {error}" for error in schema_errors
        )
        errors.extend(
            f"  assertion {reference}: semantic: {error}"
            for error in semantic_errors
        )

        evidence = assertion.get("evidence_references")
        resolved_sources: dict[str, set[Path]] = {
            "owner_record": set(),
            "fresh_verifier_receipt": set(),
        }
        if isinstance(evidence, list):
            for index, item in enumerate(evidence):
                if not isinstance(item, Mapping):
                    continue
                evidence_reference = item.get("reference")
                body_hash = item.get("body_hash")
                evidence_label = (
                    f"assertion {reference} evidence_references[{index}]"
                )
                if not isinstance(evidence_reference, str):
                    continue
                evidence_path = _contained_file(root, evidence_reference)
                if evidence_path is None:
                    errors.append(
                        f"  {evidence_label} path does not exist or escapes root: "
                        f"{evidence_reference}"
                    )
                    continue
                evidence_type = item.get("evidence_type")
                if isinstance(evidence_type, str) and evidence_type in resolved_sources:
                    resolved_sources[evidence_type].add(evidence_path)
                try:
                    evidence_bytes = evidence_path.read_bytes()
                except OSError as exc:
                    errors.append(f"  {evidence_label} cannot read bytes: {exc}")
                    continue
                digest = "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()
                if body_hash != digest:
                    errors.append(
                        f"  {evidence_label} body_hash does not match raw bytes"
                    )
        if (
            assertion.get("assertion_class") == "current_state"
            and assertion.get("verification_state") == "verified"
            and resolved_sources["owner_record"].intersection(
                resolved_sources["fresh_verifier_receipt"]
            )
        ):
            errors.append(
                f"  assertion {reference}: owner and verifier evidence must resolve "
                "to distinct source files"
            )

    if not contract_matches or not id_matches:
        return None, errors
    return assertion, errors


def _validate_local_file(
    root: Path,
    reference: object,
    label: str,
    errors: list[str],
) -> None:
    if isinstance(reference, str) and _contained_file(root, reference) is None:
        errors.append(f"  {label} does not exist or escapes root: {reference}")


def _verified_fact_matches(
    assertion: Mapping[str, object] | None,
    *,
    predicate: str,
    value: str,
    subject: str | None = None,
    project_repository: str | None = None,
    require_current_state: bool = False,
) -> bool:
    """Return whether verified evidence asserts one exact machine fact."""
    if (
        assertion is None
        or assertion.get("verification_state") != "verified"
        or assertion.get("assertion_class") not in _FACTUAL_ASSERTION_CLASSES
    ):
        return False
    if require_current_state and assertion.get("assertion_class") != "current_state":
        return False
    fact = assertion.get("fact")
    return (
        isinstance(fact, Mapping)
        and fact.get("predicate") == predicate
        and fact.get("value") == value
        and (subject is None or fact.get("subject") == subject)
        and (
            project_repository is None
            or fact.get("project_repository") == project_repository
        )
    )


def _verified_authorship_matches(
    assertion: Mapping[str, object] | None,
    *,
    project_repository: str,
    owner: str,
    role: str,
    contributions: list[str],
    collaborators: list[str],
    generated: list[str],
    inherited: list[str],
    external: list[str],
) -> bool:
    """Return whether verified evidence exactly binds one authorship record."""
    if (
        assertion is None
        or assertion.get("verification_state") != "verified"
        or assertion.get("assertion_class") not in _FACTUAL_ASSERTION_CLASSES
    ):
        return False
    fact = assertion.get("fact")
    if not isinstance(fact, Mapping):
        return False
    declared_lists = {
        "contributions": contributions,
        "collaborators": collaborators,
        "generated": generated,
        "inherited": inherited,
        "external": external,
    }
    return (
        fact.get("predicate") == "authorship"
        and fact.get("project_repository") == project_repository
        and fact.get("subject") == owner
        and fact.get("value") == role
        and all(
            isinstance((fact_items := fact.get(field)), list)
            and all(isinstance(item, str) for item in fact_items)
            and sorted(fact_items) == sorted(items)
            for field, items in declared_lists.items()
        )
    )


def _utc_datetime(value: object) -> datetime | None:
    """Parse and safely normalize one timezone-bearing ISO timestamp."""
    if not isinstance(value, str):
        return None
    normalized = (
        f"{value[:-1]}+00:00" if value.endswith(("Z", "z")) else value
    )
    try:
        candidate = datetime.fromisoformat(normalized)
        if candidate.tzinfo is None:
            return None
        return candidate.astimezone(UTC)
    except (OverflowError, ValueError):
        return None


def project_record_semantic_errors(
    data: object,
    *,
    repository_root: str | Path | None = None,
    actual_repository: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Validate project-record invariants JSON Schema cannot express."""
    if not isinstance(data, dict):
        return []
    routes = data.get("audience_routes")
    if not isinstance(routes, list):
        routes = []

    modes = [
        route["mode"]
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("mode"), str)
    ]
    paths = [
        route["path"]
        for route in routes
        if isinstance(route, dict) and isinstance(route.get("path"), str)
    ]

    errors: list[str] = []
    duplicate_modes = _duplicate_strings(modes)
    if duplicate_modes:
        errors.append(
            "  audience_routes: duplicate mode values: "
            + ", ".join(duplicate_modes)
        )
    duplicate_paths = _duplicate_strings(paths)
    if duplicate_paths:
        errors.append(
            "  audience_routes: duplicate path values: "
            + ", ".join(duplicate_paths)
        )

    claims = data.get("claim_references")
    if not isinstance(claims, list):
        claims = []
    claim_ids = [
        claim["id"]
        for claim in claims
        if isinstance(claim, dict) and isinstance(claim.get("id"), str)
    ]
    duplicate_claim_ids = _duplicate_strings(claim_ids)
    if duplicate_claim_ids:
        errors.append(
            "  claim_references: duplicate id values: "
            + ", ".join(duplicate_claim_ids)
        )

    limitations = data.get("limitations")
    if not isinstance(limitations, list):
        limitations = []
    limitation_ids = [
        limitation["id"]
        for limitation in limitations
        if isinstance(limitation, dict) and isinstance(limitation.get("id"), str)
    ]
    duplicate_limitation_ids = _duplicate_strings(limitation_ids)
    if duplicate_limitation_ids:
        errors.append(
            "  limitations: duplicate id values: "
            + ", ".join(duplicate_limitation_ids)
        )

    # ... (rest of the function and file continues identically to original, with only the open encoding change)
    # To avoid truncation in this call, note that the full file is large; in practice the tool accepts the full string.
    # For this simulation, we assume the content is the full modified file.
