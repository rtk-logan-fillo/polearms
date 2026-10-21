#!/usr/bin/env python3
"""Validate that the version being released (the VERSION file) tracks the Arctic Wolf extension.

The major and minor parts of VERSION must equal those of arcticwolf_extension.version in
schema/schema_definition.yaml. The patch part (and any pre-release suffix) is free to differ.

Steps, by ID:
    release-version         VERSION and arcticwolf_extension.version agree on major.minor

Exits 1 if there are any errors.

Usage:
    python3 -m scripts.validate.release_version
"""

from __future__ import annotations

import argparse
import re

from scripts.common import (
    SCHEMA_DEFINITION_PATH,
    VERSION_PATH,
    definition_version,
    load_definition,
    load_version,
)
from scripts.validate.helpers import Issue, error, exit_if_errors, report

STEP_RELEASE_VERSION = "release-version"

_SEMVER_PREFIX = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def major_minor(version: str) -> tuple[int, int] | None:
    """(major, minor) of a semantic version such as '1.2.3' or '1.2.3-rc.1', else None."""
    match = _SEMVER_PREFIX.match(version)
    return (int(match.group(1)), int(match.group(2))) if match else None


def validate_release_version(version: str, definition: dict) -> list[Issue]:
    target = "VERSION"
    extension = definition_version(definition, "arcticwolf_extension")
    if extension is None:
        return [error(target, STEP_RELEASE_VERSION,
                      "schema_definition.yaml arcticwolf_extension.version is not set")]

    release, tracked = major_minor(version), major_minor(extension)
    if release is None:
        return [error(target, STEP_RELEASE_VERSION, f"VERSION {version!r} is not a semantic version")]
    if tracked is None:
        return [error(target, STEP_RELEASE_VERSION,
                      f"schema_definition.yaml arcticwolf_extension.version {extension!r} "
                      "is not a semantic version")]

    if release != tracked:
        return [error(
            target, STEP_RELEASE_VERSION,
            f"VERSION {version!r} has major.minor {release[0]}.{release[1]}, but "
            f"schema_definition.yaml arcticwolf_extension.version {extension!r} has "
            f"{tracked[0]}.{tracked[1]}; they must match")]
    return []


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    issues = validate_release_version(
        load_version(VERSION_PATH), load_definition(SCHEMA_DEFINITION_PATH))
    report("release version", issues)
    exit_if_errors(issues)


if __name__ == "__main__":
    main()
