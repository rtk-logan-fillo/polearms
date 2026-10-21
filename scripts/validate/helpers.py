"""Issue reporting shared by the validators, so they all report the same way."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator, validators
from referencing import Registry, Resource

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    target: str
    step: str
    severity: str
    message: str


def error(target: str, step: str, message: str) -> Issue:
    return Issue(target, step, SEVERITY_ERROR, message)


def warning(target: str, step: str, message: str) -> Issue:
    return Issue(target, step, SEVERITY_WARNING, message)


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == SEVERITY_ERROR for i in issues)


def report(title: str, issues: list[Issue]) -> None:
    errors = sum(1 for i in issues if i.severity == SEVERITY_ERROR)
    warnings = len(issues) - errors
    status = "ok" if not issues else f"{errors} error(s), {warnings} warning(s)"
    print(f"{title}: {status}")
    for i in issues:
        print(f"  {i.severity.upper():7} [{i.step}] {i.target}: {i.message}")


def exit_if_errors(issues: list[Issue]) -> None:
    """Exit 1 if there are any errors; warnings alone do not fail the run."""
    if has_errors(issues):
        sys.exit(1)


# ---------------------------------------------------------------------------
# JSON Schema validation of the YAML files
# ---------------------------------------------------------------------------

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"
STEP_JSON_SCHEMA = "json-schema"


def load_json_schema(name: str) -> dict:
    return json.loads((SCHEMAS_DIR / name).read_text())


def _strict_integer(_checker, value) -> bool:
    """JSON Schema calls 1.0 an integer, but YAML parses 1.0 as a float, which a typed int rejects."""
    return isinstance(value, int) and not isinstance(value, bool)


# Draft 2020-12 with a stricter "integer" type, so class_uid: 1.0 is not accepted.
StrictValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", _strict_integer),
)


def _registry() -> Registry:
    """All the schemas in schemas/, so a $ref from one to another resolves locally."""
    resources = []
    for path in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        contents = json.loads(path.read_text())
        resources.append((contents["$id"], Resource.from_contents(contents)))
    return Registry().with_resources(resources)


def _location(error) -> str:
    """Where in the document an error is, e.g. 'mappings[3].mapper.fn'."""
    out = ""
    for part in error.absolute_path:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "<document>"


def _describe(error) -> str:
    if error.validator == "additionalProperties":
        # jsonschema lists every unknown key in the message; name them for a clear error
        schema_props = error.schema.get("properties", {})
        unknown = sorted(k for k in error.instance if k not in schema_props)
        return f"unknown key(s) {', '.join(repr(k) for k in unknown)}"
    if error.validator == "not" and "required" in error.validator_value.get("not", error.validator_value):
        # `not: {required: [k]}` forbids key k here, e.g. join on a list-item swords path.
        forbidden = error.validator_value.get("required", [])
        return f"{', '.join(repr(k) for k in forbidden)} is not allowed when the swords path is a list item"
    if error.validator == "pattern":
        # The raw regex is unreadable; the schema's description says what the value should be.
        return f"{error.instance!r} is not valid: expected {error.schema.get('description', 'a different format')}"
    if error.validator == "required":
        return error.message.replace(" is a required property", " is required")
    return error.message


def validate_against_schema(instance, schema_name: str, target: str) -> list[Issue]:
    """Check a parsed YAML document against schemas/<schema_name>; one issue per violation.

    A mapping needing a mapper, or a [key] needing a label, are rules a schema can't express in
    isolation and are checked elsewhere; this covers the structure: required and unknown keys,
    value types, and the conditional rules JSON Schema can state.
    """
    validator = StrictValidator(load_json_schema(schema_name), registry=_registry())
    issues = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(map(str, e.absolute_path))):
        where = _location(err)
        issues.append(error(
            f"{target}:{where}" if where != "<document>" else target,
            STEP_JSON_SCHEMA, _describe(err)))
    return issues
