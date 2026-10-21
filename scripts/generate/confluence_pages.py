#!/usr/bin/env python3
"""Build the Confluence pages documenting each class's POLEARMS -> SWORDS mappings and publish them.

For every class config under config/ this builds two pages, in Confluence storage format:

    <Class> <version> - Mappings          every mapped field, with schema info and the SWORDS side
    <Class> <version> - Essential Fields  the class's essential fields, with schema info

and creates or updates them in Confluence, under POLEARMS / <version> / <Class> <version> in the
personal space of the given user. <version> is the contents of the VERSION file.

Usage:
    python3 -m scripts.generate.confluence_pages --confluence-user USER --confluence-token TOKEN
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from scripts.common import (
    CONFIG_DIR,
    MAPPINGS_PATH,
    SCHEMA_PATH,
    VERSION_PATH,
    ClassConfig,
    Mapping,
    OCSFSchema,
    base_path,
    discover_class_configs,
    display_path,
    load_mappings,
    load_version,
)

SWORDS_SCHEMA_PATH = Path(
    "/workspaces/parse_and_detect/rules/carsers/schemas/carser_swords_schema.json"
)
CONFLUENCE_URL = "https://arcticwolf.atlassian.net/wiki"

ROOT_PAGE_TITLE = "POLEARMS"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# SWORDS schema
# ---------------------------------------------------------------------------


def load_swords_schema(path: Path) -> dict:
    if not path.is_file():
        print(f"warning: SWORDS schema not found at {path}; SWORDS types will be blank",
              file=sys.stderr)
        return {}
    with open(path) as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# Page building
# ---------------------------------------------------------------------------


@dataclass
class Page:
    title: str
    body: str
    hierarchy: list[str]
    summary: str


@dataclass
class Row:
    polearms_field: str
    caption: str = ""
    description: str = ""
    type_name: str = ""
    requirement: str = ""
    join_sep: str | None = None
    swords: str = ""
    swords_type: str = ""
    mapping: str = ""
    source: str = ""

    def shown_field(self) -> str:
        if self.join_sep is None:
            return self.polearms_field
        return f"join({self.polearms_field}, {json.dumps(self.join_sep)})"


def filter_mappings_to_essential(mappings: list[Mapping], config: ClassConfig) -> list[Mapping]:
    """Keep mappings with a polearms path covered by an essential field, and only those paths."""
    kept = []
    for m in mappings:
        paths = [p for p in m.polearms if p and config.covers_path(p)]
        if not paths:
            continue
        # A many-to-one mapping needs every input to produce its output: whole or not at all.
        if m.is_many_to_one() and len(paths) != len(m.polearms):
            continue
        kept.append(Mapping(paths, m.swords, m.labels, m.mapper))
    return kept


def schema_columns(attr: dict | None) -> dict:
    attr = attr or {}
    return {
        "caption": attr.get("caption", ""),
        "description": attr.get("description", ""),
        "type_name": attr.get("type", ""),
        "requirement": attr.get("requirement", ""),
    }


def build_mapping_rows(
    mappings: list[Mapping],
    overrides: list[Mapping],
    essential_names: list[str],
    schema: OCSFSchema,
    class_name: str,
    swords_schema: dict,
) -> list[Row]:
    # One mapping per SWORDS field; a class override replaces the global mapping.
    effective: dict[str, tuple[Mapping, str]] = {}
    for m in mappings:
        if m.has_polearms():
            effective[m.swords] = (m, "Mapping")
    for m in overrides:
        if m.has_polearms():
            effective[m.swords] = (m, "Override")

    rows: list[Row] = []
    covered: set[str] = set()

    for m, source in effective.values():
        for polearms_path in m.polearms:
            if not polearms_path:
                continue
            field_path = base_path(polearms_path)
            attr = schema.lookup_field(class_name, field_path)
            if attr is None:
                continue  # the mapping targets a field this class does not have
            covered.add(field_path)

            if m.is_many_to_one():
                mapping_cell = "<strong>Complex</strong> (many-to-one)"
            elif m.mapper is not None:
                mapping_cell = "<strong>Complex</strong>"
            else:
                mapping_cell = "Direct"

            swords_type = ""
            info = swords_schema.get(m.swords_field_path())
            if info:
                swords_type = info.get("datatype", "") + ("[]" if info.get("is_list") else "")

            source_cell = escape_html(source)
            if source == "Override":
                source_cell = f"<strong>{source_cell}</strong>"

            rows.append(Row(
                polearms_field=display_path(polearms_path, m.labels),
                join_sep=m.join_separator(),
                swords=m.display_swords(),
                swords_type=swords_type,
                mapping=mapping_cell,
                source=source_cell,
                **schema_columns(attr),
            ))

    # Essential fields with no mapping still get a row, with the SWORDS columns blank.
    for name in sorted(n for n in essential_names if base_path(n) not in covered):
        rows.append(Row(polearms_field=name, **schema_columns(schema.lookup_field(class_name, name))))

    rows.sort(key=lambda r: (r.polearms_field, r.swords))
    return rows


MAPPING_COLUMNS = [
    ("POLEARMS Field", 23), ("POLEARMS Caption", 9), ("POLEARMS Description", 20),
    ("POLEARMS Type", 8), ("POLEARMS Requirement", 9), ("SWORDS Field", 17),
    ("SWORDS Type", 6), ("Mapping Type", 5), ("Source", 3),
]
ESSENTIAL_COLUMNS = [
    ("POLEARMS Field", 30), ("POLEARMS Caption", 15), ("POLEARMS Description", 47), ("Expected", 8),
]


def table(columns: list[tuple[str, int]], rows: list[list[str]]) -> str:
    cols = "".join(f'<col style="width:{width}%"/>' for _, width in columns)
    head = "".join(f"<th>{title}</th>" for title, _ in columns)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (
        f'<table data-layout="full-width" style="width:100%"><colgroup>{cols}</colgroup>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    )


def build_mapping_table(rows: list[Row]) -> str:
    return table(MAPPING_COLUMNS, [
        [
            f"<code>{escape_html(r.shown_field())}</code>",
            escape_html(r.caption),
            r.description,  # the schema authors descriptions as HTML
            escape_html(r.type_name),
            escape_html(r.requirement),
            f"<code>{escape_html(r.swords)}</code>" if r.swords else "",
            escape_html(r.swords_type),
            r.mapping,
            r.source,
        ]
        for r in rows
    ])


def build_essential_fields_table(fields: list[dict], schema: OCSFSchema, class_name: str) -> str:
    rows = []
    for f in sorted(fields, key=lambda f: f["polearms"]):
        attr = schema.lookup_field(class_name, f["polearms"]) or {}
        rows.append([
            f"<code>{escape_html(f['polearms'])}</code>",
            escape_html(attr.get("caption", "")),
            attr.get("description", ""),
            "<strong>Yes</strong>" if f.get("expected") else "No",
        ])
    return table(ESSENTIAL_COLUMNS, rows)


def build_pages(
    version: str,
    config: ClassConfig,
    global_mappings: list[Mapping],
    schema: OCSFSchema,
    swords_schema: dict,
) -> list[Page]:
    class_info = schema.lookup_class(config.name)
    class_title = f"{class_info['caption']} {version}"
    hierarchy = [ROOT_PAGE_TITLE, version, class_title]
    description = f"<p>{class_info['description']}</p>" if class_info.get("description") else ""

    mappings, overrides = global_mappings, config.override_mappings
    if config.essential_fields_only:
        mappings = filter_mappings_to_essential(mappings, config)
        overrides = filter_mappings_to_essential(overrides, config)
    rows = build_mapping_rows(
        mappings, overrides, [f["polearms"] for f in config.essential_fields],
        schema, config.name, swords_schema,
    )
    mapped = sum(1 for r in rows if r.swords)

    return [
        Page(
            title=f"{class_title} - Mappings",
            body=description + build_mapping_table(rows),
            hierarchy=hierarchy,
            summary=f"{len(rows)} fields ({mapped} mapped, {len(rows) - mapped} unmapped)",
        ),
        Page(
            title=f"{class_title} - Essential Fields",
            body=description + build_essential_fields_table(
                config.essential_fields, schema, config.name),
            hierarchy=hierarchy,
            summary=f"{len(config.essential_fields)} essential fields",
        ),
    ]


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


class ConfluenceClient:
    def __init__(self, base_url: str, user: str, token: str):
        self.base_url = base_url.rstrip("/")
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {creds}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req) as resp:
                payload = resp.read()
        except urllib.error.HTTPError as err:
            raise SystemExit(f"Confluence API error (HTTP {err.code}): {err.read().decode()}")
        return json.loads(payload) if payload else {}

    def current_user(self) -> str:
        user = self.request("GET", "/rest/api/user/current")
        return user.get("accountId") or user.get("userKey") or user.get("username", "")

    def personal_space_key(self, account_id: str) -> str:
        key = "~" + account_id
        query = urllib.parse.urlencode({"spaceKey": key, "limit": 1})
        results = self.request("GET", f"/rest/api/space?{query}").get("results", [])
        return results[0]["key"] if results else key

    def find_page(self, space_key: str, title: str, ancestor_id: str = "") -> dict | None:
        query = urllib.parse.urlencode({
            "spaceKey": space_key, "title": title, "type": "page", "expand": "version,ancestors",
        })
        for page in self.request("GET", f"/rest/api/content?{query}").get("results", []):
            if not ancestor_id or any(a["id"] == ancestor_id for a in page.get("ancestors", [])):
                return page
        return None

    def create_page(self, space_key: str, parent_id: str, title: str, body: str) -> dict:
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return self.request("POST", "/rest/api/content", payload)

    def update_page(self, page_id: str, title: str, body: str, version: int) -> dict:
        payload = {
            "type": "page",
            "title": title,
            "body": {"storage": {"value": body, "representation": "storage"}},
            "version": {"number": version},
        }
        return self.request("PUT", f"/rest/api/content/{urllib.parse.quote(page_id)}", payload)

    def find_or_create_page(self, space_key: str, parent_id: str, title: str) -> tuple[dict, bool]:
        page = self.find_page(space_key, title, parent_id)
        if page is None and parent_id:
            page = self.find_page(space_key, title)
        if page is not None:
            return page, False
        return self.create_page(space_key, parent_id, title, ""), True


def publish_pages(pages: list[Page], client: ConfluenceClient) -> None:
    print("Authenticating... ", end="", flush=True)
    account_id = client.current_user()
    print("ok")
    space_key = client.personal_space_key(account_id)
    print(f"Publishing to space {space_key}")

    for page in pages:
        parent_id = ""
        for title in page.hierarchy:
            parent, created = client.find_or_create_page(space_key, parent_id, title)
            print(f"  {'Created' if created else 'Found  '} page: {title}")
            parent_id = parent["id"]

        existing = client.find_page(space_key, page.title, parent_id) or client.find_page(
            space_key, page.title)
        if existing:
            client.update_page(existing["id"], page.title, page.body,
                               existing["version"]["number"] + 1)
            print(f"  Updated page: {page.title} ({page.summary})")
        else:
            client.create_page(space_key, parent_id, page.title, page.body)
            print(f"  Created page: {page.title} ({page.summary})")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--confluence-user", required=True, help="Confluence account email")
    parser.add_argument("--confluence-token", required=True, help="Confluence API token")
    args = parser.parse_args()

    version = load_version(VERSION_PATH)
    global_mappings = load_mappings(MAPPINGS_PATH)
    schema = OCSFSchema.load(SCHEMA_PATH)
    swords_schema = load_swords_schema(SWORDS_SCHEMA_PATH)

    configs = [ClassConfig.load(p) for p in discover_class_configs(CONFIG_DIR)]
    if not configs:
        raise SystemExit(f"no class configs found under {CONFIG_DIR}")

    pages: list[Page] = []
    for config in configs:
        pages.extend(build_pages(version, config, global_mappings, schema, swords_schema))

    client = ConfluenceClient(CONFLUENCE_URL, args.confluence_user, args.confluence_token)
    publish_pages(pages, client)


if __name__ == "__main__":
    main()
