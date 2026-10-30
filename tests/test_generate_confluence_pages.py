import sys

import pytest
import yaml

from scripts import generate_confluence_pages as gcp
from scripts.common import ClassConfig, Mapping
from tests.conftest import FOLDER_ID, SPACE_ID


def config(**kw):
    defaults = dict(name="widget", essential_fields_only=False, essential_fields=[], override_mappings=[])
    return ClassConfig(**{**defaults, **kw})


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


class TestEscapeHtml:
    def test_escapes_the_special_characters(self):
        assert gcp.escape_html('<a href="x">&</a>') == "&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;"

    def test_ampersand_is_escaped_first_so_nothing_is_double_escaped(self):
        assert gcp.escape_html("<") == "&lt;"

    def test_plain_text_is_unchanged(self):
        assert gcp.escape_html("plain text 123") == "plain text 123"


class TestRow:
    def test_shown_field_without_a_join(self):
        assert gcp.Row(polearms_field="a.b").shown_field() == "a.b"

    def test_shown_field_wraps_a_join(self):
        assert gcp.Row(polearms_field="a[k].b", join_sep=",").shown_field() == 'join(a[k].b, ",")'

    def test_an_empty_separator_is_still_a_join(self):
        assert gcp.Row(polearms_field="a", join_sep="").shown_field() == 'join(a, "")'


# ---------------------------------------------------------------------------
# essential-field filtering
# ---------------------------------------------------------------------------


class TestFilterMappingsToEssential:
    CFG = config(essential_fields=[{"polearms": "name"}, {"polearms": "owner"}])

    def test_keeps_only_mappings_covered_by_an_essential_field(self):
        kept = gcp.filter_mappings_to_essential(
            [Mapping(polearms="name", swords="a"), Mapping(polearms="tags", swords="b")], self.CFG)
        assert [m.swords for m in kept] == ["a"]

    def test_fields_under_an_essential_field_are_covered(self):
        kept = gcp.filter_mappings_to_essential([Mapping(polearms="owner.email", swords="a")], self.CFG)
        assert len(kept) == 1

    def test_many_to_one_is_kept_whole_or_not_at_all(self):
        partly = Mapping(polearms=["name", "tags"], swords="a", mapper={"fn": "map_x"})
        fully = Mapping(polearms=["name", "owner.email"], swords="b", mapper={"fn": "map_x"})
        kept = gcp.filter_mappings_to_essential([partly, fully], self.CFG)
        assert [m.swords for m in kept] == ["b"]
        assert kept[0].polearms == ["name", "owner.email"]

    def test_a_blank_path_makes_the_mapping_many_to_one_so_it_is_dropped(self):
        # A list with a blank entry is malformed (validate_mappings flags it); with two entries it
        # counts as many-to-one, and only one of them survives the filter.
        assert gcp.filter_mappings_to_essential([Mapping(polearms=["name", ""], swords="a")], self.CFG) == []

    def test_a_single_string_path_with_a_blank_value_is_dropped(self):
        assert gcp.filter_mappings_to_essential([Mapping(polearms="", swords="a")], self.CFG) == []

    def test_does_not_mutate_the_input(self):
        original = Mapping(polearms="name", swords="a")
        gcp.filter_mappings_to_essential([original], self.CFG)
        assert original.polearms == ["name"]


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

SWORDS = {
    "widget-name": {"datatype": "string", "is_list": False},
    "owner-tags": {"datatype": "string", "is_list": True},
}


def rows_for(mini_schema, mappings, overrides=(), essentials=(), swords=SWORDS):
    return gcp.build_mapping_rows(list(mappings), list(overrides), list(essentials),
                                  mini_schema, "widget", swords)


class TestBuildMappingRows:
    def test_direct_mapping(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="name", swords="widget-name")])
        assert (row.polearms_field, row.swords, row.swords_type) == ("name", "widget-name", "string")
        assert (row.mapping, row.source) == ("Direct", "Global")
        assert (row.caption, row.type_name, row.requirement) == ("Name", "string_t", "required")

    def test_schema_description_is_kept_as_html(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="name", swords="widget-name")])
        assert row.description == "The <i>name</i>."

    def test_mapper_is_complex(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="name", swords="widget-name", mapper={"fn": "map_x"})])
        assert row.mapping == "<strong>Complex</strong>"

    def test_many_to_one_is_labelled_and_produces_a_row_per_polearms_field(self, mini_schema):
        rows = rows_for(mini_schema, [Mapping(polearms=["name", "tags"], swords="s", mapper={"fn": "map_x"})])
        assert [r.polearms_field for r in rows] == ["name", "tags"]
        assert {r.mapping for r in rows} == {"<strong>Complex</strong> (many-to-one)"}

    def test_array_of_a_primitive_type_gets_brackets(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["tags"]["is_array"] = True
        (row,) = rows_for(mini_schema, [Mapping(polearms="tags", swords="s")])
        assert row.type_name == "string_t[]"

    def test_array_of_objects_keeps_the_plain_type(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        (row,) = rows_for(mini_schema, [Mapping(polearms="owner", swords="s")])
        assert row.type_name == "object_t"

    def test_a_non_array_is_unchanged(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["tags"]["is_array"] = False
        (row,) = rows_for(mini_schema, [Mapping(polearms="tags", swords="s")])
        assert row.type_name == "string_t"

    def test_unmapped_essential_array_fields_also_get_brackets(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["tags"]["is_array"] = True
        (row,) = rows_for(mini_schema, [], essentials=["tags"])
        assert row.type_name == "string_t[]"

    def test_list_swords_types_get_brackets(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="tags", swords="owner-tags")])
        assert row.swords_type == "string[]"

    def test_swords_type_comes_from_the_swords_schema_datatype(self, mini_schema):
        schema = {"a": {"datatype": "int", "is_list": False}, "b": {"datatype": "ip", "is_list": True}}
        rows = rows_for(mini_schema, [Mapping(polearms="name", swords="a"), Mapping(polearms="tags", swords="b")],
                        swords=schema)
        assert {r.swords: r.swords_type for r in rows} == {"a": "int", "b": "ip[]"}

    def test_swords_type_looks_up_the_path_without_its_labels(self, mini_schema):
        m = Mapping(polearms="owner[x].email", swords="t[y].z", labels={"x": "k", "y": "k"}, mapper={"fn": "map_x"})
        (row,) = rows_for(mini_schema, [m], swords={"t.z": {"datatype": "long", "is_list": False}})
        assert row.swords_type == "long"

    def test_a_swords_field_without_a_datatype_has_a_blank_type(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="tags", swords="s")],
                          swords={"s": {"datatype": None, "is_list": True}})
        assert row.swords_type == ""

    def test_unknown_swords_field_has_a_blank_type(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="name", swords="other")])
        assert row.swords_type == ""

    def test_labels_are_expanded_in_the_displayed_paths(self, mini_schema):
        m = Mapping(polearms="owner[x].email", swords="t[y].z", labels={"x": "i==0", "y": "k"}, mapper={"fn": "map_x"})
        (row,) = rows_for(mini_schema, [m])
        assert row.polearms_field == "owner[i==0].email"
        assert row.swords == "t[k].z"

    def test_join_separator_is_carried_through(self, mini_schema):
        (row,) = rows_for(mini_schema, [Mapping(polearms="tags", swords="s", mapper={"fn": "map_x", "join": ","})])
        assert row.shown_field() == 'join(tags, ",")'

    def test_an_override_replaces_the_global_mapping_for_the_same_swords_field(self, mini_schema):
        rows = rows_for(mini_schema,
                        [Mapping(polearms="name", swords="s")],
                        [Mapping(polearms="tags", swords="s")])
        assert [(r.polearms_field, r.source) for r in rows] == [("tags", "<strong>Override</strong>")]

    def test_mappings_to_fields_the_class_lacks_are_dropped(self, mini_schema):
        assert rows_for(mini_schema, [Mapping(polearms="serial", swords="s")]) == []

    def test_mappings_without_polearms_are_ignored(self, mini_schema):
        assert rows_for(mini_schema, [Mapping(polearms="", swords="s")]) == []

    def test_unmapped_essential_fields_get_a_blank_swords_row(self, mini_schema):
        rows = rows_for(mini_schema, [Mapping(polearms="name", swords="s")], essentials=["name", "tags"])
        by_field = {r.polearms_field: r for r in rows}
        assert by_field["tags"].swords == "" and by_field["tags"].mapping == ""
        assert by_field["tags"].caption == "Tags"

    def test_an_essential_field_covered_by_a_labelled_mapping_is_not_duplicated(self, mini_schema):
        m = Mapping(polearms="owner[x].email", swords="s", labels={"x": "k"}, mapper={"fn": "map_x"})
        rows = rows_for(mini_schema, [m], essentials=["owner[].email"])
        assert len(rows) == 1

    def test_rows_are_sorted_by_polearms_field(self, mini_schema):
        rows = rows_for(mini_schema, [Mapping(polearms="tags", swords="b"), Mapping(polearms="name", swords="a"),
                                      Mapping(polearms="owner.email", swords="c")])
        assert [r.polearms_field for r in rows] == ["name", "owner.email", "tags"]


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------


class TestTables:
    def test_table_structure_and_widths(self):
        html = gcp.table([("A", 60), ("B", 40)], [["1", "2"], ["3", "4"]])
        assert html.startswith('<table data-layout="full-width"')
        assert '<col style="width:60%"/><col style="width:40%"/>' in html
        assert "<th>A</th><th>B</th>" in html
        assert html.count("<tr>") == 3          # header + 2 rows
        assert "<td>3</td><td>4</td>" in html

    def test_column_widths_sum_to_100(self):
        assert sum(w for _, w in gcp.MAPPING_COLUMNS) == 100
        assert sum(w for _, w in gcp.ESSENTIAL_COLUMNS) == 100

    def test_mapping_table_escapes_values_but_not_the_html_description(self):
        row = gcp.Row(polearms_field="a<b", caption="<c>", description="<p>ok</p>",
                      swords="s&t", mapping="<strong>Complex</strong>")
        html = gcp.build_mapping_table([row])
        assert "<code>a&lt;b</code>" in html
        assert "<td>&lt;c&gt;</td>" in html
        assert "<td><p>ok</p></td>" in html
        assert "<code>s&amp;t</code>" in html
        assert "<td><strong>Complex</strong></td>" in html

    def test_mapping_table_leaves_swords_blank_for_unmapped_rows(self):
        html = gcp.build_mapping_table([gcp.Row(polearms_field="a")])
        assert "<code></code>" not in html

    def test_essential_fields_table(self, mini_schema):
        html = gcp.build_essential_fields_table(
            [{"polearms": "tags"}, {"polearms": "name", "expected": True}], mini_schema, "widget")
        assert html.index("<code>name</code>") < html.index("<code>tags</code>")   # sorted
        assert "<strong>Yes</strong>" in html and "<td>No</td>" in html
        assert "<td>Name</td>" in html and "<td>The <i>name</i>.</td>" in html

    def test_essential_field_unknown_to_the_schema_gets_blank_columns(self, mini_schema):
        html = gcp.build_essential_fields_table([{"polearms": "bogus"}], mini_schema, "widget")
        assert "<code>bogus</code></td><td></td><td></td>" in html


# ---------------------------------------------------------------------------
# build_pages
# ---------------------------------------------------------------------------


class TestBuildPages:
    GLOBALS = [Mapping(polearms="name", swords="widget-name"), Mapping(polearms="owner.email", swords="owner-email")]

    def build(self, mini_schema, cfg, globals_=None):
        return gcp.build_pages("3.1.4", cfg, self.GLOBALS if globals_ is None else globals_,
                               mini_schema, SWORDS)

    def test_two_pages_titled_by_caption_and_version(self, mini_schema):
        mappings, essential = self.build(mini_schema, config())
        assert mappings.title == "Widget 3.1.4 - Mappings"
        assert essential.title == "Widget 3.1.4 - Essential Fields"

    def test_hierarchy_is_version_then_class_below_the_base_folder(self, mini_schema):
        for page in self.build(mini_schema, config()):
            assert page.hierarchy == ["3.1.4", "Widget 3.1.4"]

    def test_class_description_is_prepended_as_a_paragraph(self, mini_schema):
        mappings, _ = self.build(mini_schema, config())
        assert mappings.body.startswith("<p>A <b>widget</b>.</p><table")

    def test_no_paragraph_when_the_class_has_no_description(self, mini_schema):
        mappings, _ = self.build(mini_schema, config(name="gadget"), globals_=[])
        assert mappings.body.startswith("<table")

    def test_summary_counts_mapped_and_unmapped_fields(self, mini_schema):
        cfg = config(essential_fields=[{"polearms": "name"}, {"polearms": "tags"}])
        mappings, essential = self.build(mini_schema, cfg)
        assert mappings.summary == "3 fields (2 mapped, 1 unmapped)"
        assert essential.summary == "2 essential fields"

    def test_class_overrides_are_applied(self, mini_schema):
        cfg = config(override_mappings=[Mapping(polearms="tags", swords="widget-name")])
        mappings, _ = self.build(mini_schema, cfg)
        assert "<strong>Override</strong>" in mappings.body

    def test_essential_fields_only_restricts_the_mappings_page(self, mini_schema):
        cfg = config(essential_fields_only=True, essential_fields=[{"polearms": "name"}])
        mappings, _ = self.build(mini_schema, cfg)
        assert "<code>name</code>" in mappings.body
        assert "owner.email" not in mappings.body

    def test_unknown_class_exits(self, mini_schema):
        with pytest.raises(SystemExit, match="not found in schema"):
            self.build(mini_schema, config(name="nope"))


# ---------------------------------------------------------------------------
# Confluence client and publishing (against the fake server)
# ---------------------------------------------------------------------------


def client_for(server, user="me@example.com", token="s3cret"):
    return gcp.ConfluenceClient(server.url, user, token)


class TestConfluenceClient:
    def test_sends_basic_auth_and_json_headers(self, confluence):
        client_for(confluence).current_user()
        import base64
        (header,) = confluence.auth_headers
        assert base64.b64decode(header.removeprefix("Basic ")).decode() == "me@example.com:s3cret"

    def test_base_url_trailing_slash_is_tolerated(self, confluence):
        assert gcp.ConfluenceClient(confluence.url + "/", "u", "t").current_user() == "acct-1"

    def test_current_user_prefers_account_id(self, confluence):
        assert client_for(confluence).current_user() == "acct-1"

    def test_get_folder(self, confluence):
        folder = client_for(confluence).get_folder(FOLDER_ID)
        assert (folder["title"], folder["spaceId"]) == ("POLEARMS", SPACE_ID)

    def test_get_folder_that_does_not_exist_exits(self, confluence):
        with pytest.raises(SystemExit, match="HTTP 404"):
            client_for(confluence).get_folder("1")

    def test_find_page_returns_none_when_absent(self, confluence):
        assert client_for(confluence).find_page(SPACE_ID, "Nope") is None

    def test_create_then_find(self, confluence):
        client = client_for(confluence)
        created = client.create_page(SPACE_ID, FOLDER_ID, "Title", "<p>x</p>")
        found = client.find_page(SPACE_ID, "Title")
        assert found["id"] == created["id"] and found["version"]["number"] == 1
        assert found["parentId"] == FOLDER_ID and found["body"] == "<p>x</p>"

    def test_find_page_is_scoped_to_the_space(self, confluence):
        client_for(confluence).create_page(SPACE_ID, FOLDER_ID, "Title", "")
        assert client_for(confluence).find_page("other-space", "Title") is None

    def test_update_replaces_body_and_version(self, confluence):
        client = client_for(confluence)
        page = client.create_page(SPACE_ID, FOLDER_ID, "T", "old")
        client.update_page(page["id"], "T", "new", 2)
        assert confluence.pages[page["id"]]["body"] == "new"
        assert confluence.pages[page["id"]]["version"] == {"number": 2}

    def test_find_or_create_creates_once_then_finds(self, confluence):
        client = client_for(confluence)
        first, created1 = client.find_or_create_page(SPACE_ID, FOLDER_ID, "Root")
        second, created2 = client.find_or_create_page(SPACE_ID, FOLDER_ID, "Root")
        assert (created1, created2) == (True, False)
        assert first["id"] == second["id"]
        assert confluence.titles() == ["Root"]

    def test_find_or_create_refuses_a_page_of_that_title_under_another_parent(self, confluence):
        existing = confluence.add_page("Moved", parent_id=None)
        with pytest.raises(SystemExit, match=rf"already exists.*not under.*page id {existing['id']}"):
            client_for(confluence).find_or_create_page(SPACE_ID, FOLDER_ID, "Moved")
        assert confluence.pages[existing["id"]]["parentId"] is None   # left alone

    def test_http_errors_exit_with_the_status_and_body(self, confluence):
        confluence.fail_with = (401, "bad credentials")
        with pytest.raises(SystemExit, match=r"HTTP 401.*bad credentials"):
            client_for(confluence).current_user()


def sample_pages(mini_schema, version="1.2.3"):
    return gcp.build_pages(version, config(essential_fields=[{"polearms": "name"}]),
                           [Mapping(polearms="name", swords="widget-name")], mini_schema, SWORDS)


class TestPublishPages:
    def test_creates_the_hierarchy_and_both_pages(self, confluence, mini_schema):
        gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        assert confluence.titles() == sorted([
            "1.2.3", "Widget 1.2.3",
            "Widget 1.2.3 - Mappings", "Widget 1.2.3 - Essential Fields"])
        assert confluence.parent_title("1.2.3") == "POLEARMS"
        assert confluence.parent_title("Widget 1.2.3") == "1.2.3"
        assert confluence.parent_title("Widget 1.2.3 - Mappings") == "Widget 1.2.3"
        assert confluence.parent_title("Widget 1.2.3 - Essential Fields") == "Widget 1.2.3"

    def test_publishes_the_page_bodies(self, confluence, mini_schema):
        pages = sample_pages(mini_schema)
        gcp.publish_pages(pages, client_for(confluence))
        bodies = {p["title"]: p["body"] for p in confluence.pages.values()}
        assert all(bodies[page.title] == page.body for page in pages)

    def test_publishing_again_updates_in_place_without_duplicating(self, confluence, mini_schema):
        client = client_for(confluence)
        gcp.publish_pages(sample_pages(mini_schema), client)
        count = len(confluence.pages)
        gcp.publish_pages(sample_pages(mini_schema), client)
        assert len(confluence.pages) == count
        mappings = next(p for p in confluence.pages.values() if p["title"].endswith("- Mappings"))
        assert mappings["version"]["number"] == 2

    def test_a_new_version_gets_its_own_branch_of_the_tree(self, confluence, mini_schema):
        client = client_for(confluence)
        gcp.publish_pages(sample_pages(mini_schema, "1.0.0"), client)
        gcp.publish_pages(sample_pages(mini_schema, "2.0.0"), client)
        assert {"1.0.0", "2.0.0", "Widget 1.0.0 - Mappings", "Widget 2.0.0 - Mappings"} <= set(confluence.titles())
        assert confluence.parent_title("1.0.0") == confluence.parent_title("2.0.0") == "POLEARMS"

    def test_prints_progress(self, confluence, mini_schema, capsys):
        gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        out = capsys.readouterr().out
        assert "Authenticating... ok" in out and "Publishing under folder POLEARMS (6981780874)" in out
        assert "Created page: Widget 1.2.3 - Mappings" in out

    def test_the_base_folder_itself_is_never_modified(self, confluence, mini_schema):
        gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        assert confluence.folder == {"id": FOLDER_ID, "title": "POLEARMS", "spaceId": SPACE_ID,
                                     "parentId": None, "parentType": None}
        assert not any(method != "GET" and FOLDER_ID in path for method, path in confluence.requests)

    def test_a_folder_with_the_wrong_title_aborts_before_writing(self, confluence, mini_schema):
        confluence.folder["title"] = "Something else"
        with pytest.raises(SystemExit, match="is titled 'Something else', expected 'POLEARMS'"):
            gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        assert confluence.pages == {}

    def test_a_missing_base_folder_aborts_before_writing(self, confluence, mini_schema, monkeypatch):
        monkeypatch.setattr(gcp, "BASE_FOLDER_ID", "111")
        with pytest.raises(SystemExit, match="HTTP 404"):
            gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        assert confluence.pages == {}

    def test_does_not_adopt_a_same_titled_page_elsewhere_in_the_space(self, confluence, mini_schema):
        other = confluence.add_page("Widget 1.2.3 - Mappings", parent_id=None, body="someone else's")
        with pytest.raises(SystemExit, match="not under the expected parent"):
            gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        assert confluence.pages[other["id"]]["body"] == "someone else's"
        assert confluence.pages[other["id"]]["version"] == {"number": 1}

    def test_an_api_failure_aborts_the_publish(self, confluence, mini_schema):
        confluence.fail_with = (500, "boom")
        with pytest.raises(SystemExit, match="HTTP 500"):
            gcp.publish_pages(sample_pages(mini_schema), client_for(confluence))
        assert confluence.pages == {}


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


@pytest.fixture
def project(fake_project, confluence, monkeypatch):
    for name, path in {
        "SCHEMA_PATH": fake_project.schema, "MAPPINGS_PATH": fake_project.mappings,
        "VERSION_PATH": fake_project.version, "CONFIG_DIR": fake_project.config_dir,
    }.items():
        monkeypatch.setattr(gcp, name, path)
    monkeypatch.setattr(gcp, "SWORDS_SCHEMA_PATH", fake_project.swords_schema)
    monkeypatch.setattr(gcp, "CONFLUENCE_URL", confluence.url)
    return fake_project


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["confluence_pages.py", *args])
    gcp.main()


class TestMain:
    def test_publishes_pages_for_every_class_using_the_version_file(self, project, confluence, monkeypatch):
        run_main(monkeypatch, "--confluence-user", "me", "--confluence-token", "tok")
        assert "Widget 1.2.3 - Mappings" in confluence.titles()
        assert "Widget 1.2.3 - Essential Fields" in confluence.titles()

    def test_uses_the_given_credentials(self, project, confluence, monkeypatch):
        run_main(monkeypatch, "--confluence-user", "me", "--confluence-token", "tok")
        import base64
        (header,) = confluence.auth_headers
        assert base64.b64decode(header.removeprefix("Basic ")).decode() == "me:tok"

    def test_follows_the_version_file(self, project, confluence, monkeypatch):
        project.version.write_text('{"version": "9.9.9"}')
        run_main(monkeypatch, "--confluence-user", "u", "--confluence-token", "t")
        assert "Widget 9.9.9 - Mappings" in confluence.titles()
        assert not any("1.2.3" in t for t in confluence.titles())

    def test_a_dev_version_gets_its_own_page_tree(self, project, confluence, monkeypatch):
        project.version.write_text('{"version": "1.10.0-dev"}')
        run_main(monkeypatch, "--confluence-user", "u", "--confluence-token", "t")
        assert "1.10.0-dev" in confluence.titles()
        assert "Widget 1.10.0-dev - Mappings" in confluence.titles()

    @pytest.mark.parametrize("args", [
        [], ["--confluence-user", "u"], ["--confluence-token", "t"],
    ])
    def test_both_credentials_are_required(self, project, monkeypatch, args):
        with pytest.raises(SystemExit) as exc:
            run_main(monkeypatch, *args)
        assert exc.value.code == 2

    def test_no_class_configs_is_an_error(self, project, confluence, monkeypatch):
        project.widget_config.unlink()
        with pytest.raises(SystemExit, match="no class configs"):
            run_main(monkeypatch, "--confluence-user", "u", "--confluence-token", "t")
        assert confluence.pages == {}

    @pytest.mark.parametrize("contents,message", [
        ("", "is not valid JSON"),
        ('{"version": ""}', 'non-empty string "version"'),
        ("{}", 'non-empty string "version"'),
    ])
    def test_a_bad_version_file_is_an_error_and_publishes_nothing(self, project, confluence, monkeypatch, contents, message):
        project.version.write_text(contents)
        with pytest.raises(SystemExit, match=message):
            run_main(monkeypatch, "--confluence-user", "u", "--confluence-token", "t")
        assert confluence.pages == {}


class TestRealRepository:
    """Every real class config must build its pages without error, using the real schema."""

    def test_all_classes_build(self):
        import scripts.common as pc
        schema = pc.OCSFSchema.load(pc.SCHEMA_PATH)
        globals_ = pc.load_mappings(pc.MAPPINGS_PATH)
        paths = pc.discover_class_configs(pc.CONFIG_DIR)
        assert paths
        for path in paths:
            pages = gcp.build_pages("0.0.0", pc.ClassConfig.load(path), globals_, schema, {})
            assert len(pages) == 2 and all(p.body.startswith(("<p>", "<table")) for p in pages)

    def test_vendor_overflow_page_has_the_expected_shape(self):
        import scripts.common as pc
        schema = pc.OCSFSchema.load(pc.SCHEMA_PATH)
        cfg = pc.ClassConfig.load(pc.CONFIG_DIR / "arcticwolf" / "vendor_overflow" / "config.yaml")
        mappings, essential = gcp.build_pages("1", cfg, pc.load_mappings(pc.MAPPINGS_PATH), schema, {})
        assert mappings.title == "Vendor Overflow 1 - Mappings"
        assert essential.summary == f"{len(cfg.essential_fields)} essential fields"
        # Rendered inside <code>, so the quotes in join(..., ",") are HTML-escaped.
        assert "join(attacks[technique.uid!=null].technique.uid, &quot;,&quot;)" in mappings.body
