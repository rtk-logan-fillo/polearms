import io
import json
import urllib.error

import pytest

from scripts import swords_schema as ss

SCHEMA = {"a.b": {"datatype": "int", "is_list": False, "presence": "optional"}}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.delenv("GH_TOKEN", raising=False)


@pytest.fixture
def served(monkeypatch):
    """Replace the network with a canned response; records the requests made."""
    state = type("S", (), {"payload": json.dumps(SCHEMA).encode(), "requests": [], "error": None})()

    def fake_urlopen(request):
        state.requests.append(request)
        if state.error:
            raise state.error
        return FakeResponse(state.payload)

    monkeypatch.setattr(ss.urllib.request, "urlopen", fake_urlopen)
    return state


class TestSwordsType:
    @pytest.mark.parametrize("entry,expected", [
        ({"datatype": "int", "is_list": False}, "int"),
        ({"datatype": "int", "is_list": True}, "int[]"),
        ({"datatype": "string"}, "string"),
        ({"datatype": None, "is_list": True}, ""),
        ({}, ""),
        (None, ""),
    ])
    def test_type(self, entry, expected):
        assert ss.swords_type(entry) == expected


class TestGithubToken:
    def test_prefers_github_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "a")
        monkeypatch.setenv("GH_TOKEN", "b")
        assert ss.github_token() == "a"

    def test_falls_back_to_gh_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "b")
        assert ss.github_token() == "b"

    def test_falls_back_to_the_gh_cli(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setattr(ss.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "cli-token\n"})())
        assert ss.github_token() == "cli-token"

    def test_blank_when_there_is_no_token_and_no_gh(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        def missing(*a, **k):
            raise FileNotFoundError("gh")

        monkeypatch.setattr(ss.subprocess, "run", missing)
        assert ss.github_token() == ""


class TestFetch:
    def test_saves_the_schema_and_authenticates(self, tmp_path, token, served):
        path = tmp_path / "schema" / "s.json"
        ss.fetch_swords_schema(path)
        assert json.loads(path.read_text()) == SCHEMA
        (request,) = served.requests
        assert request.get_header("Authorization") == "Bearer tok"
        assert "raw" in request.get_header("Accept")
        assert not list(path.parent.glob("*.tmp"))

    def test_no_token_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ss, "github_token", lambda: "")
        with pytest.raises(SystemExit, match="no GitHub token"):
            ss.fetch_swords_schema(tmp_path / "s.json")
        assert not (tmp_path / "s.json").exists()

    def test_http_error_is_an_error_and_writes_nothing(self, tmp_path, token, served):
        served.error = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b"Not Found"))
        with pytest.raises(SystemExit, match=r"HTTP 404.*Not Found"):
            ss.fetch_swords_schema(tmp_path / "s.json")
        assert not (tmp_path / "s.json").exists()

    def test_network_error_is_an_error(self, tmp_path, token, served):
        served.error = urllib.error.URLError("no route")
        with pytest.raises(SystemExit, match="no route"):
            ss.fetch_swords_schema(tmp_path / "s.json")

    @pytest.mark.parametrize("payload", [b"not json", b"[]", b"{}"])
    def test_a_bad_payload_is_rejected_and_keeps_the_existing_file(self, tmp_path, token, served, payload):
        path = tmp_path / "s.json"
        path.write_text('{"old": {}}')
        served.payload = payload
        with pytest.raises(SystemExit):
            ss.fetch_swords_schema(path)
        assert path.read_text() == '{"old": {}}'


class TestLoad:
    def test_loads_an_existing_file_without_downloading(self, tmp_path, served):
        path = tmp_path / "s.json"
        path.write_text(json.dumps(SCHEMA))
        assert ss.load_swords_schema(path) == SCHEMA
        assert served.requests == []

    def test_downloads_when_missing(self, tmp_path, token, served, capsys):
        path = tmp_path / "s.json"
        assert ss.load_swords_schema(path) == SCHEMA
        assert len(served.requests) == 1
        assert "downloading the SWORDS schema" in capsys.readouterr().out

    def test_invalid_json_on_disk_is_an_error(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text("{oops")
        with pytest.raises(SystemExit, match="not valid JSON"):
            ss.load_swords_schema(path)

    def test_a_non_object_on_disk_is_an_error(self, tmp_path):
        path = tmp_path / "s.json"
        path.write_text("[]")
        with pytest.raises(SystemExit, match="must be a JSON object"):
            ss.load_swords_schema(path)


class TestMain:
    def test_always_downloads_a_fresh_copy(self, tmp_path, token, served, monkeypatch, capsys):
        path = tmp_path / "s.json"
        path.write_text(json.dumps({"stale": {}}))
        monkeypatch.setattr(ss, "SWORDS_SCHEMA_PATH", path)
        monkeypatch.setattr("sys.argv", ["swords_schema.py"])
        ss.main()
        assert json.loads(path.read_text()) == SCHEMA
        assert "saved the SWORDS schema (1 fields)" in capsys.readouterr().out
