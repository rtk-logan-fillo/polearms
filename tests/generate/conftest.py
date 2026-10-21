import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import pytest


class FakeConfluence:
    """An in-memory Confluence REST API served over a real local HTTP socket."""

    def __init__(self):
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
        page = next(p for p in self.pages.values() if p["title"] == title)
        return self.pages[page["ancestors"][-1]["id"]]["title"] if page["ancestors"] else None

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
                if url.path.endswith("/space"):
                    return self._reply({"results": [{"key": "~acct-1"}]})
                title = query["title"][0]
                self._reply({"results": [p for p in state.pages.values() if p["title"] == title]})

            def do_POST(self):
                if not self._begin():
                    return
                body = self._body()
                state._next_id += 1
                page_id = str(state._next_id)
                state.pages[page_id] = {
                    "id": page_id, "title": body["title"], "version": {"number": 1},
                    "ancestors": body.get("ancestors", []),
                    "body": body["body"]["storage"]["value"],
                }
                self._reply(state.pages[page_id])

            def do_PUT(self):
                if not self._begin():
                    return
                body = self._body()
                page = state.pages[self.path.rsplit("/", 1)[1]]
                page.update(title=body["title"], version=body["version"],
                            body=body["body"]["storage"]["value"])
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
