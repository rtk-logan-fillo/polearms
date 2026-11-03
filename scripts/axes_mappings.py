#!/usr/bin/env python3
"""Download and load the AXES mappings.

The AXES mappings live in the (private) rtkwlf/axes repository. The keys of all-mappings.json are
AXES fields; each maps to a list of operations, and the "old" lists of those operations name the
SWORDS fields that become the AXES field. The file is saved to schema/axes_all_mappings.json, which
is git-ignored, and is used to fill in the AXES Field column of the Confluence pages.

The download authenticates like scripts/swords_schema.py: a GitHub token from $GITHUB_TOKEN or
$GH_TOKEN, or else from the GitHub CLI (`gh auth token`). Running this script always downloads a
fresh copy; the Confluence generator only downloads when the file is missing.

Usage:
    python3 -m scripts.axes_mappings
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

from scripts.common import AXES_MAPPINGS_PATH
from scripts.swords_schema import github_token

AXES_MAPPINGS_URL = (
    "https://api.github.com/repos/rtkwlf/axes/contents/mappings/all-mappings.json?ref=main"
)


def fetch_axes_mappings(path: Path = AXES_MAPPINGS_PATH, url: str = AXES_MAPPINGS_URL) -> None:
    """Download the AXES mappings to path. Exits with a message if they cannot be downloaded."""
    token = github_token()
    if not token:
        raise SystemExit(
            f"cannot download the AXES mappings to {path}: no GitHub token. Set GITHUB_TOKEN "
            "(with read access to rtkwlf/axes) or log in with `gh auth login`.")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read()
    except urllib.error.HTTPError as err:
        raise SystemExit(f"cannot download the AXES mappings (HTTP {err.code}): {err.read().decode()}")
    except urllib.error.URLError as err:
        raise SystemExit(f"cannot download the AXES mappings: {err.reason}")

    try:
        mappings = json.loads(payload)
    except json.JSONDecodeError as err:
        raise SystemExit(f"the downloaded AXES mappings are not valid JSON: {err}")
    if not isinstance(mappings, dict) or not mappings:
        raise SystemExit("the downloaded AXES mappings are not a non-empty JSON object")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(payload)
    temp.replace(path)


def load_axes_mappings(path: Path = AXES_MAPPINGS_PATH) -> dict[str, list[dict]]:
    """The AXES mappings as {axes field: [operation, ...]}, downloaded first if they are not
    already at path."""
    if not path.is_file():
        print(f"downloading the AXES mappings to {path}")
        fetch_axes_mappings(path)
    try:
        mappings = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise SystemExit(f"{path} is not valid JSON ({err}); delete it to download a fresh copy")
    if not isinstance(mappings, dict):
        raise SystemExit(f"{path} must be a JSON object; delete it to download a fresh copy")
    return mappings


def _old_fields(operations: list[dict]):
    """Every SWORDS field named in an "old" list, including inside nested operations."""
    for op in operations:
        yield from op.get("old") or []
        yield from _old_fields(op.get("operations") or [])


def swords_to_axes(axes_mappings: dict[str, list[dict]]) -> dict[str, list[str]]:
    """{SWORDS field: [AXES fields it maps to]}, each list sorted. A SWORDS field can feed more
    than one AXES field."""
    lookup: dict[str, set[str]] = {}
    for axes_field, operations in axes_mappings.items():
        for swords_field in _old_fields(operations):
            lookup.setdefault(swords_field, set()).add(axes_field)
    return {swords_field: sorted(fields) for swords_field, fields in lookup.items()}


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    fetch_axes_mappings(AXES_MAPPINGS_PATH)
    count = len(load_axes_mappings(AXES_MAPPINGS_PATH))
    print(f"saved the AXES mappings ({count} fields) to {AXES_MAPPINGS_PATH}")


if __name__ == "__main__":
    main()
