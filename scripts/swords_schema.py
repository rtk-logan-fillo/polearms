#!/usr/bin/env python3
"""Download and load the SWORDS schema.

The SWORDS schema lives in the (private) rtkwlf/parse_and_detect repository. It is saved to
schema/carser_swords_schema.json, which is git-ignored, and is used to validate the SWORDS fields in
the mappings and to fill in the SWORDS Type column of the Confluence pages.

The download authenticates with a GitHub token from $GITHUB_TOKEN or $GH_TOKEN, or else from the
GitHub CLI (`gh auth token`).

Running this script always downloads a fresh copy. The validators and the Confluence generator only
download when the file is missing.

Usage:
    python3 -m scripts.swords_schema
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from scripts.common import SWORDS_SCHEMA_PATH

SWORDS_SCHEMA_URL = (
    "https://api.github.com/repos/rtkwlf/parse_and_detect/contents/"
    "rules/carsers/schemas/carser_swords_schema.json?ref=master"
)


def github_token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def fetch_swords_schema(path: Path = SWORDS_SCHEMA_PATH, url: str = SWORDS_SCHEMA_URL) -> None:
    """Download the SWORDS schema to path. Exits with a message if it cannot be downloaded."""
    token = github_token()
    if not token:
        raise SystemExit(
            f"cannot download the SWORDS schema to {path}: no GitHub token. Set GITHUB_TOKEN "
            "(with read access to rtkwlf/parse_and_detect) or log in with `gh auth login`.")
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read()
    except urllib.error.HTTPError as err:
        raise SystemExit(f"cannot download the SWORDS schema (HTTP {err.code}): {err.read().decode()}")
    except urllib.error.URLError as err:
        raise SystemExit(f"cannot download the SWORDS schema: {err.reason}")

    try:
        schema = json.loads(payload)
    except json.JSONDecodeError as err:
        raise SystemExit(f"the downloaded SWORDS schema is not valid JSON: {err}")
    if not isinstance(schema, dict) or not schema:
        raise SystemExit("the downloaded SWORDS schema is not a non-empty JSON object")

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(payload)
    temp.replace(path)


def load_swords_schema(path: Path = SWORDS_SCHEMA_PATH) -> dict[str, dict]:
    """The SWORDS schema as {field: {"datatype", "is_list", "presence", ...}}, downloaded first if
    it is not already at path."""
    if not path.is_file():
        print(f"downloading the SWORDS schema to {path}")
        fetch_swords_schema(path)
    try:
        schema = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise SystemExit(f"{path} is not valid JSON ({err}); delete it to download a fresh copy")
    if not isinstance(schema, dict):
        raise SystemExit(f"{path} must be a JSON object; delete it to download a fresh copy")
    return schema


def swords_type(entry: dict | None) -> str:
    """A field's type as shown to people: 'int', or 'int[]' for a list. Blank if unknown."""
    datatype = (entry or {}).get("datatype")
    if not datatype:
        return ""
    return datatype + ("[]" if entry.get("is_list") else "")


def main() -> None:
    argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    fetch_swords_schema(SWORDS_SCHEMA_PATH)
    count = len(load_swords_schema(SWORDS_SCHEMA_PATH))
    print(f"saved the SWORDS schema ({count} fields) to {SWORDS_SCHEMA_PATH}")


if __name__ == "__main__":
    main()
