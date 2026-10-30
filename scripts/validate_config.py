#!/usr/bin/env python3
"""Validate every class config under config/ against schema/schema.json.

Steps, by ID:
    json-schema             the YAML matches its JSON Schema (scripts/schemas/)
    valid-class-name        class_name is a class in the schema
    valid-class-uid         class_uid is present and equals the schema's uid for that class
    valid-essential-field   every essential field exists in that class

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
        if schema.lookup_field(class_name, path) is None:
            issues.append(error(class_name, STEP_VALID_ESSENTIAL_FIELD,
                                f"essential field {path!r} is not a field of class {class_name}"))
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
