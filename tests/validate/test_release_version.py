import subprocess
import sys

import pytest
import yaml

from scripts.common import ROOT
from scripts.validate import release_version as rv


def definition(extension="1.2.0"):
    return {"ocsf": {"version": "1.8.0"}, "arcticwolf_extension": {"version": extension}}


def only(issues):
    assert len(issues) == 1, issues
    return issues[0]


class TestMajorMinor:
    @pytest.mark.parametrize("version,expected", [
        ("1.2.3", (1, 2)), ("0.0.0", (0, 0)), ("10.20.30", (10, 20)),
        ("1.2.3-rc.1", (1, 2)), ("1.2.3+build.5", (1, 2)), ("1.2.3-rc.1+b", (1, 2)),
    ])
    def test_semantic_versions(self, version, expected):
        assert rv.major_minor(version) == expected

    @pytest.mark.parametrize("version", ["", "1", "1.2", "v1.2.3", "a.b.c", "1.2.x", " 1.2.3"])
    def test_non_semantic_versions(self, version):
        assert rv.major_minor(version) is None

    def test_compares_numbers_not_text(self):
        assert rv.major_minor("1.10.0") != rv.major_minor("1.1.0")


class TestValidateReleaseVersion:
    def test_matching_major_and_minor_pass(self):
        assert rv.validate_release_version("1.2.0", definition("1.2.0")) == []

    def test_the_patch_may_differ_either_way(self):
        assert rv.validate_release_version("1.2.7", definition("1.2.0")) == []
        assert rv.validate_release_version("1.2.0", definition("1.2.9")) == []

    def test_a_pre_release_suffix_is_ignored(self):
        assert rv.validate_release_version("1.2.3-rc.1", definition("1.2.0")) == []
        assert rv.validate_release_version("1.2.3+build", definition("1.2.0")) == []

    def test_a_minor_mismatch_fails(self):
        issue = only(rv.validate_release_version("1.3.0", definition("1.2.0")))
        assert (issue.step, issue.severity, issue.target) == ("release-version", "error", "VERSION")
        assert "1.3" in issue.message and "1.2" in issue.message and "must match" in issue.message

    def test_a_major_mismatch_fails(self):
        assert only(rv.validate_release_version("2.2.0", definition("1.2.0"))).step == "release-version"

    def test_minor_ten_is_not_minor_one(self):
        assert rv.validate_release_version("1.10.0", definition("1.1.0"))

    def test_the_message_names_both_full_versions(self):
        message = only(rv.validate_release_version("1.3.4", definition("1.2.9"))).message
        assert "'1.3.4'" in message and "'1.2.9'" in message

    def test_a_release_version_that_is_not_semver(self):
        issue = only(rv.validate_release_version("1.2", definition("1.2.0")))
        assert "not a semantic version" in issue.message and "'1.2'" in issue.message

    def test_an_extension_version_that_is_not_semver(self):
        issue = only(rv.validate_release_version("1.2.0", definition("1.2")))
        assert "arcticwolf_extension.version '1.2' is not a semantic version" in issue.message

    @pytest.mark.parametrize("defn", [{}, {"arcticwolf_extension": None}, {"arcticwolf_extension": {}},
                                      {"ocsf": {"version": "1.8.0"}}])
    def test_a_missing_extension_version(self, defn):
        issue = only(rv.validate_release_version("1.2.0", defn))
        assert "arcticwolf_extension.version is not set" in issue.message

    def test_a_yaml_number_for_the_extension_version_is_not_semver(self):
        # An unquoted 1.2 in the YAML is a float, not "1.2.0".
        assert "not a semantic version" in only(rv.validate_release_version("1.2.0", definition(1.2))).message


class TestMain:
    @pytest.fixture
    def paths(self, tmp_path, monkeypatch):
        version, defn = tmp_path / "VERSION", tmp_path / "def.yaml"
        version.write_text("1.2.5\n")
        defn.write_text(yaml.safe_dump(definition("1.2.0")))
        monkeypatch.setattr(rv, "VERSION_PATH", version)
        monkeypatch.setattr(rv, "SCHEMA_DEFINITION_PATH", defn)
        monkeypatch.setattr(sys, "argv", ["release_version.py"])
        return version, defn

    def test_passes(self, paths, capsys):
        rv.main()
        assert capsys.readouterr().out == "release version: ok\n"

    def test_exits_1_on_a_mismatch(self, paths, capsys):
        paths[0].write_text("1.3.0\n")
        with pytest.raises(SystemExit) as exc:
            rv.main()
        assert exc.value.code == 1
        assert "[release-version]" in capsys.readouterr().out

    def test_bumping_the_extension_requires_bumping_the_release(self, paths):
        paths[1].write_text(yaml.safe_dump(definition("2.0.0")))
        with pytest.raises(SystemExit):
            rv.main()

    def test_an_empty_version_file_exits(self, paths):
        paths[0].write_text("")
        with pytest.raises(SystemExit):
            rv.main()


class TestRealRepository:
    def test_the_checked_in_version_tracks_the_extension(self):
        result = subprocess.run([sys.executable, "-m", "scripts.validate.release_version"],
                                cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert result.stdout == "release version: ok\n"
