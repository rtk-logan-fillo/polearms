#!/usr/bin/env python3
"""Validate every class config under config/ against schema/schema.json.

Steps, by ID:
    json-schema             the YAML matches its JSON Schema (scripts/schemas/)
    valid-class-name        class_name is a class in the schema
    valid-class-uid         class_uid is present and equals the schema's uid for that class
    valid-essential-field   every essential field exists in that class
    essential-field-arrays  every array the path passes through is written with [], and nothing
                            else is: attacks[].tactic.src_url, not attacks.tactic.src_url. A final
                            array of primitives may be written with or without [].

Exits 1 if there are any errors.

Usage:
    python3 -m scripts.validate_config
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from scripts.common import CONFIG_DIR, SCHEMA_PATH, OCSFSchema, discover_class_configs
from scripts.validate_helpers import Issue, error, exit_if_errors, report, validate_against_schema

STEP_VALID_CLASS_NAME = "valid-class-name"
STEP_VALID_CLASS_UID = "valid-class-uid"
STEP_VALID_ESSENTIAL_FIELD = "valid-essential-field"
STEP_ESSENTIAL_FIELD_ARRAYS = "essential-field-arrays"


def array_path_problem(path: str, flags: list[bool]) -> str | None:
    """The path as it must be written, or None if it is already right.

    Every array the path passes through needs [] (attacks[].tactic.uid), and a segment that is not
    an array must not have it. The last segment, when it is an array of primitives, may have either.
    """
    parts = path.split(".")
    expected = []
    for i, (part, is_array) in enumerate(zip(parts, flags)):
        name = part.split("[", 1)[0]
        last = i == len(parts) - 1
        if last and is_array and part in (name, name + "[]"):
            expected.append(part)
        else:
            expected.append(name + ("[]" if is_array else ""))
    expected_path = ".".join(expected)
    return None if expected_path == path else expected_path


def validate_config(raw, schema: OCSFSchema, target: str = "config.yaml") -> list[Issue]:
    """Validate one class config, given as the parsed contents of its config.yaml.

    The structure is checked against the JSON Schema first. If that fails, its errors are the
    result: the semantic checks below need a well-formed config to say anything useful.
    """
    structural = validate_against_schema(raw, "config.schema.json", target)
    if structural:
        return structural

    class_name, class_uid = raw["class_name"], raw["class_uid"]
    issues: list[Issue] = []

    schema_class = schema.classes.get(class_name)
    if schema_class is None:
        return [error(class_name, STEP_VALID_CLASS_NAME,
                      f"class_name {class_name!r} is not a class in schema.json")]

    if class_uid != schema_class.get("uid"):
        issues.append(error(
            class_name, STEP_VALID_CLASS_UID,
            f"class_uid {class_uid} does not match schema.json, where {class_name!r} "
            f"has uid {schema_class.get('uid')}"))

    for entry in raw.get("essential_fields") or []:
        path = entry["polearms"]
        flags = schema.array_segments(class_name, path)
        if flags is None:
            issues.append(error(class_name, STEP_VALID_ESSENTIAL_FIELD,
                                f"essential field {path!r} is not a field of class {class_name}"))
            continue
        expected = array_path_problem(path, flags)
        if expected is not None:
            issues.append(error(class_name, STEP_ESSENTIAL_FIELD_ARRAYS,
                                f"essential field {path!r} must be written {expected!r}"))
    return issues


def load_raw_config(path: Path):
    return yaml.safe_load(path.read_text())


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    schema = OCSFSchema.load(SCHEMA_PATH)

    all_issues: list[Issue] = []
    for path in discover_class_configs(CONFIG_DIR):
        raw = load_raw_config(path)
        relative = path.relative_to(CONFIG_DIR).as_posix()
        issues = validate_config(raw, schema, target=relative)
        name = raw.get("class_name") if isinstance(raw, dict) else None
        title = f"{name or path.parent.relative_to(CONFIG_DIR)} config"
        report(title, issues)
        all_issues += issues

    exit_if_errors(all_issues)


if __name__ == "__main__":
    main()
