import pytest
import yaml

import scripts.common as pc
from scripts.common import Mapping


class TestPathHelpers:
    @pytest.mark.parametrize("path,expected", [
        ("a.b", "a.b"),
        ("attacks[x].tactic.uid", "attacks.tactic.uid"),
        ("a[x].b[y].c", "a.b.c"),
        ("a[].b", "a.b"),
        ("a[uid!=null && x==1].b", "a.b"),
        ("", ""),
    ])
    def test_base_path(self, path, expected):
        assert pc.base_path(path) == expected

    @pytest.mark.parametrize("path,expected", [
        ("a.b", []),
        ("a[x].b", ["x"]),
        ("a[x].b[y]", ["x", "y"]),
        ("a[].b", [""]),
        ("a[uid!=null].b", ["uid!=null"]),
    ])
    def test_label_keys(self, path, expected):
        assert pc.label_keys(path) == expected

    def test_display_path_substitutes_labels(self):
        assert pc.display_path("a[x].b[y]", {"x": "i==0", "y": "k"}) == "a[i==0].b[k]"

    def test_display_path_without_labels_is_unchanged(self):
        assert pc.display_path("a[x].b", {}) == "a[x].b"

    def test_display_path_leaves_unlabelled_brackets(self):
        assert pc.display_path("a[x].b[]", {"x": "k"}) == "a[k].b[]"


class TestMapping:
    def test_a_single_string_polearms_path_is_stored_as_a_list(self):
        assert Mapping(polearms="a.b", swords="s").polearms == ["a.b"]

    def test_a_list_of_polearms_paths_is_kept(self):
        assert Mapping(polearms=["a", "b"], swords="s").polearms == ["a", "b"]

    def test_an_empty_string_means_no_polearms_path(self):
        assert Mapping(polearms="", swords="s").polearms == []

    def test_the_polearms_list_is_copied_not_shared(self):
        paths = ["a", "b"]
        mapping = Mapping(polearms=paths, swords="s")
        paths.append("c")
        assert mapping.polearms == ["a", "b"]

    def test_constructor_and_from_dict_agree(self):
        raw = {"polearms": "a[x].b", "swords": "s", "labels": {"x": "k"}, "mapper": {"fn": "map_x"}}
        assert Mapping(**raw) == Mapping.from_dict(raw)

    def test_from_dict_accepts_a_single_string_path(self):
        assert pc.Mapping.from_dict({"polearms": "a.b", "swords": "s"}).polearms == ["a.b"]

    def test_from_dict_accepts_a_list_of_paths(self):
        assert pc.Mapping.from_dict({"polearms": ["a", "b"], "swords": "s"}).polearms == ["a", "b"]

    def test_from_dict_defaults(self):
        m = pc.Mapping.from_dict({})
        assert (m.polearms, m.swords, m.labels, m.mapper) == ([], "", {}, None)

    def test_has_polearms(self):
        assert Mapping(polearms="a", swords="s").has_polearms()
        assert not Mapping(polearms="", swords="s").has_polearms()
        assert not Mapping(polearms=[], swords="s").has_polearms()
        assert Mapping(polearms=["", "a"], swords="s").has_polearms()

    def test_base_paths_skips_empty_paths(self):
        assert Mapping(polearms=["a[x].b", "", "c"], swords="s").base_paths() == ["a.b", "c"]

    def test_is_many_to_one(self):
        assert Mapping(polearms=["a", "b"], swords="s").is_many_to_one()
        assert not Mapping(polearms="a", swords="s").is_many_to_one()

    def test_is_list_item(self):
        assert Mapping(polearms="a", swords="t[].x").is_list_item()
        assert not Mapping(polearms="a", swords="t.x").is_list_item()

    def test_label_keys_cover_polearms_and_swords_but_ignore_bare_brackets(self):
        m = Mapping(polearms=["a[x].b", "c[]"], swords="t[y].z")
        assert m.label_keys() == {"x", "y"}

    def test_display_name_joins_displayed_paths(self):
        m = Mapping(polearms=["a[x].b", "c"], swords="s", labels={"x": "i==0"})
        assert m.display_name() == "a[i==0].b, c"

    def test_display_swords_and_swords_field_path(self):
        m = Mapping(polearms="a", swords="t[y].z", labels={"y": "k"})
        assert m.display_swords() == "t[k].z"
        assert m.swords_field_path() == "t.z"

    def test_mapper_fn_and_join_separator(self):
        m = Mapping(polearms="a", swords="s", mapper={"fn": "map_x", "join": ","})
        assert m.mapper_fn() == "map_x"
        assert m.join_separator() == ","

    def test_mapper_accessors_without_a_mapper(self):
        m = Mapping(polearms="a", swords="s")
        assert m.mapper_fn() == ""
        assert m.join_separator() is None


class TestClassConfig:
    def write(self, tmp_path, data):
        path = tmp_path / "config.yaml"
        path.write_text(yaml.safe_dump(data))
        return path

    def test_load(self, tmp_path):
        cfg = pc.ClassConfig.load(self.write(tmp_path, {
            "class_name": "widget",
            "essential_fields_only": True,
            "essential_fields": [{"polearms": "name", "expected": True}],
            "override_mappings": [{"polearms": "a", "swords": "s"}],
        }))
        assert cfg.name == "widget"
        assert cfg.essential_fields_only is True
        assert cfg.essential_fields == [{"polearms": "name", "expected": True}]
        assert [m.swords for m in cfg.override_mappings] == ["s"]

    def test_load_defaults(self, tmp_path):
        cfg = pc.ClassConfig.load(self.write(tmp_path, {"class_name": "widget"}))
        assert cfg.essential_fields_only is False
        assert cfg.essential_fields == [] and cfg.override_mappings == []

    def test_load_empty_file(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("")
        assert pc.ClassConfig.load(path).name == ""

    def test_covers_path(self, tmp_path):
        cfg = pc.ClassConfig.load(self.write(tmp_path, {
            "class_name": "w", "essential_fields": [{"polearms": "owner"}, {"polearms": "a[].b"}]}))
        assert cfg.covers_path("owner")
        assert cfg.covers_path("owner.email")          # lies under an essential field
        assert cfg.covers_path("a[x].b")               # [key] segments are ignored on both sides
        assert not cfg.covers_path("ownership")        # a prefix of the name is not a parent
        assert not cfg.covers_path("name")


class TestLoaders:
    def test_load_mappings(self, tmp_path):
        path = tmp_path / "m.yaml"
        path.write_text(yaml.safe_dump({"mappings": [
            {"polearms": "a", "swords": "s1"}, {"polearms": ["b", "c"], "swords": "s2"}]}))
        loaded = pc.load_mappings(path)
        assert [m.swords for m in loaded] == ["s1", "s2"]
        assert loaded[1].polearms == ["b", "c"]

    def test_load_mappings_with_no_entries(self, tmp_path):
        path = tmp_path / "m.yaml"
        path.write_text("")
        assert pc.load_mappings(path) == []

    def test_load_version_strips_whitespace(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("  1.2.3\n\n")
        assert pc.load_version(path) == "1.2.3"

    def test_load_version_rejects_an_empty_file(self, tmp_path):
        path = tmp_path / "VERSION"
        path.write_text("\n")
        with pytest.raises(SystemExit, match="is empty"):
            pc.load_version(path)

    def test_discover_class_configs_is_recursive_and_sorted(self, tmp_path):
        for rel in ("b/config.yaml", "a/config.yaml", "a/nested/config.yaml", "a/other.yaml"):
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_text("")
        found = [p.relative_to(tmp_path).as_posix() for p in pc.discover_class_configs(tmp_path)]
        assert found == ["a/config.yaml", "a/nested/config.yaml", "b/config.yaml"]


class TestSchemaDefinition:
    def test_load_definition(self, tmp_path):
        path = tmp_path / "d.yaml"
        path.write_text(yaml.safe_dump({"ocsf": {"version": "1.8.0"}}))
        assert pc.load_definition(path) == {"ocsf": {"version": "1.8.0"}}

    def test_an_empty_definition_file_is_an_empty_definition(self, tmp_path):
        path = tmp_path / "d.yaml"
        path.write_text("")
        assert pc.load_definition(path) == {}

    def test_definition_version(self):
        assert pc.definition_version({"ocsf": {"version": "1.8.0"}}, "ocsf") == "1.8.0"

    def test_definition_version_is_text_even_when_yaml_made_it_a_number(self):
        assert pc.definition_version({"ocsf": {"version": 1.8}}, "ocsf") == "1.8"

    @pytest.mark.parametrize("definition", [{}, {"ocsf": None}, {"ocsf": {}}, {"other": {"version": "1"}}])
    def test_definition_version_is_none_when_not_set(self, definition):
        assert pc.definition_version(definition, "ocsf") is None


class TestOCSFSchema:
    def test_lookup_class(self, mini_schema):
        assert mini_schema.lookup_class("widget")["caption"] == "Widget"

    def test_lookup_unknown_class_exits(self, mini_schema):
        with pytest.raises(SystemExit, match="not found in schema"):
            mini_schema.lookup_class("nope")

    def test_lookup_top_level_field(self, mini_schema):
        assert mini_schema.lookup_field("widget", "name")["caption"] == "Name"

    def test_lookup_nested_fields_through_objects(self, mini_schema):
        assert mini_schema.lookup_field("widget", "owner.email")["caption"] == "Email"
        assert mini_schema.lookup_field("widget", "owner.address.city")["caption"] == "City"

    def test_lookup_ignores_bracket_segments(self, mini_schema):
        assert mini_schema.lookup_field("widget", "owner[x].email") is not None

    @pytest.mark.parametrize("path", [
        "nope", "owner.nope", "name.child", "owner.address.nope", "",
    ])
    def test_lookup_invalid_paths_return_none(self, mini_schema, path):
        assert mini_schema.lookup_field("widget", path) is None

    def test_lookup_field_is_scoped_to_the_class(self, mini_schema):
        assert mini_schema.lookup_field("gadget", "name") is None
        assert mini_schema.lookup_field("widget", "serial") is None

    def test_lookup_field_in_unknown_class(self, mini_schema):
        assert mini_schema.lookup_field("nope", "name") is None

    def test_load_from_file(self, fake_project):
        assert pc.OCSFSchema.load(fake_project.schema).lookup_class("gadget")["uid"] == 2
