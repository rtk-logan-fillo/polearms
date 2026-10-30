import subprocess
import sys

import pytest
import yaml

from scripts.common import ROOT
from scripts import validate_config as vc


def only(issues):
    assert len(issues) == 1, issues
    return issues[0]


def validate(mini_schema, **raw):
    return vc.validate_config({"class_name": "widget", "class_uid": 1, **raw}, mini_schema)


class TestClassIdentity:
    def test_valid(self, mini_schema):
        assert validate(mini_schema) == []

    def test_valid_for_a_second_class(self, mini_schema):
        assert vc.validate_config({"class_name": "gadget", "class_uid": 2}, mini_schema) == []

    def test_unknown_class_name(self, mini_schema):
        issue = only(vc.validate_config({"class_name": "widgit", "class_uid": 1}, mini_schema))
        assert (issue.step, issue.severity) == ("valid-class-name", "error")
        assert "'widgit'" in issue.message

    def test_uid_that_does_not_match_the_class(self, mini_schema):
        issue = only(validate(mini_schema, class_uid=2))   # 2 is gadget's uid, not widget's
        assert issue.step == "valid-class-uid"
        assert "class_uid 2" in issue.message and "uid 1" in issue.message

    def test_uid_and_name_swapped_between_classes(self, mini_schema):
        assert only(vc.validate_config({"class_name": "gadget", "class_uid": 1}, mini_schema)).step == "valid-class-uid"

    def test_missing_class_name(self, mini_schema):
        issue = only(vc.validate_config({"class_uid": 1}, mini_schema, target="x/config.yaml"))
        assert (issue.step, issue.target) == ("json-schema", "x/config.yaml")
        assert issue.message == "'class_name' is required"

    @pytest.mark.parametrize("name", ["", None, 5, ["widget"]])
    def test_invalid_class_name_values(self, mini_schema, name):
        issues = vc.validate_config({"class_name": name, "class_uid": 1}, mini_schema)
        assert [i.step for i in issues] == ["json-schema"]
        assert all(i.target.endswith("class_name") for i in issues)

    def test_missing_class_uid(self, mini_schema):
        issue = only(vc.validate_config({"class_name": "widget"}, mini_schema))
        assert (issue.step, issue.message) == ("json-schema", "'class_uid' is required")

    @pytest.mark.parametrize("uid", ["1", 1.0, True, [1], None, -1])
    def test_invalid_class_uid(self, mini_schema, uid):
        issue = only(validate(mini_schema, class_uid=uid))
        assert issue.step == "json-schema" and issue.target.endswith("class_uid")

    def test_unknown_keys_are_rejected(self, mini_schema):
        issue = only(validate(mini_schema, versoin="1.0.0"))
        assert (issue.step, issue.message) == ("json-schema", "unknown key(s) 'versoin'")

    def test_uid_zero_is_a_real_uid_not_missing(self, mini_schema):
        mini_schema.classes["base"] = {"uid": 0, "attributes": {}}
        assert vc.validate_config({"class_name": "base", "class_uid": 0}, mini_schema) == []

    def test_empty_config(self, mini_schema):
        issues = vc.validate_config({}, mini_schema)
        assert {i.step for i in issues} == {"json-schema"}
        assert {i.message for i in issues} == {"'class_name' is required", "'class_uid' is required"}

    @pytest.mark.parametrize("document", [None, [], "text", 5])
    def test_a_config_that_is_not_a_mapping(self, mini_schema, document):
        assert {i.step for i in vc.validate_config(document, mini_schema)} == {"json-schema"}

    def test_structural_errors_stop_the_semantic_checks(self, mini_schema):
        # class_uid is wrong for the class AND the type is wrong: only the structural error shows.
        issues = vc.validate_config({"class_name": "widget", "class_uid": "99"}, mini_schema)
        assert [i.step for i in issues] == ["json-schema"]

    def test_the_target_is_the_class_name_for_semantic_errors(self, mini_schema):
        assert only(validate(mini_schema, class_uid=2)).target == "widget"

    def test_a_wrong_name_does_not_also_report_the_uid(self, mini_schema):
        issues = vc.validate_config({"class_name": "nope", "class_uid": 99}, mini_schema)
        assert [i.step for i in issues] == ["valid-class-name"]


class TestEssentialFields:
    def test_all_present(self, mini_schema):
        fields = [{"polearms": "name"}, {"polearms": "owner.email"}, {"polearms": "owner.address.city"}]
        assert validate(mini_schema, essential_fields=fields) == []

    def test_empty_list_and_missing_key_are_fine(self, mini_schema):
        assert validate(mini_schema, essential_fields=[]) == []
        assert vc.validate_config({"class_name": "widget", "class_uid": 1}, mini_schema) == []

    def test_a_bare_essential_fields_key_is_rejected(self, mini_schema):
        # `essential_fields:` with nothing after it parses as None, which is not a list.
        issue = only(validate(mini_schema, essential_fields=None))
        assert issue.step == "json-schema" and issue.target.endswith("essential_fields")

    def test_field_not_in_the_class(self, mini_schema):
        issue = only(validate(mini_schema, essential_fields=[{"polearms": "nope"}]))
        assert issue.step == "valid-essential-field"
        assert "'nope'" in issue.message and "class widget" in issue.message

    def test_field_that_belongs_to_a_different_class(self, mini_schema):
        assert only(validate(mini_schema, essential_fields=[{"polearms": "serial"}])).step == "valid-essential-field"

    def test_every_bad_field_is_reported_and_good_ones_are_not(self, mini_schema):
        fields = [{"polearms": "bad1"}, {"polearms": "name"}, {"polearms": "owner.nope"}]
        issues = validate(mini_schema, essential_fields=fields)
        assert [i.message.split("'")[1] for i in issues] == ["bad1", "owner.nope"]

    def test_bracket_notation_resolves_like_the_mappings_do(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        assert validate(mini_schema, essential_fields=[{"polearms": "owner[].email"}]) == []

    def test_the_message_says_how_to_write_the_array(self, mini_schema):
        mini_schema.objects["person"]["attributes"]["address"]["is_array"] = True
        issue = only(validate(mini_schema, essential_fields=[{"polearms": "owner.address.city"}]))
        assert issue.step == "essential-field-arrays"
        assert "'owner.address.city' must be written 'owner.address[].city'" in issue.message

    def test_an_array_in_the_middle_of_the_path_needs_brackets(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        assert only(validate(mini_schema, essential_fields=[{"polearms": "owner.email"}])).step == "essential-field-arrays"
        assert validate(mini_schema, essential_fields=[{"polearms": "owner[].email"}]) == []

    def test_every_array_along_the_path_needs_brackets(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        mini_schema.objects["person"]["attributes"]["address"]["is_array"] = True
        issue = only(validate(mini_schema, essential_fields=[{"polearms": "owner[].address.city"}]))
        assert "must be written 'owner[].address[].city'" in issue.message
        assert validate(mini_schema, essential_fields=[{"polearms": "owner[].address[].city"}]) == []

    def test_brackets_on_something_that_is_not_an_array_are_rejected(self, mini_schema):
        issue = only(validate(mini_schema, essential_fields=[{"polearms": "owner[].email"}]))
        assert issue.step == "essential-field-arrays"
        assert "must be written 'owner.email'" in issue.message

    def test_a_final_array_of_primitives_may_be_written_either_way(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["tags"]["is_array"] = True
        assert validate(mini_schema, essential_fields=[{"polearms": "tags"}]) == []
        assert validate(mini_schema, essential_fields=[{"polearms": "tags[]"}]) == []

    def test_a_final_non_array_may_not_have_brackets(self, mini_schema):
        assert only(validate(mini_schema, essential_fields=[{"polearms": "name[]"}])).step == "essential-field-arrays"

    def test_a_missing_field_is_not_also_reported_for_its_brackets(self, mini_schema):
        assert [i.step for i in validate(mini_schema, essential_fields=[{"polearms": "nope.x"}])] == ["valid-essential-field"]

    def test_a_labelled_bracket_is_not_the_empty_form(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        assert only(validate(mini_schema, essential_fields=[{"polearms": "owner[x].email"}])).step == "essential-field-arrays"

    def test_expected_flag_is_allowed(self, mini_schema):
        assert validate(mini_schema, essential_fields=[{"polearms": "name", "expected": True}]) == []

    @pytest.mark.parametrize("entry", [{}, {"polearms": ""}, {"polearms": None}, {"expected": True}, "name", 5])
    def test_entries_without_a_usable_path(self, mini_schema, entry):
        issues = validate(mini_schema, essential_fields=[entry])
        assert issues and {i.step for i in issues} == {"json-schema"}
        assert all("essential_fields[0]" in i.target for i in issues)

    def test_unknown_keys_in_an_essential_field_are_rejected(self, mini_schema):
        issue = only(validate(mini_schema, essential_fields=[{"polearms": "name", "requried": True}]))
        assert (issue.step, issue.message) == ("json-schema", "unknown key(s) 'requried'")

    def test_essential_fields_must_be_a_list(self, mini_schema):
        issue = only(validate(mini_schema, essential_fields={"polearms": "name"}))
        assert issue.step == "json-schema" and "is not of type 'array'" in issue.message

    def test_override_mappings_are_checked_against_the_mapping_schema(self, mini_schema):
        issue = only(validate(mini_schema, override_mappings=[{"polearms": "name"}]))
        assert issue.step == "json-schema" and issue.message == "'swords' is required"
        assert "override_mappings[0]" in issue.target

    def test_fields_are_not_checked_when_the_class_is_unknown(self, mini_schema):
        issues = vc.validate_config({"class_name": "nope", "class_uid": 1,
                                     "essential_fields": [{"polearms": "anything"}]}, mini_schema)
        assert [i.step for i in issues] == ["valid-class-name"]

    def test_extension_style_class_names_work(self, mini_schema):
        mini_schema.classes["ext/thing"] = {"uid": 7, "attributes": {"x": {"caption": "X"}}}
        raw = {"class_name": "ext/thing", "class_uid": 7, "essential_fields": [{"polearms": "x"}]}
        assert vc.validate_config(raw, mini_schema) == []


class TestLoadRawConfig:
    def test_loads(self, tmp_path):
        path = tmp_path / "c.yaml"
        path.write_text("class_name: widget\n")
        assert vc.load_raw_config(path) == {"class_name": "widget"}

    @pytest.mark.parametrize("text,expected", [("", None), ("- a\n- b\n", ["a", "b"]), ("just a string\n", "just a string")])
    def test_non_mapping_files_are_returned_as_is_for_the_json_schema_to_reject(self, tmp_path, text, expected):
        path = tmp_path / "c.yaml"
        path.write_text(text)
        assert vc.load_raw_config(path) == expected


class TestMain:
    @pytest.fixture
    def project(self, fake_project, monkeypatch):
        monkeypatch.setattr(vc, "SCHEMA_PATH", fake_project.schema)
        monkeypatch.setattr(vc, "CONFIG_DIR", fake_project.config_dir)
        monkeypatch.setattr(sys, "argv", ["config.py"])
        return fake_project

    def write(self, project, **raw):
        project.widget_config.write_text(yaml.safe_dump({"class_name": "widget", "class_uid": 1, **raw}))

    def test_passes(self, project, capsys):
        vc.main()
        assert capsys.readouterr().out == "widget config: ok\n"

    def test_exits_1_on_any_error(self, project, capsys):
        self.write(project, class_uid=5)
        with pytest.raises(SystemExit) as exc:
            vc.main()
        assert exc.value.code == 1
        assert "[valid-class-uid]" in capsys.readouterr().out

    def test_every_config_is_checked_and_all_are_reported(self, project, capsys):
        other = project.config_dir / "gadget"
        other.mkdir()
        (other / "config.yaml").write_text("class_name: gadget\nclass_uid: 99\n")
        with pytest.raises(SystemExit):
            vc.main()
        out = capsys.readouterr().out
        assert "widget config: ok" in out and "gadget config: 1 error(s)" in out

    def test_a_config_with_no_name_is_titled_by_its_directory(self, project, capsys):
        project.widget_config.write_text("class_uid: 1\n")
        with pytest.raises(SystemExit):
            vc.main()
        assert "widget config: 1 error(s)" in capsys.readouterr().out


class TestRealRepository:
    def test_every_checked_in_config_is_valid(self):
        result = subprocess.run([sys.executable, "-m", "scripts.validate_config"], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ERROR" not in result.stdout
        assert result.stdout.count(" config: ok") == 5
