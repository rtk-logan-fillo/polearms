import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from scripts.common import OCSFSchema

MINI_SCHEMA = {
    "classes": {
        "widget": {
            "uid": 1,
            "caption": "Widget",
            "description": "A <b>widget</b>.",
            "attributes": {
                "name": {"caption": "Name", "description": "The <i>name</i>.",
                         "type": "string_t", "requirement": "required"},
                "tags": {"caption": "Tags", "description": "Labels.",
                         "type": "string_t", "requirement": "optional"},
                "owner": {"caption": "Owner", "description": "Who owns it.", "type": "object_t",
                          "object_type": "person", "requirement": "recommended"},
            },
        },
        "gadget": {
            "uid": 2,
            "caption": "Gadget",
            "description": "",
            "attributes": {
                "serial": {"caption": "Serial", "description": "Serial number.",
                           "type": "string_t", "requirement": "required"},
            },
        },
    },
    "objects": {
        "person": {"attributes": {
            "email": {"caption": "Email", "description": "Email address.",
                      "type": "email_t", "requirement": "optional"},
            "address": {"caption": "Address", "description": "Where.", "type": "object_t",
                        "object_type": "address", "requirement": "optional"},
        }},
        "address": {"attributes": {
            "city": {"caption": "City", "description": "The city.",
                     "type": "string_t", "requirement": "optional"},
        }},
    },
}


@pytest.fixture
def mini_schema() -> OCSFSchema:
    return OCSFSchema(json.loads(json.dumps(MINI_SCHEMA)))


@pytest.fixture
def fake_project(tmp_path):
    """A tiny repo layout (version.json, mappings, schema, one class config) in a temp dir.

    Returns the paths, named like the constants in common, ready to monkeypatch in.
    """
    version = tmp_path / "version.json"
    version.write_text(json.dumps({"version": "1.2.3"}))

    mappings = tmp_path / "mappings.yaml"
    mappings.write_text(yaml.safe_dump({"mappings": [
        {"polearms": "name", "swords": "widget-name"},
        {"polearms": "owner.email", "swords": "owner-email"},
    ]}))

    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(MINI_SCHEMA))

    swords_schema = tmp_path / "carser_swords_schema.json"
    swords_schema.write_text(json.dumps({
        name: {"datatype": "string", "is_list": False, "presence": "optional"}
        for name in ("widget-name", "owner-email", "s", "x", "elsewhere")
    }))

    complex_mappings = tmp_path / "complex_mappings.py"
    complex_mappings.write_text("def map_x(value):\n    return value\n")

    config_dir = tmp_path / "config"
    (config_dir / "widget").mkdir(parents=True)
    (config_dir / "widget" / "config.yaml").write_text(yaml.safe_dump({
        "class_name": "widget",
        "class_uid": 1,
        "essential_fields": [{"polearms": "name", "expected": True}, {"polearms": "tags"}],
    }))

    return SimpleNamespace(
        root=tmp_path, version=version, mappings=mappings, schema=schema,
        complex_mappings=complex_mappings, config_dir=config_dir, swords_schema=swords_schema,
        widget_config=config_dir / "widget" / "config.yaml",
    )

FOLDER_ID = "6981780874"
SPACE_ID = "space-1"


class FakeConfluence:
    """An in-memory Confluence REST API (v2 pages and folders) over a real local HTTP socket.

    Holds one folder, POLEARMS, in one space. Like Confluence, page titles are unique per space.
    """

    def __init__(self):
        self.folder = {"id": FOLDER_ID, "title": "POLEARMS", "spaceId": SPACE_ID,
                       "parentId": None, "parentType": None}
        self.pages: dict[str, dict] = {}
        self.requests: list[tuple[str, str]] = []
        self.auth_headers: set[str] = set()
        self.fail_with: tuple[int, str] | None = None
        self._next_id = 100
        self._server: HTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def titles(self) -> list[str]:
        return sorted(p["title"] for p in self.pages.values())

    def parent_title(self, title: str) -> str | None:
        """Title of the page or folder this page sits under; None at the top of the space."""
        page = next(p for p in self.pages.values() if p["title"] == title)
        parent = page["parentId"]
        if parent == self.folder["id"]:
            return self.folder["title"]
        return self.pages[parent]["title"] if parent else None

    def add_page(self, title: str, parent_id: str | None = None, body: str = "") -> dict:
        """Put a page in the space directly, as someone else might have."""
        self._next_id += 1
        page_id = str(self._next_id)
        self.pages[page_id] = {
            "id": page_id, "title": title, "spaceId": SPACE_ID, "parentId": parent_id,
            "parentType": "folder" if parent_id == self.folder["id"] else "page",
            "version": {"number": 1}, "body": body,
        }
        return self.pages[page_id]

    def start(self) -> None:
        state = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, obj, status=200):
                payload = json.dumps(obj).encode() if not isinstance(obj, bytes) else obj
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def _body(self):
                return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

            def _begin(self) -> bool:
                state.requests.append((self.command, self.path))
                state.auth_headers.add(self.headers.get("Authorization", ""))
                if state.fail_with:
                    status, text = state.fail_with
                    self._reply(text.encode(), status)
                    return False
                return True

            def do_GET(self):
                if not self._begin():
                    return
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path.endswith("/user/current"):
                    return self._reply({"accountId": "acct-1"})
                if url.path == f"/api/v2/folders/{FOLDER_ID}":
                    return self._reply(state.folder)
                if url.path.startswith("/api/v2/folders/"):
                    return self._reply({"message": "not found"}, 404)
                if url.path == "/api/v2/pages":
                    title = query["title"][0]
                    space = query["space-id"][0]
                    return self._reply({"results": [
                        p for p in state.pages.values()
                        if p["title"] == title and p["spaceId"] == space]})
                self._reply({"message": "not found"}, 404)

            def do_POST(self):
                if not self._begin():
                    return
                body = self._body()
                if any(p["title"] == body["title"] and p["spaceId"] == body["spaceId"]
                       for p in state.pages.values()):
                    return self._reply({"message": "A page with this title already exists"}, 400)
                page = state.add_page(body["title"], body.get("parentId"),
                                      body["body"]["value"])
                page["spaceId"] = body["spaceId"]
                self._reply(page)

            def do_PUT(self):
                if not self._begin():
                    return
                body = self._body()
                page = state.pages[self.path.rsplit("/", 1)[1]]
                page.update(title=body["title"], version=body["version"],
                            body=body["body"]["value"])
                self._reply(page)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def confluence():
    server = FakeConfluence()
    server.start()
    yield server
    server.stop()
