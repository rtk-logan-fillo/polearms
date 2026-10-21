import json
import subprocess
import sys

import pytest
import yaml

from scripts.common import ROOT
from scripts.compile import status as ss

DEFINITION = {"ocsf": {"version": "1.8.0"}, "arcticwolf_extension": {"version": "0.0.1"}}


def schema(ocsf="1.8.0", arcticwolf="0.0.1"):
    return {"version": ocsf, "extensions": {"linux": {"version": "1.8.0"}, "arcticwolf": {"version": arcticwolf}}}


class TestStaleReasons:
    def test_a_current_schema_has_no_reasons(self):
        assert ss.stale_reasons(schema(), DEFINITION) == []

    def test_a_different_extension_version(self):
        (reason,) = ss.stale_reasons(schema(arcticwolf="1.0.0"), DEFINITION)
        assert "arcticwolf" in reason and "'1.0.0'" in reason and "'0.0.1'" in reason

    def test_a_different_ocsf_version(self):
        (reason,) = ss.stale_reasons(schema(ocsf="1.7.0"), DEFINITION)
        assert "ocsf" in reason and "'1.7.0'" in reason and "'1.8.0'" in reason

    def test_both_differing_are_both_reported(self):
        assert len(ss.stale_reasons(schema("1.7.0", "9.9.9"), DEFINITION)) == 2

    def test_only_the_arcticwolf_extension_is_compared_not_the_platform_ones(self):
        s = schema()
        s["extensions"]["win"] = {"version": "0.0.0"}       # unrelated extension, any version
        assert ss.stale_reasons(s, DEFINITION) == []

    @pytest.mark.parametrize("compiled", [{}, {"version": "1.8.0"}, {"version": "1.8.0", "extensions": {}},
                                          {"version": "1.8.0", "extensions": {"arcticwolf": {}}},
                                          {"version": "1.8.0", "extensions": None}])
    def test_a_schema_that_does_not_record_the_extension_is_stale(self, compiled):
        assert ss.stale_reasons(compiled, DEFINITION)

    def test_an_empty_schema_is_stale_on_both_counts(self):
        assert len(ss.stale_reasons({}, DEFINITION)) == 2

    def test_versions_are_compared_as_text(self):
        # "1.10.0" is not "1.1.0", and a trailing-zero lookalike is not a match.
        assert ss.stale_reasons(schema(arcticwolf="0.0.10"), DEFINITION)
        assert ss.stale_reasons(schema(arcticwolf="0.0.1.0"), DEFINITION)

    def test_yaml_numbers_in_the_definition_are_compared_as_their_text(self):
        # an unquoted 1.8 parses as the float 1.8, which is not the version "1.8.0"
        defn = {"ocsf": {"version": 1.8}, "arcticwolf_extension": {"version": "0.0.1"}}
        assert ss.stale_reasons(schema(), defn)

    @pytest.mark.parametrize("definition,name", [
        ({"arcticwolf_extension": {"version": "0.0.1"}}, "ocsf"),
        ({"ocsf": {"version": "1.8.0"}}, "arcticwolf"),
        ({}, "ocsf"),
    ])
    def test_a_definition_that_names_no_version_is_reported_not_crashed_on(self, definition, name):
        assert any(f"does not name a {name} version" in r for r in ss.stale_reasons(schema(), definition))


class TestMain:
    @pytest.fixture
    def files(self, tmp_path, monkeypatch):
        schema_path, definition_path = tmp_path / "schema.json", tmp_path / "def.yaml"
        schema_path.write_text(json.dumps(schema()))
        definition_path.write_text(yaml.safe_dump(DEFINITION))
        monkeypatch.setattr(ss, "SCHEMA_PATH", schema_path)
        monkeypatch.setattr(ss, "SCHEMA_DEFINITION_PATH", definition_path)
        monkeypatch.setattr(sys, "argv", ["status.py"])
        return schema_path, definition_path

    def run(self, capsys):
        ss.main()
        captured = capsys.readouterr()
        return captured.out, captured.err

    def test_current_schema_prints_false(self, files, capsys):
        out, err = self.run(capsys)
        assert out == "needs_compile=false\n"
        assert "already matches" in err

    def test_stale_schema_prints_true_and_says_why(self, files, capsys):
        files[1].write_text(yaml.safe_dump({**DEFINITION, "arcticwolf_extension": {"version": "0.0.2"}}))
        out, err = self.run(capsys)
        assert out == "needs_compile=true\n"
        assert "out of date: arcticwolf" in err

    def test_only_the_decision_goes_to_stdout_so_it_can_be_appended_to_github_output(self, files, capsys):
        files[1].write_text(yaml.safe_dump({"ocsf": {"version": "9.9.9"}, "arcticwolf_extension": {"version": "9.9.9"}}))
        out, _ = self.run(capsys)
        assert out.splitlines() == ["needs_compile=true"]

    def test_a_missing_schema_needs_compiling(self, files, capsys):
        files[0].unlink()
        out, _ = self.run(capsys)
        assert out == "needs_compile=true\n"

    @pytest.mark.parametrize("text", ["", "{", "not json at all"])
    def test_a_corrupt_schema_needs_compiling(self, files, capsys, text):
        files[0].write_text(text)
        out, err = self.run(capsys)
        assert out == "needs_compile=true\n" and "not valid JSON" in err


class TestRealRepository:
    def test_it_runs_on_the_checked_in_files_and_prints_a_decision(self):
        result = subprocess.run([sys.executable, "-m", "scripts.compile.status"],
                                cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() in ("needs_compile=true", "needs_compile=false")
