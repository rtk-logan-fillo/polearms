import io
import json
import urllib.error

import pytest

from scripts import axes_mappings as am

LISTING = [
    {"type": "file", "name": "_ecs_mappings.yaml", "url": "https://x/_ecs_mappings.yaml"},
    {"type": "file", "name": "cloud.yaml", "url": "https://x/cloud.yaml"},
    {"type": "file", "name": "README.md", "url": "https://x/README.md"},
    {"type": "dir", "name": "sub", "url": "https://x/sub"},
]
FILES = {
    "https://x/_ecs_mappings.yaml": "# generated\n---\n- old: host.id\n  ecs: host.id\n  type: keyword\n",
    "https://x/cloud.yaml": (
        "- old: cloud.client.auth.ip\n  ecs: host.ip\n  type: keyword\n"
        "- old: cloud.client.agent.name\n  ecs: TODO\n  type: keyword\n"
    ),
}


def entry(old, ecs, file="x.yaml", **kw):
    return {"file": file, "old": old, "ecs": ecs, **kw}


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
    """Replace the network with canned responses by URL; records the requests made."""
    state = type("S", (), {"listing": LISTING, "files": dict(FILES), "requests": [], "error": None})()

    def fake_urlopen(request):
        state.requests.append(request)
        if state.error:
            raise state.error
        url = request.full_url
        if url == am.MAPPINGS_DIR_URL:
            return FakeResponse(json.dumps(state.listing).encode())
        return FakeResponse(state.files[url].encode())

    monkeypatch.setattr(am.urllib.request, "urlopen", fake_urlopen)
    return state


class TestSwordsToAxes:
    def test_maps_old_to_ecs(self):
        assert am.swords_to_axes([entry("cloud.client.auth.ip", "host.ip")]) == {
            "cloud.client.auth.ip": ["host.ip"]}

    def test_a_one_to_one_mapping_maps_a_field_to_itself(self):
        assert am.swords_to_axes([entry("host.id", "host.id", file=am.ONE_TO_ONE_FILE)]) == {
            "host.id": ["host.id"]}

    def test_the_other_files_win_over_the_one_to_one_file(self):
        entries = [
            entry("ad.event.user.ip", "ad.event.user.ip", file=am.ONE_TO_ONE_FILE),
            entry("ad.event.user.ip", "client.ip", file="ad.yaml"),
        ]
        assert am.swords_to_axes(entries) == {"ad.event.user.ip": ["client.ip"]}

    def test_a_field_in_several_other_files_lists_every_axes_field_sorted(self):
        entries = [entry("s", "z", file="a.yaml"), entry("s", "a", file="b.yaml")]
        assert am.swords_to_axes(entries) == {"s": ["a", "z"]}

    def test_also_adds_a_second_axes_field(self):
        assert am.swords_to_axes([entry("c-hostname", "client.domain", also="client.name")]) == {
            "c-hostname": ["client.domain", "client.name"]}

    @pytest.mark.parametrize("placeholder", ["TODO", "DROP", "COMPLEX"])
    def test_placeholders_are_not_axes_fields(self, placeholder):
        assert am.swords_to_axes([entry("s", placeholder)]) == {}

    def test_a_placeholder_in_another_file_leaves_the_one_to_one_mapping(self):
        entries = [
            entry("av.event.user", "av.event.user", file=am.ONE_TO_ONE_FILE),
            entry("av.event.user", "TODO", file="av.yaml"),
        ]
        assert am.swords_to_axes(entries) == {"av.event.user": ["av.event.user"]}

    def test_the_base_prefix_is_removed_from_both_sides(self):
        entries = [entry("base.c-ip", "client.ip"), entry("base.telemetry-types", "base.telemetry_types")]
        assert am.swords_to_axes(entries) == {"c-ip": ["client.ip"], "telemetry-types": ["telemetry_types"]}


class TestParseMappingFile:
    def test_keeps_old_ecs_and_also(self):
        text = "---\n- old: a\n  ecs: b\n  also: c\n  type: keyword\n  docs: ignored\n"
        assert am.parse_mapping_file("f.yaml", text) == [
            {"file": "f.yaml", "old": "a", "ecs": "b", "also": "c"}]

    def test_an_empty_file_has_no_entries(self):
        assert am.parse_mapping_file("f.yaml", "# nothing\n") == []

    def test_a_non_list_is_an_error(self):
        with pytest.raises(SystemExit, match="must be a list"):
            am.parse_mapping_file("f.yaml", "a: b\n")

    def test_an_entry_without_ecs_is_an_error(self):
        with pytest.raises(SystemExit, match="without an old and an ecs"):
            am.parse_mapping_file("f.yaml", "- old: a\n")

    def test_invalid_yaml_is_an_error(self):
        with pytest.raises(SystemExit, match="cannot parse f.yaml"):
            am.parse_mapping_file("f.yaml", "- old: [unclosed\n")


class TestFetch:
    def test_saves_the_entries_of_every_yaml_file_and_authenticates(self, tmp_path, token, served):
        path = tmp_path / "schema" / "a.json"
        am.fetch_axes_mappings(path)
        saved = json.loads(path.read_text())
        assert [(e["file"], e["old"], e["ecs"]) for e in saved] == [
            ("_ecs_mappings.yaml", "host.id", "host.id"),
            ("cloud.yaml", "cloud.client.auth.ip", "host.ip"),
            ("cloud.yaml", "cloud.client.agent.name", "TODO"),
        ]
        assert all(r.get_header("Authorization") == "Bearer tok" for r in served.requests)
        assert len(served.requests) == 3        # the listing and two yaml files
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

    def test_no_entries_is_rejected_and_keeps_the_existing_file(self, tmp_path, token, served):
        path = tmp_path / "a.json"
        path.write_text("[1]")
        served.listing = []
        with pytest.raises(SystemExit, match="no entries"):
            am.fetch_axes_mappings(path)
        assert path.read_text() == "[1]"

    def test_a_listing_that_is_not_a_list_is_rejected(self, tmp_path, token, served):
        served.listing = {"message": "nope"}
        with pytest.raises(SystemExit, match="not a list"):
            am.fetch_axes_mappings(tmp_path / "a.json")


class TestLoad:
    def test_loads_an_existing_file_without_downloading(self, tmp_path, served):
        path = tmp_path / "a.json"
        path.write_text(json.dumps([entry("a", "b")]))
        assert am.load_axes_mappings(path) == [entry("a", "b")]
        assert served.requests == []

    def test_downloads_when_missing(self, tmp_path, token, served, capsys):
        path = tmp_path / "a.json"
        assert len(am.load_axes_mappings(path)) == 3
        assert "downloading the AXES mappings" in capsys.readouterr().out

    def test_invalid_json_on_disk_is_an_error(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text("{oops")
        with pytest.raises(SystemExit, match="not valid JSON"):
            am.load_axes_mappings(path)

    def test_a_non_list_on_disk_is_an_error(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text("{}")
        with pytest.raises(SystemExit, match="must be a JSON list"):
            am.load_axes_mappings(path)


class TestMain:
    def test_always_downloads_a_fresh_copy(self, tmp_path, token, served, monkeypatch, capsys):
        path = tmp_path / "a.json"
        path.write_text(json.dumps([entry("stale", "stale")]))
        monkeypatch.setattr(am, "AXES_MAPPINGS_PATH", path)
        monkeypatch.setattr("sys.argv", ["axes_mappings.py"])
        am.main()
        assert len(json.loads(path.read_text())) == 3
        assert "saved the AXES mappings (3 entries)" in capsys.readouterr().out
