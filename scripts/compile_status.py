#!/usr/bin/env python3
"""Say whether schema/schema.json needs to be recompiled from schema/schema_definition.yaml.

schema.json records the OCSF version it was built from (its top-level "version") and the Arctic
Wolf extension's version (extensions.arcticwolf.version). If either differs from the version the
definition asks for, or the schema doesn't record one, the schema is out of date.

Prints a line such as "needs_compile=true" so that a workflow can append the output to
$GITHUB_OUTPUT, and explains the reason on stderr.

Usage:
    python3 -m scripts.compile_status >> "$GITHUB_OUTPUT"
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.common import SCHEMA_DEFINITION_PATH, SCHEMA_PATH, definition_version, load_definition

ARCTICWOLF_EXTENSION = "arcticwolf"


def compiled_versions(schema: dict) -> dict[str, str | None]:
    """The versions a compiled schema.json says it was built from."""
    extension = (schema.get("extensions") or {}).get(ARCTICWOLF_EXTENSION) or {}
    version, extension_version = schema.get("version"), extension.get("version")
    return {
        "ocsf": None if version is None else str(version),
        "arcticwolf": None if extension_version is None else str(extension_version),
    }


def stale_reasons(schema: dict, definition: dict) -> list[str]:
    """Why schema.json is out of date with the definition; empty if it is current."""
    wanted = {
        "ocsf": definition_version(definition, "ocsf"),
        "arcticwolf": definition_version(definition, "arcticwolf_extension"),
    }
    have = compiled_versions(schema)
    reasons = []
    for name in ("ocsf", "arcticwolf"):
        if wanted[name] is None:
            reasons.append(f"the definition does not name a {name} version")
        elif have[name] != wanted[name]:
            reasons.append(f"{name}: schema.json has {have[name]!r}, the definition wants {wanted[name]!r}")
    return reasons


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    definition = load_definition(SCHEMA_DEFINITION_PATH)
    try:
        schema = json.loads(SCHEMA_PATH.read_text())
    except FileNotFoundError:
        schema = {}                      # no schema yet: it has to be compiled
    except json.JSONDecodeError as err:
        print(f"{SCHEMA_PATH.name} is not valid JSON ({err}); it has to be recompiled", file=sys.stderr)
        schema = {}

    reasons = stale_reasons(schema, definition)
    for reason in reasons:
        print(f"schema.json is out of date: {reason}", file=sys.stderr)
    if not reasons:
        print("schema.json already matches the definition", file=sys.stderr)
    print(f"needs_compile={'true' if reasons else 'false'}")


if __name__ == "__main__":
    main()
