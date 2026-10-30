#!/usr/bin/env python3
"""Build the Confluence pages documenting each class's POLEARMS -> SWORDS mappings and publish them.

For every class config under config/ this builds two pages, in Confluence storage format:

    <Class> <version> - Mappings          every mapped field, with schema info and the SWORDS side
    <Class> <version> - Essential Fields  the class's essential fields, with schema info

and creates or updates them in Confluence, under POLEARMS / <version> / <Class> <version>.
POLEARMS is an existing folder in the MDRP space (BASE_FOLDER_ID); it must already exist and is
never created or modified. <version> is the "version" in version.json.

The SWORDS Type column comes from the SWORDS schema (datatype, with [] added for a list), which is
downloaded to schema/ if it is not already there (see scripts/swords_schema.py).

Usage:
    python3 -m scripts.generate_confluence_pages --confluence-user USER --confluence-token TOKEN
"""

from __future__ import annotations

import argparse
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from scripts.common import (
    CONFIG_DIR,
    MAPPINGS_PATH,
    SCHEMA_PATH,
    SWORDS_SCHEMA_PATH,
    VERSION_PATH,
    ClassConfig,
    Mapping,
    OCSFSchema,
    base_path,
    discover_class_configs,
    display_path,
    is_object_field,
    load_mappings,
    load_version,
)
from scripts.swords_schema import load_swords_schema, swords_type

CONFLUENCE_URL = "https://arcticwolf.atlassian.net/wiki"

# https://arcticwolf.atlassian.net/wiki/spaces/MDRP/folder/6981780874
BASE_FOLDER_ID = "6981780874"
BASE_FOLDER_TITLE = "POLEARMS"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


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


def polearms_type(attr: dict) -> str:
    """The attribute's type, with [] added for an array of a primitive type: 'string_t[]'."""
    type_name = attr.get("type", "")
    if type_name and not is_object_field(attr) and attr.get("is_array"):
        return type_name + "[]"
    return type_name


def schema_columns(attr: dict | None) -> dict:
    attr = attr or {}
    return {
        "caption": attr.get("caption", ""),
        "description": attr.get("description", ""),
        "type_name": polearms_type(attr),
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
            effective[m.swords] = (m, "Global")
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

            source_cell = escape_html(source)
            if source == "Override":
                source_cell = f"<strong>{source_cell}</strong>"

            rows.append(Row(
                polearms_field=display_path(polearms_path, m.labels),
                join_sep=m.join_separator(),
                swords=m.display_swords(),
                swords_type=swords_type(swords_schema.get(m.swords_field_path())),
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
    hierarchy = [version, class_title]
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

    def get_folder(self, folder_id: str) -> dict:
        return self.request("GET", f"/api/v2/folders/{urllib.parse.quote(folder_id)}")

    def find_page(self, space_id: str, title: str) -> dict | None:
        """The page with this title in the space (titles are unique per space), or None."""
        query = urllib.parse.urlencode({"space-id": space_id, "title": title, "limit": 1})
        results = self.request("GET", f"/api/v2/pages?{query}").get("results", [])
        return results[0] if results else None

    def create_page(self, space_id: str, parent_id: str, title: str, body: str) -> dict:
        return self.request("POST", "/api/v2/pages", {
            "spaceId": space_id,
            "status": "current",
            "title": title,
            "parentId": parent_id,
            "body": {"representation": "storage", "value": body},
        })

    def update_page(self, page_id: str, title: str, body: str, version: int) -> dict:
        return self.request("PUT", f"/api/v2/pages/{urllib.parse.quote(page_id)}", {
            "id": page_id,
            "status": "current",
            "title": title,
            "body": {"representation": "storage", "value": body},
            "version": {"number": version},
        })

    def find_or_create_page(self, space_id: str, parent_id: str, title: str) -> tuple[dict, bool]:
        """The page titled title under parent_id, created empty if it does not exist.

        Exits if a page with that title exists elsewhere in the space: titles are unique per
        space, so it cannot be created here, and it is not ours to move or overwrite.
        """
        page = self.find_page(space_id, title)
        if page is None:
            return self.create_page(space_id, parent_id, title, ""), True
        if str(page.get("parentId")) != parent_id:
            raise SystemExit(
                f"a page titled {title!r} already exists in this space but is not under the "
                f"expected parent (page id {page['id']}); remove or rename it and retry")
        return page, False


def publish_pages(pages: list[Page], client: ConfluenceClient) -> None:
    print("Authenticating... ", end="", flush=True)
    client.current_user()
    print("ok")

    base = client.get_folder(BASE_FOLDER_ID)
    if base.get("title") != BASE_FOLDER_TITLE:
        raise SystemExit(
            f"folder {BASE_FOLDER_ID} is titled {base.get('title')!r}, expected "
            f"{BASE_FOLDER_TITLE!r}; refusing to publish")
    space_id = str(base["spaceId"])
    print(f"Publishing under folder {BASE_FOLDER_TITLE} ({BASE_FOLDER_ID})")

    for page in pages:
        parent_id = BASE_FOLDER_ID
        for title in page.hierarchy:
            parent, created = client.find_or_create_page(space_id, parent_id, title)
            print(f"  {'Created' if created else 'Found  '} page: {title}")
            parent_id = str(parent["id"])

        existing = client.find_page(space_id, page.title)
        if existing is None:
            client.create_page(space_id, parent_id, page.title, page.body)
            print(f"  Created page: {page.title} ({page.summary})")
            continue
        if str(existing.get("parentId")) != parent_id:
            raise SystemExit(
                f"a page titled {page.title!r} already exists in this space but is not under "
                f"the expected parent (page id {existing['id']}); remove or rename it and retry")
        client.update_page(existing["id"], page.title, page.body,
                           existing["version"]["number"] + 1)
        print(f"  Updated page: {page.title} ({page.summary})")


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
