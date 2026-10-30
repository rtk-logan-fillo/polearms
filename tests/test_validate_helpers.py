import pytest

from scripts import validate_helpers as v


class TestIssues:
    def test_error_and_warning_set_the_severity(self):
        assert v.error("t", "s", "m") == v.Issue("t", "s", v.SEVERITY_ERROR, "m")
        assert v.warning("t", "s", "m") == v.Issue("t", "s", v.SEVERITY_WARNING, "m")

    def test_issues_are_immutable(self):
        with pytest.raises(Exception):
            v.error("t", "s", "m").message = "changed"

    def test_has_errors(self):
        assert v.has_errors([v.warning("t", "s", "m"), v.error("t", "s", "m")])
        assert not v.has_errors([v.warning("t", "s", "m")])
        assert not v.has_errors([])


class TestReport:
    def test_ok(self, capsys):
        v.report("scope", [])
        assert capsys.readouterr().out == "scope: ok\n"

    def test_counts_and_lines(self, capsys):
        v.report("scope", [v.error("a", "format", "bad"), v.warning("b", "shadow", "hm"),
                           v.error("c", "format", "worse")])
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "scope: 2 error(s), 1 warning(s)"
        assert lines[1] == "  ERROR   [format] a: bad"
        assert lines[2] == "  WARNING [shadow] b: hm"
        assert len(lines) == 4


class TestExitIfErrors:
    def test_exits_1_on_errors(self):
        with pytest.raises(SystemExit) as exc:
            v.exit_if_errors([v.error("t", "s", "m")])
        assert exc.value.code == 1

    def test_warnings_and_nothing_do_not_exit(self):
        v.exit_if_errors([v.warning("t", "s", "m")])
        v.exit_if_errors([])


# ---------------------------------------------------------------------------
# JSON Schema validation
# ---------------------------------------------------------------------------

import json

import yaml

from scripts.common import (
    CONFIG_DIR,
    MAPPINGS_PATH,
    SCHEMA_DEFINITION_PATH,
    VERSION_PATH,
    discover_class_configs,
)

SCHEMA_FILES = sorted(v.SCHEMAS_DIR.glob("*.schema.json"))


class TestSchemaFiles:
    def test_all_the_schemas_exist(self):
        assert {p.name for p in SCHEMA_FILES} == {
            "config.schema.json", "mapping.schema.json", "mappings.schema.json",
            "schema_definition.schema.json", "version.schema.json"}

    @pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
    def test_each_is_a_valid_json_schema(self, path):
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(json.loads(path.read_text()))

    @pytest.mark.parametrize("path", SCHEMA_FILES, ids=lambda p: p.name)
    def test_each_id_matches_its_file_name_so_refs_resolve(self, path):
        assert json.loads(path.read_text())["$id"] == path.name

    @pytest.mark.parametrize("name", ["config.schema.json", "mappings.schema.json",
                                      "schema_definition.schema.json", "version.schema.json"])
    def test_top_level_documents_reject_unknown_keys(self, name):
        assert json.loads((v.SCHEMAS_DIR / name).read_text())["additionalProperties"] is False

    def test_load_json_schema(self):
        assert v.load_json_schema("config.schema.json")["title"] == "Class config.yaml"


class TestValidateAgainstSchema:
    def test_valid_document_has_no_issues(self):
        assert v.validate_against_schema({"mappings": []}, "mappings.schema.json", "t") == []

    def test_issues_are_json_schema_errors_for_the_given_target(self):
        (issue,) = v.validate_against_schema({"mappings": [{"polearms": "a"}]}, "mappings.schema.json", "m.yaml")
        assert issue == v.Issue("m.yaml:mappings[0]", "json-schema", "error", "'swords' is required")

    def test_a_document_level_error_uses_the_bare_target(self):
        (issue,) = v.validate_against_schema([], "mappings.schema.json", "m.yaml")
        assert issue.target == "m.yaml" and "is not of type 'object'" in issue.message

    def test_locations_use_dots_for_keys_and_brackets_for_indexes(self):
        doc = {"mappings": [{"polearms": "a", "swords": "s", "labels": {"x": 5}}]}
        (issue,) = v.validate_against_schema(doc, "mappings.schema.json", "t")
        assert issue.target == "t:mappings[0].labels.x"

    def test_one_issue_per_violation_in_document_order(self):
        doc = {"mappings": [{"polearms": "a"}, {"swords": "s"}, {"polearms": "b", "swords": "s", "z": 1}]}
        issues = v.validate_against_schema(doc, "mappings.schema.json", "t")
        assert [(i.target, i.message) for i in issues] == [
            ("t:mappings[0]", "'swords' is required"),
            ("t:mappings[1]", "'polearms' is required"),
            ("t:mappings[2]", "unknown key(s) 'z'"),
        ]

    def test_refs_between_schema_files_resolve(self):
        # config.schema.json -> mapping.schema.json: a bad override mapping is found through the $ref.
        doc = {"class_name": "w", "class_uid": 1, "override_mappings": [{"swords": "s"}]}
        (issue,) = v.validate_against_schema(doc, "config.schema.json", "t")
        assert issue.target == "t:override_mappings[0]" and issue.message == "'polearms' is required"

    def test_integers_are_strict(self):
        for bad in (1.0, True, "1", None):
            issues = v.validate_against_schema({"class_name": "w", "class_uid": bad}, "config.schema.json", "t")
            assert issues, bad
        assert v.validate_against_schema({"class_name": "w", "class_uid": 1}, "config.schema.json", "t") == []

    def test_pattern_errors_describe_the_expected_value_not_the_regex(self):
        doc = {"ocsf": {"version": "1.8"}, "arcticwolf_extension": {"version": "1.0.0"}}
        (issue,) = v.validate_against_schema(doc, "schema_definition.schema.json", "t")
        assert "expected a semantic version" in issue.message and "\\d" not in issue.message

    def test_unknown_keys_are_all_named(self):
        (issue,) = v.validate_against_schema({"mappings": [], "a": 1, "b": 2}, "mappings.schema.json", "t")
        assert issue.message == "unknown key(s) 'a', 'b'"

    def test_semantic_version_pattern(self):
        ok = ["1.0.0", "0.0.1", "10.20.30", "1.0.0-rc.1", "1.0.0+build.5", "1.0.0-rc.1+b"]
        bad = ["1.0", "1", "v1.0.0", "1.0.0.0", "", "a.b.c", " 1.0.0"]
        for version in ok:
            assert not v.validate_against_schema(
                {"ocsf": {"version": version}, "arcticwolf_extension": {"version": "1.0.0"}},
                "schema_definition.schema.json", "t"), version
        for version in bad:
            assert v.validate_against_schema(
                {"ocsf": {"version": version}, "arcticwolf_extension": {"version": "1.0.0"}},
                "schema_definition.schema.json", "t"), version


class TestVersionSchema:
    @pytest.mark.parametrize("version", [
        "0.0.0", "1.10.0", "1.10.0-dev", "1.10.0-dev.2", "1.0.0-rc.1", "1.0.0+build.5", "1.0.0-rc.1+b",
    ])
    def test_accepts_semantic_versions_including_pre_releases(self, version):
        assert v.validate_against_schema({"version": version}, "version.schema.json", "t") == []

    @pytest.mark.parametrize("version", ["1.0", "1", "v1.0.0", "1.0.0.0", "", " 1.0.0", "1.0.0-", "dev", None, 1, 1.0])
    def test_rejects_everything_else(self, version):
        assert v.validate_against_schema({"version": version}, "version.schema.json", "t")


class TestRealFilesMatchTheirSchemas:
    def test_mappings_yaml(self):
        assert v.validate_against_schema(
            yaml.safe_load(MAPPINGS_PATH.read_text()), "mappings.schema.json", "mappings.yaml") == []

    def test_schema_definition_yaml(self):
        assert v.validate_against_schema(
            yaml.safe_load(SCHEMA_DEFINITION_PATH.read_text()),
            "schema_definition.schema.json", "schema_definition.yaml") == []

    def test_version_json(self):
        assert v.validate_against_schema(
            json.loads(VERSION_PATH.read_text()), "version.schema.json", "version.json") == []

    def test_every_class_config(self):
        paths = discover_class_configs(CONFIG_DIR)
        assert paths
        for path in paths:
            assert v.validate_against_schema(
                yaml.safe_load(path.read_text()), "config.schema.json", str(path)) == [], path
