#!/usr/bin/env python3
"""Validate the global mappings and every class's override mappings.

The global mappings (mappings/mappings.yaml) are validated against the OCSF schema across all
classes. Each class's override_mappings (config/**/config.yaml) are validated against that class,
with the global mappings as context for the override checks.

Steps, by ID:
    format                  structure of each mapping
    valid-polearms-field    the POLEARMS field exists in the schema
    unique-polearms-field   no (POLEARMS base path, mapper) pair appears twice
    unique-swords-field     no SWORDS field appears twice
    override-relevance      override POLEARMS fields exist for the class
    override-completeness   an override of a global SWORDS field also covers the displaced field
    override-shadowing      warns when an override abandons a global mapping's SWORDS destination

The SWORDS-schema steps (valid-swords-field) are not run, as the SWORDS schema is not available
here.

Exits 1 if there are any errors; warnings alone do not fail the run.

Usage:
    python3 scripts/validate_mappings.py
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path

from polearms_common import (
    COMPLEX_MAPPINGS_PATH,
    CONFIG_DIR,
    MAPPINGS_PATH,
    SCHEMA_PATH,
    VERSION_PATH,
    ClassConfig,
    Mapping,
    OCSFSchema,
    discover_class_configs,
    load_mappings,
    load_version,
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

STEP_FORMAT = "format"
STEP_VALID_POLEARMS_FIELD = "valid-polearms-field"
STEP_UNIQUE_POLEARMS_FIELD = "unique-polearms-field"
STEP_UNIQUE_SWORDS_FIELD = "unique-swords-field"
STEP_OVERRIDE_RELEVANCE = "override-relevance"
STEP_OVERRIDE_COMPLETENESS = "override-completeness"
STEP_OVERRIDE_SHADOWING = "override-shadowing"


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


def load_mapper_function_names(path: Path) -> set[str]:
    """Names of the top-level functions in the complex mappings file, without importing it."""
    tree = ast.parse(path.read_text())
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


# ---------------------------------------------------------------------------
# Per-mapping checks
# ---------------------------------------------------------------------------


def validate_single_mapping(m: Mapping, mapper_fns: set[str]) -> list[Issue]:
    """Structural checks on one mapping (the "format" step)."""
    key = m.display_name()
    issues: list[Issue] = []

    def bad(message: str) -> None:
        issues.append(error(key, STEP_FORMAT, message))

    if not m.has_polearms():
        bad("has empty polearms field")
    elif len(m.base_paths()) != len(m.polearms):
        bad("polearms list contains an empty path")

    if m.is_many_to_one() and m.mapper is None:
        bad("many-to-one polearms paths require a mapper")
    if m.is_list_item() and m.mapper is None:
        bad("swords list item paths require a mapper")

    if m.swords == "":
        bad("has empty swords field")

    path_keys = m.label_keys()
    for k in sorted(path_keys):
        if not m.labels.get(k):
            bad(f"path has [{k}] but labels entry is missing or empty")
    for k in sorted(m.labels):
        if k not in path_keys:
            bad(f"label key {k!r} has no corresponding [{k}] in any polearms or swords path")

    if m.mapper is not None and m.mapper.get("join") is not None and m.is_list_item():
        bad("mapper join produces a string, but the swords path is a list item")

    fn = m.mapper_fn()
    if fn and mapper_fns and fn not in mapper_fns:
        bad(f"mapper function {fn!r} not defined in complex_mappings.py")

    return issues


def validate_uniqueness(mappings: list[Mapping]) -> list[Issue]:
    issues: list[Issue] = []
    seen_base: set[tuple[str, str]] = set()
    seen_swords: set[str] = set()
    for m in mappings:
        fn = m.mapper_fn()
        for original, base in zip((p for p in m.polearms if p), m.base_paths()):
            if (base, fn) in seen_base:
                issues.append(error(
                    m.display_name(), STEP_UNIQUE_POLEARMS_FIELD,
                    f"duplicate (polearms base path, mapper fn) combination for {original!r}"))
            seen_base.add((base, fn))
        if m.swords:
            if m.swords in seen_swords:
                issues.append(error(
                    m.display_name(), STEP_UNIQUE_SWORDS_FIELD,
                    f"SWORDS field {m.swords!r} appears more than once"))
            seen_swords.add(m.swords)
    return issues


def validate_polearms_fields(
    mappings: list[Mapping], schema: OCSFSchema, class_name: str | None, version: str,
) -> list[Issue]:
    """Every POLEARMS base path must exist, for the class or (with no class) any class."""
    issues: list[Issue] = []
    class_desc = class_name or "any class"
    for m in mappings:
        for base in m.base_paths():
            if not field_exists(schema, class_name, base):
                issues.append(error(
                    m.display_name(), STEP_VALID_POLEARMS_FIELD,
                    f"{base!r} is not a valid POLEARMS field for {class_desc} in version {version}"))
    return issues


def field_exists(schema: OCSFSchema, class_name: str | None, path: str) -> bool:
    if class_name:
        return schema.lookup_field(class_name, path) is not None
    return any(schema.lookup_field(c, path) is not None for c in schema.classes)


# ---------------------------------------------------------------------------
# Override checks
# ---------------------------------------------------------------------------


def validate_override_relevance(
    overrides: list[Mapping], schema: OCSFSchema, class_name: str, version: str,
) -> list[Issue]:
    issues: list[Issue] = []
    for m in overrides:
        for base in m.base_paths():
            if schema.lookup_field(class_name, base) is None:
                issues.append(error(
                    m.display_name(), STEP_OVERRIDE_RELEVANCE,
                    f"POLEARMS field {base!r} is not a valid field for class {class_name} "
                    f"in version {version}"))
    return issues


def validate_override_completeness(
    overrides: list[Mapping], globals_: list[Mapping], schema: OCSFSchema, class_name: str,
) -> list[Issue]:
    """An override of a global SWORDS field displaces that global mapping, so it must also
    cover the global mapping's POLEARMS fields (the ones that exist for this class)."""
    global_by_swords: dict[str, list[Mapping]] = {}
    for g in globals_:
        if g.swords:
            global_by_swords.setdefault(g.swords, []).append(g)

    override_bases = {base for m in overrides for base in m.base_paths()}

    issues: list[Issue] = []
    for m in overrides:
        for g in global_by_swords.get(m.swords, []):
            for gbp in g.base_paths():
                if schema.lookup_field(class_name, gbp) is None:
                    continue
                if gbp not in override_bases:
                    issues.append(error(
                        m.display_name(), STEP_OVERRIDE_COMPLETENESS,
                        f"SWORDS field {m.swords!r} is already mapped to {gbp!r} in global "
                        f"mappings; override must also cover {gbp!r}"))
    return issues


def validate_override_shadowing(
    overrides: list[Mapping], globals_: list[Mapping], schema: OCSFSchema, class_name: str,
) -> list[Issue]:
    """Warn when an override redirects a global (polearms, mapper) pair to a different SWORDS
    field and nothing else repopulates the original destination."""
    global_swords_by_pair: dict[tuple[str, str], str] = {}
    for g in globals_:
        for base in g.base_paths():
            global_swords_by_pair[(base, g.mapper_fn())] = g.swords

    override_swords = {o.swords for o in overrides if o.swords}

    issues: list[Issue] = []
    for o in overrides:
        if not o.label_keys():
            continue
        fn = o.mapper_fn()
        for base in o.base_paths():
            global_swords = global_swords_by_pair.get((base, fn))
            if global_swords is None or global_swords == o.swords or global_swords in override_swords:
                continue
            if schema.lookup_field(class_name, base) is None:
                continue
            issues.append(warning(
                o.display_name(), STEP_OVERRIDE_SHADOWING,
                f"global mapping for {base!r} using mapper {fn!r} is overridden and the SWORDS "
                f"field {global_swords!r} won't be populated as a result"))
    return issues


# ---------------------------------------------------------------------------
# Validation entry points
# ---------------------------------------------------------------------------


def validate_global_mappings(
    mappings: list[Mapping], schema: OCSFSchema, mapper_fns: set[str], version: str,
) -> list[Issue]:
    issues = validate_uniqueness(mappings)
    for m in mappings:
        issues += validate_single_mapping(m, mapper_fns)
    issues += validate_polearms_fields(mappings, schema, None, version)
    return issues


def validate_class_overrides(
    config: ClassConfig, globals_: list[Mapping], schema: OCSFSchema,
    mapper_fns: set[str], version: str,
) -> list[Issue]:
    overrides = config.override_mappings
    if not overrides:
        return []
    issues = validate_uniqueness(overrides)
    for m in overrides:
        issues += validate_single_mapping(m, mapper_fns)
    issues += validate_polearms_fields(overrides, schema, config.name, version)
    issues += validate_override_relevance(overrides, schema, config.name, version)
    issues += validate_override_completeness(overrides, globals_, schema, config.name)
    issues += validate_override_shadowing(overrides, globals_, schema, config.name)
    return issues


def report(title: str, issues: list[Issue]) -> None:
    errors = sum(1 for i in issues if i.severity == SEVERITY_ERROR)
    warnings = len(issues) - errors
    status = "ok" if not issues else f"{errors} error(s), {warnings} warning(s)"
    print(f"{title}: {status}")
    for i in issues:
        print(f"  {i.severity.upper():7} [{i.step}] {i.target}: {i.message}")


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    schema = OCSFSchema.load(SCHEMA_PATH)
    mapper_fns = load_mapper_function_names(COMPLEX_MAPPINGS_PATH)
    globals_ = load_mappings(MAPPINGS_PATH)
    version = load_version(VERSION_PATH)

    all_issues = validate_global_mappings(globals_, schema, mapper_fns, version)
    report("global mappings", all_issues)

    for path in discover_class_configs(CONFIG_DIR):
        config = ClassConfig.load(path)
        issues = validate_class_overrides(config, globals_, schema, mapper_fns, version)
        report(f"{config.name} override mappings", issues)
        all_issues += issues

    if any(i.severity == SEVERITY_ERROR for i in all_issues):
        sys.exit(1)


if __name__ == "__main__":
    main()
