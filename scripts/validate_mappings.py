#!/usr/bin/env python3
"""Validate the global mappings and every class's override mappings.

The global mappings (mappings/swords_mappings.yaml) are validated against the OCSF schema across all
classes. Each class's override_mappings (config/**/config.yaml) are validated against that class,
with the global mappings as context for the override checks.

Steps, by ID:
    json-schema             the YAML matches its JSON Schema (scripts/schemas/)
    selectors               every [key] in a path has a selectors entry with a label, and every
                            selector is used
    mapper-function         the mapper function exists in mappers_and_selectors.py
    selector-function       each selector function exists in mappers_and_selectors.py
    valid-polearms-field    the POLEARMS field exists in the schema
    primitive-polearms-field  the POLEARMS field is a primitive, never an object
    polearms-field-arrays   every array in the POLEARMS path is bracketed, and nothing else is.
                            [] is every non-null item and [N] is item N (attacks[].tactic.uid,
                            evidences[0].dst_endpoint.ip); a labelled [key] (evidences[x].src_endpoint.ip)
                            hands a mapper the whole array and needs one. A final array of
                            primitives may be written with or without one
    result-shape            without a mapper, join and first need a [] or list-returning selector and
                            cannot be combined, a list with neither needs a SWORDS field that is a
                            list, and several paths with no mapper must each give a list
    valid-swords-field     the SWORDS field exists in the SWORDS schema
    unique-polearms-field   no (POLEARMS base path, mapper and selectors) combination appears twice
    unique-swords-field     no SWORDS field appears twice
    override-relevance      override POLEARMS fields exist for the class
    override-completeness   an override of a global SWORDS field also covers the displaced field
    override-shadowing      warns when an override abandons a global mapping's SWORDS destination

The SWORDS schema is downloaded to schema/carser_swords_schema.json if it is not already there
(see scripts/swords_schema.py).

Exits 1 if there are any errors; warnings alone do not fail the run.

Usage:
    python3 -m scripts.validate_mappings
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

import yaml

from scripts.common import (
    MAPPERS_AND_SELECTORS_PATH,
    CONFIG_DIR,
    SWORDS_MAPPINGS_PATH,
    SCHEMA_PATH,
    SWORDS_SCHEMA_PATH,
    VERSION_PATH,
    ClassConfig,
    Mapping,
    OCSFSchema,
    base_path,
    discover_class_configs,
    is_index,
    is_object_field,
    load_mappings,
    load_version,
)
from scripts.validate_helpers import (  # noqa: F401  (re-exported for callers and tests)
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Issue,
    error,
    exit_if_errors,
    report,
    validate_against_schema,
    warning,
)
from scripts.swords_schema import load_swords_schema

STEP_SELECTORS = "selectors"
STEP_SELECTOR_FUNCTION = "selector-function"
STEP_MAPPER_FUNCTION = "mapper-function"
STEP_VALID_POLEARMS_FIELD = "valid-polearms-field"
STEP_PRIMITIVE_POLEARMS_FIELD = "primitive-polearms-field"
STEP_POLEARMS_FIELD_ARRAYS = "polearms-field-arrays"
STEP_RESULT_SHAPE = "result-shape"
STEP_VALID_SWORDS_FIELD = "valid-swords-field"
STEP_UNIQUE_POLEARMS_FIELD = "unique-polearms-field"
STEP_UNIQUE_SWORDS_FIELD = "unique-swords-field"
STEP_OVERRIDE_RELEVANCE = "override-relevance"
STEP_OVERRIDE_COMPLETENESS = "override-completeness"
STEP_OVERRIDE_SHADOWING = "override-shadowing"


def _functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text())
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def load_mapper_function_names(path: Path) -> set[str]:
    """Names of the top-level functions in the mappers and selectors file, without importing it."""
    return {n.name for n in _functions(path)}


def load_list_selector_names(path: Path) -> frozenset[str]:
    """Names of the selector functions annotated to return a list (-> list or -> list[...]). Any
    other selector returns one item, which the executor treats like an index."""
    def returns_list(node) -> bool:
        ann = node.returns
        if isinstance(ann, ast.Subscript):
            ann = ann.value
        return isinstance(ann, ast.Name) and ann.id in ("list", "List")
    return frozenset(n.name for n in _functions(path) if returns_list(n))


# ---------------------------------------------------------------------------
# Per-mapping checks
# ---------------------------------------------------------------------------


def validate_single_mapping(m: Mapping, mapper_fns: set[str]) -> list[Issue]:
    """The checks on one mapping that a JSON Schema can't express: its selectors and the mapper
    and selector functions.

    The structure itself (required keys, types, mapper rules) is the "json-schema" step.
    """
    key = m.display_name()
    issues: list[Issue] = []

    path_keys = m.label_keys()
    for k in sorted(path_keys):
        if not m.labels.get(k):
            issues.append(error(
                key, STEP_SELECTORS, f"path has [{k}] but selectors has no entry for it with a label"))
    for k in sorted(m.selectors):
        if k not in path_keys:
            issues.append(error(
                key, STEP_SELECTORS,
                f"selector key {k!r} has no corresponding [{k}] in any polearms or swords path"))

    fn = m.mapper_fn()
    if fn and mapper_fns and fn not in mapper_fns:
        issues.append(error(
            key, STEP_MAPPER_FUNCTION, f"mapper function {fn!r} not defined in mappers_and_selectors.py"))
    for k in sorted(m.selectors):
        sel_fn = m.selector_fn(k)
        if sel_fn and mapper_fns and sel_fn not in mapper_fns:
            issues.append(error(
                key, STEP_SELECTOR_FUNCTION,
                f"selector function {sel_fn!r} for [{k}] not defined in mappers_and_selectors.py"))

    return issues


def validate_uniqueness(mappings: list[Mapping]) -> list[Issue]:
    issues: list[Issue] = []
    seen_base: set[tuple[str, str]] = set()
    seen_swords: set[str] = set()
    for m in mappings:
        logic = m.logic_key()
        for original, base in zip((p for p in m.polearms if p), m.base_paths()):
            if (base, logic) in seen_base:
                issues.append(error(
                    m.display_name(), STEP_UNIQUE_POLEARMS_FIELD,
                    f"duplicate (polearms base path, mapper and selectors) combination for {original!r}"))
            seen_base.add((base, logic))
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


def validate_primitive_polearms_fields(
    mappings: list[Mapping], schema: OCSFSchema, class_name: str | None,
) -> list[Issue]:
    """A POLEARMS base path must be a primitive field, never an object. With no class, a path that
    is an object in any class that has it is rejected. Paths that don't exist are left to
    valid-polearms-field."""
    classes = [class_name] if class_name else list(schema.classes)
    issues: list[Issue] = []
    for m in mappings:
        for base in m.base_paths():
            attrs = (schema.lookup_field(c, base) for c in classes)
            if any(a is not None and is_object_field(a) for a in attrs):
                issues.append(error(
                    m.display_name(), STEP_PRIMITIVE_POLEARMS_FIELD,
                    f"{base!r} is an object; a POLEARMS field must be a primitive field "
                    f"(map one of its child fields instead)"))
    return issues


def validate_polearms_field_arrays(
    mappings: list[Mapping], schema: OCSFSchema, class_name: str | None,
) -> list[Issue]:
    """Each array a POLEARMS path passes through needs a bracket, and nothing else may have one.
    [] (every non-null item) and [N] (item N) are resolved by the executor. A labelled [key], like
    evidences[x], has a selectors entry, which picks the items with a function, or only documents
    the bracket when a mapper picks them itself. A final array of primitives may have a bracket or not. With no class, the
    path is checked against every class that has it. Paths that don't exist are left to
    valid-polearms-field."""
    classes = [class_name] if class_name else list(schema.classes)
    issues: list[Issue] = []
    for m in mappings:
        for path in (p for p in m.polearms if p):
            parts = path.split(".")
            reported: set[str] = set()
            for cls in classes:
                flags = schema.array_segments(cls, base_path(path))
                if flags is None or len(flags) != len(parts):
                    continue
                for part, is_array, last in zip(parts, flags, [False] * (len(parts) - 1) + [True]):
                    name, bracket = part.split("[", 1)[0], "[" in part
                    key = part[len(name) + 1:-1]
                    selects = bracket and (key == "" or is_index(key))
                    labelled = bracket and not selects and key in m.selectors
                    right_bracket = selects or labelled
                    if is_array and not right_bracket and not (last and not bracket):
                        problem = (f"{name!r} is an array, so it must be written as {name}[] "
                                   f"(every non-null item), {name}[N] (item N) or a selector "
                                   f"bracket like {name}[x] with a selectors entry")
                    elif bracket and not is_array:
                        problem = f"{name!r} is not an array, so it must not have brackets"
                    else:
                        continue
                    if problem not in reported:
                        reported.add(problem)
                        issues.append(error(
                            m.display_name(), STEP_POLEARMS_FIELD_ARRAYS,
                            f"POLEARMS field {path!r}: {problem}"))
    return issues


def validate_result_shape(
    mappings: list[Mapping], swords_schema: dict, list_selectors: frozenset[str] | None = None,
) -> list[Issue]:
    """For a mapping without a mapper, the paths decide the result: a [] or a list-returning
    selector bracket gives a list of values and anything else gives one. So join and first need
    list paths (and cannot be combined), and a list result with neither writes a list, which the
    SWORDS field must be able to hold. A mapping with several paths and no mapper joins their
    lists end to end, so every path must give a list. SWORDS fields missing from the schema are
    left to valid-swords-field. list_selectors names the selectors that return a list; None counts
    every selector function as one."""
    issues: list[Issue] = []
    for m in mappings:
        if m.first and m.mapper is not None:
            issues.append(error(
                m.display_name(), STEP_RESULT_SHAPE,
                "first applies to a path the executor resolves; remove the mapper or select in it"))
        if m.mapper is not None:
            continue
        if m.is_many_to_one():
            bad = [p for p in m.polearms if p and not m.path_produces_list(p, list_selectors)]
            if bad:
                issues.append(error(
                    m.display_name(), STEP_RESULT_SHAPE,
                    f"a mapping with several POLEARMS paths and no mapper joins their lists, but "
                    f"{', '.join(repr(p) for p in bad)} does not give a list; use [] or a selector "
                    f"that returns a list, or add a mapper"))
            if m.first or m.join is not None:
                issues.append(error(
                    m.display_name(), STEP_RESULT_SHAPE,
                    f"{'first' if m.first else 'join'} is not supported on a mapping with several "
                    f"POLEARMS paths and no mapper"))
            continue
        lists = m.produces_list(list_selectors)
        if m.first and m.join is not None:
            issues.append(error(
                m.display_name(), STEP_RESULT_SHAPE,
                "first and join cannot be combined: first gives one value and join needs a list"))
        elif (m.first or m.join is not None) and not lists:
            issues.append(error(
                m.display_name(), STEP_RESULT_SHAPE,
                f"{'first' if m.first else 'join'} needs a POLEARMS path with [] or a selector "
                f"that returns a list, so there is a list to {'take from' if m.first else 'join'}"))
        elif lists and m.join is None and not m.first and not m.is_list_item():
            attr = swords_schema.get(m.swords_field_path())
            if attr is not None and attr.get("is_list") is False:
                issues.append(error(
                    m.display_name(), STEP_RESULT_SHAPE,
                    f"the path gives a list but SWORDS field {m.swords!r} is not a list; "
                    f"add join or first, or write [N] for one item"))
    return issues


def validate_swords_fields(mappings: list[Mapping], swords_schema: dict) -> list[Issue]:
    """Every SWORDS field (with its [key] segments stripped) must exist in the SWORDS schema."""
    return [
        error(m.display_name(), STEP_VALID_SWORDS_FIELD,
              f"{m.swords_field_path()!r} is not a field in the SWORDS schema")
        for m in mappings
        if m.swords and m.swords_field_path() not in swords_schema
    ]


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
            global_swords_by_pair[(base, g.logic_key())] = g.swords

    override_swords = {o.swords for o in overrides if o.swords}

    issues: list[Issue] = []
    for o in overrides:
        if not any("[" in p for p in o.polearms):
            continue
        fn = o.logic_key()
        for base in o.base_paths():
            global_swords = global_swords_by_pair.get((base, fn))
            if global_swords is None or global_swords == o.swords or global_swords in override_swords:
                continue
            if schema.lookup_field(class_name, base) is None:
                continue
            issues.append(warning(
                o.display_name(), STEP_OVERRIDE_SHADOWING,
                f"global mapping for {base!r} using {fn!r} is overridden and the SWORDS "
                f"field {global_swords!r} won't be populated as a result"))
    return issues


# ---------------------------------------------------------------------------
# Validation entry points
# ---------------------------------------------------------------------------


def validate_global_mappings(
    mappings: list[Mapping], schema: OCSFSchema, swords_schema: dict,
    mapper_fns: set[str], version: str, list_selectors: frozenset[str] | None = None,
) -> list[Issue]:
    issues = validate_uniqueness(mappings)
    for m in mappings:
        issues += validate_single_mapping(m, mapper_fns)
    issues += validate_polearms_fields(mappings, schema, None, version)
    issues += validate_primitive_polearms_fields(mappings, schema, None)
    issues += validate_polearms_field_arrays(mappings, schema, None)
    issues += validate_swords_fields(mappings, swords_schema)
    issues += validate_result_shape(mappings, swords_schema, list_selectors)
    return issues


def validate_class_overrides(
    config: ClassConfig, globals_: list[Mapping], schema: OCSFSchema, swords_schema: dict,
    mapper_fns: set[str], version: str, list_selectors: frozenset[str] | None = None,
) -> list[Issue]:
    overrides = config.override_mappings
    if not overrides:
        return []
    issues = validate_uniqueness(overrides)
    for m in overrides:
        issues += validate_single_mapping(m, mapper_fns)
    issues += validate_polearms_fields(overrides, schema, config.name, version)
    issues += validate_primitive_polearms_fields(overrides, schema, config.name)
    issues += validate_polearms_field_arrays(overrides, schema, config.name)
    issues += validate_swords_fields(overrides, swords_schema)
    issues += validate_result_shape(overrides, swords_schema, list_selectors)
    issues += validate_override_relevance(overrides, schema, config.name, version)
    issues += validate_override_completeness(overrides, globals_, schema, config.name)
    issues += validate_override_shadowing(overrides, globals_, schema, config.name)
    return issues


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text())


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    schema = OCSFSchema.load(SCHEMA_PATH)
    swords_schema = load_swords_schema(SWORDS_SCHEMA_PATH)
    mapper_fns = load_mapper_function_names(MAPPERS_AND_SELECTORS_PATH)
    list_selectors = load_list_selector_names(MAPPERS_AND_SELECTORS_PATH)
    version = load_version(VERSION_PATH)

    # A document that doesn't match its JSON Schema can't be safely turned into Mappings, so its
    # structural errors are reported and the semantic checks are skipped for it.
    issues = validate_against_schema(load_yaml(SWORDS_MAPPINGS_PATH), "mappings.schema.json", SWORDS_MAPPINGS_PATH.name)
    globals_ = [] if issues else load_mappings(SWORDS_MAPPINGS_PATH)
    if not issues:
        issues = validate_global_mappings(
            globals_, schema, swords_schema, mapper_fns, version, list_selectors)
    report("global mappings", issues)
    all_issues = list(issues)
    globals_usable = not issues

    for path in discover_class_configs(CONFIG_DIR):
        raw = load_yaml(path)
        name = raw.get("class_name") if isinstance(raw, dict) else None
        title = f"{name or path.parent.relative_to(CONFIG_DIR)} override mappings"

        # Only the overrides are this validator's concern; the rest of the config is validate.config.
        overrides = raw.get("override_mappings") if isinstance(raw, dict) else None
        if not overrides:
            report(title, [])
            continue
        issues = validate_against_schema(
            {"mappings": overrides}, "mappings.schema.json", f"{path.parent.name}/config.yaml:override_mappings")
        if not issues and name:
            if globals_usable:
                config = ClassConfig.load(path)
                issues = validate_class_overrides(
                    config, globals_, schema, swords_schema, mapper_fns, version, list_selectors)
            else:
                # The override checks compare against the global mappings, which failed above.
                print(f"{title}: skipped (global mappings are invalid)")
                continue
        report(title, issues)
        all_issues += issues

    exit_if_errors(all_issues)


if __name__ == "__main__":
    main()
