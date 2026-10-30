import subprocess
import sys

import pytest
import yaml

from scripts.common import ROOT
from scripts import validate_schema_definition as sd

DEFINITION = {"ocsf": {"version": "1.8.0"}, "arcticwolf_extension": {"version": "0.0.0"}}


class TestValidateSchemaDefinition:
    def test_a_well_formed_definition_passes(self):
        assert sd.validate_schema_definition(DEFINITION) == []

    @pytest.mark.parametrize("definition,fragment", [
        ({"ocsf": {"version": "1.8.0"}}, "'arcticwolf_extension' is required"),
        ({"arcticwolf_extension": {"version": "0.0.0"}}, "'ocsf' is required"),
        ({**DEFINITION, "extra": 1}, "unknown key(s) 'extra'"),
        ({**DEFINITION, "ocsf": {}}, "'version' is required"),
        ({**DEFINITION, "ocsf": {"version": "1.8.0", "build": 1}}, "unknown key(s) 'build'"),
        ({**DEFINITION, "ocsf": {"version": "1.8"}}, "expected a semantic version"),
        ({**DEFINITION, "ocsf": {"version": "v1.8.0"}}, "expected a semantic version"),
        ({**DEFINITION, "ocsf": {"version": 1.8}}, "is not of type 'string'"),
        ({**DEFINITION, "arcticwolf_extension": {"version": 1}}, "is not of type 'string'"),
        ({**DEFINITION, "ocsf": "1.8.0"}, "is not of type 'object'"),
    ])
    def test_a_malformed_definition_is_a_json_schema_error(self, definition, fragment):
        issues = sd.validate_schema_definition(definition)
        assert issues and {i.step for i in issues} == {"json-schema"}
        assert any(fragment in i.message for i in issues), [i.message for i in issues]

    @pytest.mark.parametrize("document", [None, [], "text", 5])
    def test_a_document_that_is_not_a_mapping_is_rejected(self, document):
        assert sd.validate_schema_definition(document)

    def test_the_target_names_the_file_and_the_location(self):
        (issue,) = sd.validate_schema_definition({**DEFINITION, "ocsf": {"version": "1.8"}}, "def.yaml")
        assert issue.target == "def.yaml:ocsf.version"

    @pytest.mark.parametrize("ocsf,extension", [
        ("1.8.0", "0.0.0"), ("9.9.9", "9.9.9"), ("1.8.0-rc.1", "2.0.0+build.5"), ("0.0.1", "10.20.30"),
    ])
    def test_the_values_are_not_compared_with_anything(self, ocsf, extension):
        definition = {"ocsf": {"version": ocsf}, "arcticwolf_extension": {"version": extension}}
        assert sd.validate_schema_definition(definition) == []


class TestMain:
    @pytest.fixture
    def definition_file(self, tmp_path, monkeypatch):
        path = tmp_path / "def.yaml"
        path.write_text(yaml.safe_dump(DEFINITION))
        monkeypatch.setattr(sd, "SCHEMA_DEFINITION_PATH", path)
        monkeypatch.setattr(sys, "argv", ["schema_definition.py"])
        return path

    def test_passes(self, definition_file, capsys):
        sd.main()
        assert capsys.readouterr().out == "schema definition: ok\n"

    def test_exits_1_on_a_malformed_definition(self, definition_file, capsys):
        definition_file.write_text(yaml.safe_dump({**DEFINITION, "ocsf": {"version": "1.8"}}))
        with pytest.raises(SystemExit) as exc:
            sd.main()
        assert exc.value.code == 1
        assert "[json-schema] def.yaml:ocsf.version" in capsys.readouterr().out

    def test_an_empty_file_is_rejected(self, definition_file, capsys):
        definition_file.write_text("")
        with pytest.raises(SystemExit) as exc:
            sd.main()
        assert exc.value.code == 1

    def test_a_mismatch_with_schema_json_is_not_this_validators_concern(self, definition_file, tmp_path, capsys):
        # No schema.json is even read: a definition naming versions that don't match it still passes.
        definition_file.write_text(yaml.safe_dump(
            {"ocsf": {"version": "0.0.1"}, "arcticwolf_extension": {"version": "0.0.1"}}))
        sd.main()
        assert capsys.readouterr().out == "schema definition: ok\n"


class TestRealRepository:
    def test_the_checked_in_definition_is_well_formed(self):
        result = subprocess.run([sys.executable, "-m", "scripts.validate_schema_definition"],
                                cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout == "schema definition: ok\n"
