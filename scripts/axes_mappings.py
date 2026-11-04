#!/usr/bin/env python3
"""Download and load the SWORDS -> AXES field mappings.

The mappings live in the (private) rtkwlf/triage-config repository, in bundles/awn-ecs/data/mappings.
Each file there is a YAML list of entries where "old" is a SWORDS field and "ecs" is the AXES field
(an entry may also have an "also" with a second AXES field). _ecs_mappings.yaml holds the 1-1
mappings, where the two names are the same; the other files hold the rest.

The entries of all the files are saved to schema/axes_mappings.json, which is git-ignored, and are
used to fill in the AXES Field column of the Confluence pages.

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

import yaml

from scripts.common import AXES_MAPPINGS_PATH
from scripts.swords_schema import github_token

MAPPINGS_DIR_URL = (
    "https://api.github.com/repos/rtkwlf/triage-config/contents/"
    "bundles/awn-ecs/data/mappings?ref=main"
)

ONE_TO_ONE_FILE = "_ecs_mappings.yaml"

# "ecs" values that say there is no AXES field: not yet decided, dropped, or built by a complex rule.
NO_AXES_FIELD = {"TODO", "DROP", "COMPLEX"}

# The top-level SWORDS fields are written as base.<field> in the mappings.
BASE_PREFIX = "base."


def _get(url: str, token: str, accept: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        raise SystemExit(f"cannot download the AXES mappings (HTTP {err.code}): {err.read().decode()}")
    except urllib.error.URLError as err:
        raise SystemExit(f"cannot download the AXES mappings: {err.reason}")


def parse_mapping_file(name: str, text: str) -> list[dict]:
    """The entries of one mappings file as [{"file", "old", "ecs", "also"?}]."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise SystemExit(f"cannot parse {name} in the AXES mappings: {err}")
    if data is None:
        return []
    if not isinstance(data, list):
        raise SystemExit(f"{name} in the AXES mappings must be a list of entries")
    entries = []
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("old"), str) \
                or not isinstance(item.get("ecs"), str):
            raise SystemExit(f"{name} in the AXES mappings has an entry without an old and an ecs: {item!r}")
        entry = {"file": name, "old": item["old"], "ecs": item["ecs"]}
        if isinstance(item.get("also"), str):
            entry["also"] = item["also"]
        entries.append(entry)
    return entries


def fetch_axes_mappings(path: Path = AXES_MAPPINGS_PATH, url: str = MAPPINGS_DIR_URL) -> None:
    """Download the AXES mappings to path. Exits with a message if they cannot be downloaded."""
    token = github_token()
    if not token:
        raise SystemExit(
            f"cannot download the AXES mappings to {path}: no GitHub token. Set GITHUB_TOKEN "
            "(with read access to rtkwlf/triage-config) or log in with `gh auth login`.")

    try:
        listing = json.loads(_get(url, token, "application/vnd.github+json"))
    except json.JSONDecodeError as err:
        raise SystemExit(f"the AXES mappings directory listing is not valid JSON: {err}")
    if not isinstance(listing, list):
        raise SystemExit("the AXES mappings directory listing is not a list of files")

    entries: list[dict] = []
    for item in listing:
        name = item.get("name", "")
        if item.get("type") != "file" or not name.endswith((".yaml", ".yml")):
            continue
        file_url = item.get("url") or f"{url.split('?')[0]}/{name}?ref=main"
        text = _get(file_url, token, "application/vnd.github.raw+json").decode()
        entries.extend(parse_mapping_file(name, text))
    if not entries:
        raise SystemExit("the downloaded AXES mappings contain no entries")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(entries))
    temp.replace(path)


def load_axes_mappings(path: Path = AXES_MAPPINGS_PATH) -> list[dict]:
    """The AXES mapping entries, downloaded first if they are not already at path."""
    if not path.is_file():
        print(f"downloading the AXES mappings to {path}")
        fetch_axes_mappings(path)
    try:
        entries = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise SystemExit(f"{path} is not valid JSON ({err}); delete it to download a fresh copy")
    if not isinstance(entries, list):
        raise SystemExit(f"{path} must be a JSON list; delete it to download a fresh copy")
    return entries


def _strip_base(field: str) -> str:
    return field[len(BASE_PREFIX):] if field.startswith(BASE_PREFIX) else field


def swords_to_axes(entries: list[dict]) -> dict[str, list[str]]:
    """{SWORDS field: [AXES fields it maps to]}, each list sorted.

    Entries whose ecs is TODO, DROP or COMPLEX have no AXES field. The 1-1 mappings of
    _ecs_mappings.yaml are used for a SWORDS field only when no other file maps it.
    """
    specific: dict[str, set[str]] = {}
    one_to_one: dict[str, set[str]] = {}
    for entry in entries:
        if entry["ecs"] in NO_AXES_FIELD:
            continue
        target = one_to_one if entry.get("file") == ONE_TO_ONE_FILE else specific
        fields = target.setdefault(_strip_base(entry["old"]), set())
        fields.add(_strip_base(entry["ecs"]))
        if entry.get("also"):
            fields.add(_strip_base(entry["also"]))
    merged = {**one_to_one, **specific}
    return {swords_field: sorted(fields) for swords_field, fields in merged.items()}


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    fetch_axes_mappings(AXES_MAPPINGS_PATH)
    count = len(load_axes_mappings(AXES_MAPPINGS_PATH))
    print(f"saved the AXES mappings ({count} entries) to {AXES_MAPPINGS_PATH}")


if __name__ == "__main__":
    main()
