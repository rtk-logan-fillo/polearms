#!/usr/bin/env python3
"""Validate schema/schema_definition.yaml against its JSON Schema.

Only the file's structure is checked: the two sections, and that each version is a quoted
semantic-version string. The versions are not compared with anything; the validate-and-compile-schema workflow
builds schema.json from whatever versions this file names.

Steps, by ID:
    json-schema             schema_definition.yaml matches its JSON Schema
                            (scripts/validate/schemas/schema_definition.schema.json)

Exits 1 if there are any errors.

Usage:
    python3 -m scripts.validate.schema_definition
"""

from __future__ import annotations

import argparse

import yaml

from scripts.common import SCHEMA_DEFINITION_PATH
from scripts.validate.helpers import Issue, exit_if_errors, report, validate_against_schema


def validate_schema_definition(raw, target: str = "schema_definition.yaml") -> list[Issue]:
    """Check the parsed contents of schema_definition.yaml against its JSON Schema."""
    return validate_against_schema(raw, "schema_definition.schema.json", target)


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    raw = yaml.safe_load(SCHEMA_DEFINITION_PATH.read_text())
    issues = validate_schema_definition(raw, SCHEMA_DEFINITION_PATH.name)
    report("schema definition", issues)
    exit_if_errors(issues)


if __name__ == "__main__":
    main()
