import io
import json
import urllib.error

import pytest

from scripts import axes_mappings as am

MAPPINGS = {
    "a.b": [{"operation": "rename", "stage": "OLAP", "forEach": False, "old": ["x-1", "x-2"]}],
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(am, "github_token", lambda: "tok")


@pytest.fixture
def served(monkeypatch):
    state = type("S", (), {"payload": json.dumps(MAPPINGS).encode(), "requests": [], "error": None})()

    def fake_urlopen(request):
        state.requests.append(request)
        if state.error:
            raise state.error
        return FakeResponse(state.payload)

    monkeypatch.setattr(am.urllib.request, "urlopen", fake_urlopen)
    return state


class TestSwordsToAxes:
    def test_inverts_the_old_lists(self):
        assert am.swords_to_axes(MAPPINGS) == {"x-1": ["a.b"], "x-2": ["a.b"]}

    def test_a_swords_field_feeding_several_axes_fields_lists_them_sorted(self):
        mappings = {
            "z": [{"operation": "rename", "old": ["s"]}],
            "a": [{"operation": "rename", "old": ["s"]}],
        }
        assert am.swords_to_axes(mappings) == {"s": ["a", "z"]}

    def test_includes_old_lists_of_nested_operations(self):
        mappings = {"a": [{"operation": "conditional", "when": {}, "operations": [
            {"operation": "rename", "old": ["deep"]}]}]}
        assert am.swords_to_axes(mappings) == {"deep": ["a"]}

    def test_operations_without_old_are_ignored(self):
        assert am.swords_to_axes({"a": [{"operation": "drop"}]}) == {}

    def test_a_field_repeated_across_operations_is_listed_once(self):
        mappings = {"a": [{"operation": "rename", "old": ["s"]}, {"operation": "tag", "old": ["s"]}]}
        assert am.swords_to_axes(mappings) == {"s": ["a"]}


class TestFetch:
    def test_saves_the_mappings_and_authenticates(self, tmp_path, token, served):
        path = tmp_path / "schema" / "a.json"
        am.fetch_axes_mappings(path)
        assert json.loads(path.read_text()) == MAPPINGS
        (request,) = served.requests
        assert request.get_header("Authorization") == "Bearer tok"
        assert not list(path.parent.glob("*.tmp"))

    def test_no_token_is_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(am, "github_token", lambda: "")
        with pytest.raises(SystemExit, match="no GitHub token"):
            am.fetch_axes_mappings(tmp_path / "a.json")
        assert not (tmp_path / "a.json").exists()

    def test_http_error_is_an_error_and_writes_nothing(self, tmp_path, token, served):
        served.error = urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b"Not Found"))
        with pytest.raises(SystemExit, match=r"HTTP 404.*Not Found"):
            am.fetch_axes_mappings(tmp_path / "a.json")
        assert not (tmp_path / "a.json").exists()

    def test_network_error_is_an_error(self, tmp_path, token, served):
        served.error = urllib.error.URLError("no route")
        with pytest.raises(SystemExit, match="no route"):
            am.fetch_axes_mappings(tmp_path / "a.json")

    @pytest.mark.parametrize("payload", [b"not json", b"[]", b"{}"])
    def test_a_bad_payload_is_rejected_and_keeps_the_existing_file(self, tmp_path, token, served, payload):
        path = tmp_path / "a.json"
        path.write_text('{"old": []}')
        served.payload = payload
        with pytest.raises(SystemExit):
            am.fetch_axes_mappings(path)
        assert path.read_text() == '{"old": []}'


class TestLoad:
    def test_loads_an_existing_file_without_downloading(self, tmp_path, served):
        path = tmp_path / "a.json"
        path.write_text(json.dumps(MAPPINGS))
        assert am.load_axes_mappings(path) == MAPPINGS
        assert served.requests == []

    def test_downloads_when_missing(self, tmp_path, token, served, capsys):
        path = tmp_path / "a.json"
        assert am.load_axes_mappings(path) == MAPPINGS
        assert len(served.requests) == 1
        assert "downloading the AXES mappings" in capsys.readouterr().out

    def test_invalid_json_on_disk_is_an_error(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text("{oops")
        with pytest.raises(SystemExit, match="not valid JSON"):
            am.load_axes_mappings(path)

    def test_a_non_object_on_disk_is_an_error(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text("[]")
        with pytest.raises(SystemExit, match="must be a JSON object"):
            am.load_axes_mappings(path)


class TestMain:
    def test_always_downloads_a_fresh_copy(self, tmp_path, token, served, monkeypatch, capsys):
        path = tmp_path / "a.json"
        path.write_text(json.dumps({"stale": []}))
        monkeypatch.setattr(am, "AXES_MAPPINGS_PATH", path)
        monkeypatch.setattr("sys.argv", ["axes_mappings.py"])
        am.main()
        assert json.loads(path.read_text()) == MAPPINGS
        assert "saved the AXES mappings (1 fields)" in capsys.readouterr().out
