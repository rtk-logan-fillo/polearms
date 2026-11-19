import json
import sys

import pytest
import yaml

from scripts.common import ClassConfig, Mapping
from scripts import validate_mappings as vm

FNS = {"map_x", "map_y"}
SWORDS_SCHEMA = {
    name: {"datatype": "string", "is_list": False}
    for name in ("s", "t.z", "dup", "widget-name", "owner-email", "brand-new", "elsewhere", "g")
}


def steps(issues):
    """The distinct (step, severity) pairs in a list of validator issues."""
    return sorted({(i.step, i.severity) for i in issues})


def messages(m, fns=FNS):
    return [i.message for i in vm.validate_single_mapping(m, fns)]


# ---------------------------------------------------------------------------
# format
# ---------------------------------------------------------------------------


class TestLabelsAndMapperFunction:
    """The per-mapping checks a JSON Schema can't express: selectors and the mapper and selector functions."""

    def test_valid_labelled_mapper_mapping(self):
        m = Mapping(polearms="a[x].b", swords="s", selectors={"x": {"label": "k!=null"}}, mapper={"fn": "map_x"})
        assert messages(m) == []

    def test_a_plain_mapping_is_fine(self):
        assert messages(Mapping(polearms="name", swords="s")) == []

    def test_bracket_key_missing_from_selectors(self):
        assert messages(Mapping(polearms="a[x].b", swords="s")) == [
            "path has [x] but selectors has no entry for it with a label"]

    def test_selector_with_an_empty_label(self):
        assert messages(Mapping(polearms="a[x].b", swords="s", selectors={"x": {"label": ""}})) == [
            "path has [x] but selectors has no entry for it with a label"]

    def test_unused_selector_key(self):
        assert messages(Mapping(polearms="a", swords="s", selectors={"y": {"label": "z"}})) == [
            "selector key 'y' has no corresponding [y] in any polearms or swords path"]

    def test_a_selector_function_that_exists_is_fine(self):
        m = Mapping(polearms="a[x].b", swords="s", selectors={"x": {"label": "k", "fn": "map_x"}})
        assert messages(m) == []

    def test_undefined_selector_function(self):
        m = Mapping(polearms="a[x].b", swords="s", selectors={"x": {"label": "k", "fn": "select_nope"}})
        assert messages(m) == ["selector function 'select_nope' for [x] not defined in mappers_and_selectors.py"]

    def test_selector_function_is_not_checked_when_no_functions_are_known(self):
        m = Mapping(polearms="a[x].b", swords="s", selectors={"x": {"label": "k", "fn": "anything"}})
        assert messages(m, fns=set()) == []

    def test_bare_brackets_need_no_label(self):
        assert messages(Mapping(polearms="a[].b", swords="s")) == []

    def test_label_may_be_used_in_the_swords_path(self):
        m = Mapping(polearms="a", swords="t[y].z", selectors={"y": {"label": "k"}}, mapper={"fn": "map_x"})
        assert messages(m) == []

    def test_undefined_mapper_function(self):
        m = Mapping(polearms="a", swords="s", mapper={"fn": "map_nope"})
        assert messages(m) == ["mapper function 'map_nope' not defined in mappers_and_selectors.py"]

    def test_mapper_function_is_not_checked_when_no_functions_are_known(self):
        assert messages(Mapping(polearms="a", swords="s", mapper={"fn": "anything"}), fns=set()) == []

    def test_each_problem_is_reported_under_its_own_step(self):
        m = Mapping(polearms="a[x]", swords="s", selectors={"q": {"label": "z"}}, mapper={"fn": "map_nope"})
        assert steps(vm.validate_single_mapping(m, FNS)) == [
            ("mapper-function", "error"), ("selectors", "error")]
        assert [i.message for i in vm.validate_single_mapping(m, FNS)] == [
            "path has [x] but selectors has no entry for it with a label",
            "selector key 'q' has no corresponding [q] in any polearms or swords path",
            "mapper function 'map_nope' not defined in mappers_and_selectors.py"]


def schema_issues(*mappings):
    """Run raw mapping dicts through the real mappings JSON Schema."""
    return vm.validate_against_schema({"mappings": list(mappings)}, "mappings.schema.json", "swords_mappings.yaml")


class TestJsonSchema:
    """The structural rules, which used to be the "format" step."""

    def test_valid_mappings_pass(self):
        assert schema_issues(
            {"polearms": "a", "swords": "s"},
            {"polearms": ["a", "b"], "swords": "s", "mapper": {"fn": "f"}},
            {"polearms": "a[x]", "swords": "t[].x", "selectors": {"x": {"label": "k"}}, "mapper": {"fn": "f", "args": {"a": "p"}}},
            {"polearms": "a[]", "swords": "s", "join": ","},
            {"polearms": "a[0]", "swords": "s"},
        ) == []

    def test_every_issue_is_a_json_schema_error(self):
        issues = schema_issues({"polearms": "", "swords": ""}, {"oops": 1})
        assert issues and steps(issues) == [("json-schema", "error")]

    @pytest.mark.parametrize("polearms", ["", [], ["a", ""], [""], 5, None])
    def test_invalid_polearms(self, polearms):
        issues = schema_issues({"polearms": polearms, "swords": "s", "mapper": {"fn": "f"}})
        assert issues and all("polearms" in i.target for i in issues)

    def test_missing_polearms_or_swords(self):
        assert any("'polearms' is required" in i.message for i in schema_issues({"swords": "s"}))
        assert any("'swords' is required" in i.message for i in schema_issues({"polearms": "a"}))

    def test_empty_swords(self):
        issues = schema_issues({"polearms": "a", "swords": ""})
        assert issues and issues[0].target.endswith(".swords")

    def test_unknown_mapping_key(self):
        assert any("unknown key(s) 'oops'" in i.message for i in schema_issues(
            {"polearms": "a", "swords": "s", "oops": 1}))

    def test_many_to_one_without_a_mapper_is_left_to_the_result_shape_step(self):
        assert schema_issues({"polearms": ["a[]", "b[]"], "swords": "s"}) == []

    def test_list_item_swords_does_not_require_a_mapper(self):
        assert schema_issues({"polearms": "a", "swords": "t[].x"}) == []

    def test_join_is_allowed_on_a_list_item_swords_path(self):
        assert schema_issues({"polearms": "a", "swords": "t[].x", "mapper": {"fn": "f"}, "join": ","}) == []

    def test_join_must_be_a_string(self):
        assert schema_issues({"polearms": "a[]", "swords": "s", "join": 1})

    def test_first_is_accepted_and_must_be_a_boolean(self):
        assert schema_issues({"polearms": "a[]", "swords": "s", "first": True}) == []
        assert schema_issues({"polearms": "a[]", "swords": "s", "first": "yes"})

    def test_join_is_no_longer_a_mapper_key(self):
        issues = schema_issues({"polearms": "a", "swords": "s", "mapper": {"fn": "f", "join": ","}})
        assert [i.message for i in issues] == ["unknown key(s) 'join'"]

    def test_mapper_needs_fn_and_rejects_unknown_keys(self):
        messages_ = [i.message for i in schema_issues(
            {"polearms": "a", "swords": "s", "mapper": {"fnn": "f"}})]
        assert "'fn' is required" in messages_ and "unknown key(s) 'fnn'" in messages_

    def test_mapper_args_and_selector_labels_must_be_strings(self):
        issues = schema_issues({"polearms": "a[x]", "swords": "s", "selectors": {"x": {"label": 5}},
                                "mapper": {"fn": "f", "args": {"a": 1}}})
        assert {i.target.split(":")[1] for i in issues} == {"mappings[0].selectors.x.label", "mappings[0].mapper.args.a"}

    def test_issues_say_which_mapping_they_are_in(self):
        issues = schema_issues({"polearms": "a", "swords": "s"}, {"polearms": "b"}, {"polearms": "c", "swords": "s"})
        assert [i.target for i in issues] == ["swords_mappings.yaml:mappings[1]"]

    def test_the_document_must_have_a_mappings_list(self):
        issues = vm.validate_against_schema({"mapping": []}, "mappings.schema.json", "swords_mappings.yaml")
        assert {i.message for i in issues} == {"'mappings' is required", "unknown key(s) 'mapping'"}

    def test_a_non_mapping_document_is_rejected(self):
        assert vm.validate_against_schema(["a"], "mappings.schema.json", "swords_mappings.yaml")


# ---------------------------------------------------------------------------
# uniqueness
# ---------------------------------------------------------------------------


class TestUniqueness:
    def test_distinct_mappings_are_fine(self):
        assert vm.validate_uniqueness([Mapping(polearms="a", swords="s1"), Mapping(polearms="b", swords="s2")]) == []

    def test_duplicate_polearms_base_path(self):
        issues = vm.validate_uniqueness([Mapping(polearms="a.b", swords="s1"), Mapping(polearms="a.b", swords="s2")])
        assert steps(issues) == [("unique-polearms-field", "error")]

    def test_duplicate_is_detected_through_different_labels(self):
        issues = vm.validate_uniqueness([
            Mapping(polearms="a[x].b", swords="s1", selectors={"x": {"label": "1"}}),
            Mapping(polearms="a[y].b", swords="s2", selectors={"y": {"label": "2"}})])
        assert steps(issues) == [("unique-polearms-field", "error")]

    def test_same_polearms_with_different_mappers_is_allowed(self):
        issues = vm.validate_uniqueness([
            Mapping(polearms="a.b", swords="s1"),
            Mapping(polearms="a.b", swords="s2", mapper={"fn": "map_x"}),
            Mapping(polearms="a.b", swords="s3", mapper={"fn": "map_y"})])
        assert issues == []

    def test_same_polearms_with_different_selectors_is_allowed(self):
        mappings = [
            Mapping(polearms="f[x].v", swords="s1", selectors={"x": {"label": "1", "fn": "select_a"}}),
            Mapping(polearms="f[x].v", swords="s2", selectors={"x": {"label": "2", "fn": "select_b"}}),
        ]
        assert vm.validate_uniqueness(mappings) == []

    def test_same_polearms_and_selectors_is_a_duplicate(self):
        mappings = [
            Mapping(polearms="f[x].v", swords="s1", selectors={"x": {"label": "1", "fn": "select_a"}}),
            Mapping(polearms="f[y].v", swords="s2", selectors={"y": {"label": "1", "fn": "select_a"}}),
        ]
        assert steps(vm.validate_uniqueness(mappings)) == [("unique-polearms-field", "error")]

    def test_same_polearms_and_mapper_is_a_duplicate(self):
        issues = vm.validate_uniqueness([
            Mapping(polearms="a.b", swords="s1", mapper={"fn": "map_x"}),
            Mapping(polearms="a.b", swords="s2", mapper={"fn": "map_x"})])
        assert steps(issues) == [("unique-polearms-field", "error")]

    def test_duplicate_swords_field(self):
        issues = vm.validate_uniqueness([Mapping(polearms="a", swords="s"), Mapping(polearms="b", swords="s")])
        assert steps(issues) == [("unique-swords-field", "error")]

    def test_empty_swords_are_not_counted_as_duplicates(self):
        issues = vm.validate_uniqueness([Mapping(polearms="a", swords=""), Mapping(polearms="b", swords="")])
        assert issues == []

    def test_duplicates_within_one_many_to_one_mapping(self):
        issues = vm.validate_uniqueness([Mapping(polearms=["a.b", "a.b"], swords="s", mapper={"fn": "map_x"})])
        assert steps(issues) == [("unique-polearms-field", "error")]

    def test_message_names_the_offending_path(self):
        issues = vm.validate_uniqueness([Mapping(polearms="a.b", swords="s1"), Mapping(polearms="a.b", swords="s2")])
        assert "'a.b'" in issues[0].message


# ---------------------------------------------------------------------------
# valid POLEARMS field
# ---------------------------------------------------------------------------


class TestValidPolearmsField:
    def test_valid_for_the_class(self, mini_schema):
        assert vm.validate_polearms_fields([Mapping(polearms="owner.email", swords="s")],
                                           mini_schema, "widget", "1") == []

    def test_invalid_for_the_class(self, mini_schema):
        issues = vm.validate_polearms_fields([Mapping(polearms="serial", swords="s")],
                                             mini_schema, "widget", "1.0")
        assert steps(issues) == [("valid-polearms-field", "error")]
        assert "'serial' is not a valid POLEARMS field for widget in version 1.0" in issues[0].message

    def test_with_no_class_any_class_will_do(self, mini_schema):
        mappings = [Mapping(polearms="name", swords="s1"), Mapping(polearms="serial", swords="s2")]
        assert vm.validate_polearms_fields(mappings, mini_schema, None, "1") == []

    def test_with_no_class_a_field_in_no_class_is_invalid(self, mini_schema):
        issues = vm.validate_polearms_fields([Mapping(polearms="bogus", swords="s")], mini_schema, None, "1")
        assert steps(issues) == [("valid-polearms-field", "error")]
        assert "for any class" in issues[0].message

    def test_bracket_segments_are_ignored(self, mini_schema):
        assert vm.validate_polearms_fields([Mapping(polearms="owner[x].email", swords="s", selectors={"x": {"label": "k"}})],
                                           mini_schema, "widget", "1") == []

    def test_every_polearms_path_of_a_many_to_one_is_checked(self, mini_schema):
        issues = vm.validate_polearms_fields(
            [Mapping(polearms=["name", "bogus1", "bogus2"], swords="s", mapper={"fn": "map_x"})],
            mini_schema, "widget", "1")
        assert len(issues) == 2


# ---------------------------------------------------------------------------
# primitive POLEARMS field
# ---------------------------------------------------------------------------


class TestPrimitivePolearmsField:
    def test_a_primitive_field_is_fine(self, mini_schema):
        assert vm.validate_primitive_polearms_fields(
            [Mapping(polearms="owner.email", swords="s")], mini_schema, "widget") == []

    def test_an_object_field_is_an_error(self, mini_schema):
        issues = vm.validate_primitive_polearms_fields(
            [Mapping(polearms="owner", swords="s")], mini_schema, "widget")
        assert steps(issues) == [("primitive-polearms-field", "error")]
        assert "'owner' is an object" in issues[0].message

    def test_a_nested_object_field_is_an_error(self, mini_schema):
        issues = vm.validate_primitive_polearms_fields(
            [Mapping(polearms="owner.address", swords="s")], mini_schema, "widget")
        assert len(issues) == 1

    def test_an_array_of_objects_is_an_error(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        assert len(vm.validate_primitive_polearms_fields(
            [Mapping(polearms="owner", swords="s")], mini_schema, "widget")) == 1

    def test_an_array_of_primitives_is_fine(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["tags"]["is_array"] = True
        assert vm.validate_primitive_polearms_fields(
            [Mapping(polearms="tags", swords="s")], mini_schema, "widget") == []

    def test_bracket_segments_are_ignored(self, mini_schema):
        m = Mapping(polearms="owner[x]", swords="s", selectors={"x": {"label": "k"}})
        assert len(vm.validate_primitive_polearms_fields([m], mini_schema, "widget")) == 1

    def test_a_missing_field_is_left_to_valid_polearms_field(self, mini_schema):
        assert vm.validate_primitive_polearms_fields(
            [Mapping(polearms="bogus", swords="s")], mini_schema, "widget") == []

    def test_every_polearms_path_of_a_many_to_one_is_checked(self, mini_schema):
        m = Mapping(polearms=["name", "owner", "owner.address"], swords="s", mapper={"fn": "map_x"})
        assert len(vm.validate_primitive_polearms_fields([m], mini_schema, "widget")) == 2

    def test_with_no_class_an_object_in_any_class_is_an_error(self, mini_schema):
        mini_schema.classes["gadget"]["attributes"]["owner"] = {
            "caption": "Owner", "type": "string_t", "requirement": "optional"}
        assert len(vm.validate_primitive_polearms_fields(
            [Mapping(polearms="owner", swords="s")], mini_schema, None)) == 1

    def test_with_no_class_a_primitive_everywhere_is_fine(self, mini_schema):
        assert vm.validate_primitive_polearms_fields(
            [Mapping(polearms="name", swords="s")], mini_schema, None) == []


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestResultShape:
    SWORDS = {"scalar": {"is_list": False}, "listy": {"is_list": True}, "t.x": {"is_list": True}}

    def check(self, polearms, swords, join=None, mapper=None, first=False):
        m = Mapping(polearms=polearms, swords=swords, join=join, mapper=mapper, first=first)
        return vm.validate_result_shape([m], self.SWORDS)

    def test_first_takes_one_value_so_it_fits_a_scalar_field(self):
        assert self.check("a[].b", "scalar", first=True) == []

    def test_a_selector_bracket_gives_a_list_so_first_and_join_fit(self):
        sel = {"y": {"label": "k", "fn": "select_a"}}
        for kw in ({"first": True}, {"join": ", "}):
            m = Mapping(polearms="a[y].b", swords="scalar", selectors=sel, **kw)
            assert vm.validate_result_shape([m], self.SWORDS) == []

    def test_a_selector_bracket_into_a_scalar_field_needs_first_or_join(self):
        m = Mapping(polearms="a[y].b", swords="scalar", selectors={"y": {"label": "k", "fn": "select_a"}})
        issues = vm.validate_result_shape([m], self.SWORDS)
        assert steps(issues) == [("result-shape", "error")]

    def test_a_documentation_only_selector_gives_one_value(self):
        m = Mapping(polearms="a[y].b", swords="scalar", selectors={"y": {"label": "k"}})
        assert vm.validate_result_shape([m], self.SWORDS) == []

    LISTY = frozenset({"select_list"})

    def test_a_selector_that_returns_one_item_does_not_give_a_list(self):
        m = Mapping(polearms="a[y].b", swords="scalar", selectors={"y": {"label": "k", "fn": "select_one"}})
        assert vm.validate_result_shape([m], self.SWORDS, self.LISTY) == []
        m = Mapping(polearms="a[y].b", swords="scalar", join=",", selectors={"y": {"label": "k", "fn": "select_one"}})
        assert steps(vm.validate_result_shape([m], self.SWORDS, self.LISTY)) == [("result-shape", "error")]

    def test_a_selector_that_returns_a_list_gives_a_list(self):
        m = Mapping(polearms="a[y].b", swords="scalar", selectors={"y": {"label": "k", "fn": "select_list"}})
        assert steps(vm.validate_result_shape([m], self.SWORDS, self.LISTY)) == [("result-shape", "error")]
        m = Mapping(polearms="a[y].b", swords="listy", selectors={"y": {"label": "k", "fn": "select_list"}})
        assert vm.validate_result_shape([m], self.SWORDS, self.LISTY) == []

    def test_several_paths_without_a_mapper_must_each_give_a_list(self):
        sel = {"y": {"label": "k", "fn": "select_list"}}
        ok = Mapping(polearms=["a[y].b", "c[].d"], swords="listy", selectors=sel)
        assert vm.validate_result_shape([ok], self.SWORDS, self.LISTY) == []
        bad = Mapping(polearms=["a[y].b", "c[0].d"], swords="listy", selectors=sel)
        issues = vm.validate_result_shape([bad], self.SWORDS, self.LISTY)
        assert steps(issues) == [("result-shape", "error")]
        assert "'c[0].d' does not give a list" in issues[0].message

    def test_several_paths_with_a_mapper_are_not_checked(self):
        m = Mapping(polearms=["a", "b"], swords="scalar", mapper={"fn": "map_x"})
        assert vm.validate_result_shape([m], self.SWORDS, self.LISTY) == []

    def test_first_and_join_are_not_supported_on_several_paths_without_a_mapper(self):
        for kw in ({"first": True}, {"join": ", "}):
            m = Mapping(polearms=["a[]", "b[]"], swords="listy", **kw)
            assert any("not supported on a mapping with several" in i.message
                       for i in vm.validate_result_shape([m], self.SWORDS, self.LISTY))

    def test_first_needs_a_bare_bracket_path(self):
        for polearms in ("a.b", "a[0].b"):
            issues = self.check(polearms, "scalar", first=True)
            assert steps(issues) == [("result-shape", "error")]
            assert "first needs a POLEARMS path with []" in issues[0].message

    def test_first_and_join_cannot_be_combined(self):
        issues = self.check("a[].b", "scalar", join=",", first=True)
        assert [i.message for i in issues] == [
            "first and join cannot be combined: first gives one value and join needs a list"]

    def test_first_with_a_mapper_is_an_error(self):
        issues = self.check("a[x].b", "scalar", mapper={"fn": "map_x"}, first=True)
        assert steps(issues) == [("result-shape", "error")]

    def test_a_list_joined_into_a_scalar_field_is_fine(self):
        assert self.check("a[].b", "scalar", join=",") == []

    def test_a_list_into_a_list_field_is_fine(self):
        assert self.check("a[].b", "listy") == []

    def test_a_list_into_a_scalar_field_needs_a_join(self):
        issues = self.check("a[].b", "scalar")
        assert steps(issues) == [("result-shape", "error")]
        assert "add join" in issues[0].message

    def test_a_list_into_a_list_item_swords_path_is_fine(self):
        assert self.check("a[].b", "t[].x") == []

    def test_an_indexed_path_gives_one_value(self):
        assert self.check("a[0].b", "scalar") == []

    def test_join_needs_a_bare_bracket_path(self):
        for polearms in ("a.b", "a[0].b"):
            issues = self.check(polearms, "scalar", join=",")
            assert steps(issues) == [("result-shape", "error")]
            assert "needs a POLEARMS path with []" in issues[0].message

    def test_a_swords_field_missing_from_the_schema_is_left_to_valid_swords_field(self):
        assert self.check("a[].b", "nope") == []

    def test_mappings_with_a_mapper_are_not_checked(self):
        assert self.check("a[x].b", "scalar", mapper={"fn": "map_x"}) == []
        assert self.check("a", "scalar", join=",", mapper={"fn": "map_x"}) == []


# ---------------------------------------------------------------------------
# POLEARMS field arrays
# ---------------------------------------------------------------------------


class TestPolearmsFieldArrays:
    @pytest.fixture
    def schema(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        mini_schema.objects["person"]["attributes"]["address"]["is_array"] = True
        mini_schema.classes["widget"]["attributes"]["tags"]["is_array"] = True
        return mini_schema

    def check(self, schema, path, labels=None, class_name="widget"):
        m = Mapping(polearms=path, swords="s", selectors={k: {"label": v} for k, v in (labels or {}).items()}, mapper={"fn": "map_x"})
        return vm.validate_polearms_field_arrays([m], schema, class_name)

    def plain(self, schema, path, class_name="widget"):
        return vm.validate_polearms_field_arrays([Mapping(polearms=path, swords="s")], schema, class_name)

    def test_without_a_mapper_an_array_is_written_with_a_bare_bracket_or_an_index(self, schema):
        assert self.plain(schema, "owner[].email") == []
        assert self.plain(schema, "owner[0].email") == []
        assert self.plain(schema, "owner[2].address[].city") == []

    def test_a_labelled_bracket_without_a_selectors_entry_is_an_error(self, schema):
        issues = self.plain(schema, "owner[x].email")
        assert steps(issues) == [("polearms-field-arrays", "error")]
        assert "owner[]" in issues[0].message and "selectors entry" in issues[0].message

    def test_a_labelled_bracket_with_a_selectors_entry_is_fine(self, schema):
        m = Mapping(polearms="owner[x].email", swords="s", selectors={"x": {"label": "k", "fn": "select_a"}})
        assert vm.validate_polearms_field_arrays([m], schema, "widget") == []

    def test_without_a_mapper_a_missing_bracket_is_an_error(self, schema):
        issues = self.plain(schema, "owner.email")
        assert "'owner' is an array" in issues[0].message and "owner[N]" in issues[0].message

    def test_without_a_mapper_every_array_along_the_path_needs_a_bracket(self, schema):
        assert len(self.plain(schema, "owner[0].address.city")) == 1

    def test_without_a_mapper_a_bracket_on_a_non_array_is_an_error(self, schema):
        for path in ("name[]", "name[0]", "owner[].email[0]"):
            assert any("is not an array" in i.message for i in self.plain(schema, path))

    def test_with_a_mapper_a_bare_bracket_or_an_index_is_fine(self, schema):
        assert self.check(schema, "owner[0].email") == []
        assert self.check(schema, "owner[].email") == []
        assert self.check(schema, "owner[1].address[x].city", {"x": "k"}) == []

    def test_a_final_array_of_primitives_may_have_an_index_without_a_mapper(self, schema):
        assert self.plain(schema, "tags") == []
        assert self.plain(schema, "tags[]") == []
        assert self.plain(schema, "tags[1]") == []

    def test_a_labelled_bracket_on_an_array_is_fine(self, schema):
        assert self.check(schema, "owner[x].email", {"x": "k"}) == []

    def test_every_array_along_the_path_needs_one(self, schema):
        assert self.check(schema, "owner[x].address[y].city", {"x": "a", "y": "b"}) == []
        issues = self.check(schema, "owner[x].address.city", {"x": "a"})
        assert steps(issues) == [("polearms-field-arrays", "error")]
        assert "'address' is an array" in issues[0].message and "address[x]" in issues[0].message

    def test_a_missing_bracket_is_an_error(self, schema):
        issues = self.check(schema, "owner.email")
        assert steps(issues) == [("polearms-field-arrays", "error")]
        assert "'owner' is an array" in issues[0].message and "owner[x]" in issues[0].message

    def test_a_bracket_on_a_non_array_is_an_error(self, schema):
        issues = self.check(schema, "name[x]", {"x": "k"})
        assert steps(issues) == [("polearms-field-arrays", "error")]
        assert "'name' is not an array" in issues[0].message

    def test_a_bare_bracket_on_a_non_array_is_an_error(self, schema):
        assert len(self.check(schema, "owner[x].email[]", {"x": "k"})) == 1

    def test_a_final_array_of_primitives_may_have_a_bracket_or_not(self, schema):
        assert self.check(schema, "tags") == []
        assert self.check(schema, "tags[x]", {"x": "k"}) == []

    def test_a_missing_field_is_left_to_valid_polearms_field(self, schema):
        assert self.check(schema, "nope[x].y", {"x": "k"}) == []
        assert self.check(schema, "owner.nope") == []

    def test_every_polearms_path_of_a_many_to_one_is_checked(self, schema):
        m = Mapping(polearms=["name", "owner.email", "owner[x].address.city"], swords="s",
                    selectors={"x": {"label": "k"}}, mapper={"fn": "map_x"})
        assert len(vm.validate_polearms_field_arrays([m], schema, "widget")) == 2

    def test_with_no_class_the_path_is_checked_against_every_class_that_has_it(self, schema):
        assert len(self.check(schema, "owner.email", class_name=None)) == 1
        assert self.check(schema, "owner[x].email", {"x": "k"}, class_name=None) == []

    def test_with_no_class_the_same_problem_is_reported_once(self, schema):
        schema.classes["gadget"]["attributes"]["owner"] = schema.classes["widget"]["attributes"]["owner"]
        assert len(self.check(schema, "owner.email", class_name=None)) == 1

    def test_a_path_that_is_an_array_in_only_some_classes_is_checked_for_those(self, schema):
        schema.classes["gadget"]["attributes"]["name"] = {"caption": "N", "type": "string_t", "requirement": "optional"}
        schema.classes["gadget"]["attributes"]["owner"] = schema.classes["widget"]["attributes"]["owner"]
        assert len(self.check(schema, "owner.email", class_name=None)) == 1


# ---------------------------------------------------------------------------
# valid SWORDS field
# ---------------------------------------------------------------------------


class TestValidSwordsField:
    SCHEMA = {"a.b": {"datatype": "int", "is_list": False}, "list.item.x": {"datatype": None, "is_list": True}}

    def test_a_field_in_the_swords_schema_is_valid(self):
        assert vm.validate_swords_fields([Mapping(polearms="p", swords="a.b")], self.SCHEMA) == []

    def test_a_field_not_in_the_swords_schema_is_invalid(self):
        issues = vm.validate_swords_fields([Mapping(polearms="p", swords="a.nope")], self.SCHEMA)
        assert steps(issues) == [("valid-swords-field", "error")]
        assert issues[0].message == "'a.nope' is not a field in the SWORDS schema"
        assert issues[0].target == "p"

    def test_bracket_segments_are_ignored(self):
        m = Mapping(polearms="p", swords="list[k].item[].x", selectors={"k": {"label": "i==0"}})
        assert vm.validate_swords_fields([m], self.SCHEMA) == []

    def test_a_field_with_no_datatype_is_still_a_valid_field(self):
        assert vm.validate_swords_fields([Mapping(polearms="p", swords="list.item.x")], self.SCHEMA) == []

    def test_every_invalid_mapping_is_reported(self):
        mappings = [Mapping(polearms="p", swords="x"), Mapping(polearms="q", swords="a.b"),
                    Mapping(polearms="r", swords="y")]
        assert [i.target for i in vm.validate_swords_fields(mappings, self.SCHEMA)] == ["p", "r"]


# ---------------------------------------------------------------------------
# overrides
# ---------------------------------------------------------------------------


class TestOverrideRelevance:
    def test_valid_override(self, mini_schema):
        assert vm.validate_override_relevance([Mapping(polearms="name", swords="s")],
                                              mini_schema, "widget", "1") == []

    def test_override_of_a_field_the_class_lacks(self, mini_schema):
        issues = vm.validate_override_relevance([Mapping(polearms="serial", swords="s")],
                                                mini_schema, "widget", "1")
        assert steps(issues) == [("override-relevance", "error")]


GLOBALS = [
    Mapping(polearms="name", swords="widget-name"),
    Mapping(polearms="owner.email", swords="owner-email"),
]


class TestOverrideCompleteness:
    def test_override_of_an_unrelated_swords_field_is_fine(self, mini_schema):
        o = [Mapping(polearms="tags", swords="brand-new")]
        assert vm.validate_override_completeness(o, GLOBALS, mini_schema, "widget") == []

    def test_displacing_a_global_without_covering_its_polearms_field(self, mini_schema):
        o = [Mapping(polearms="tags", swords="widget-name")]      # displaces name -> widget-name
        issues = vm.validate_override_completeness(o, GLOBALS, mini_schema, "widget")
        assert steps(issues) == [("override-completeness", "error")]
        assert "'name'" in issues[0].message

    def test_covering_the_displaced_field_elsewhere_in_the_overrides(self, mini_schema):
        o = [Mapping(polearms="tags", swords="widget-name"), Mapping(polearms="name", swords="other")]
        assert vm.validate_override_completeness(o, GLOBALS, mini_schema, "widget") == []

    def test_displaced_fields_the_class_does_not_have_are_skipped(self, mini_schema):
        globals_ = [Mapping(polearms="serial", swords="s")]       # serial belongs to gadget, not widget
        o = [Mapping(polearms="name", swords="s")]
        assert vm.validate_override_completeness(o, globals_, mini_schema, "widget") == []

    def test_overriding_a_global_with_the_same_polearms_field_is_fine(self, mini_schema):
        o = [Mapping(polearms="name", swords="widget-name", mapper={"fn": "map_x"})]
        assert vm.validate_override_completeness(o, GLOBALS, mini_schema, "widget") == []


class TestOverrideShadowing:
    GLOBAL = [Mapping(polearms="owner[x].email", swords="owner-email", selectors={"x": {"label": "a"}}, mapper={"fn": "map_x"})]

    def labelled(self, swords, **kw):
        return Mapping(polearms="owner[y].email", swords=swords, selectors={"y": {"label": "b"}}, mapper={"fn": "map_x"}, **kw)

    def test_redirecting_a_global_to_a_new_swords_field_warns(self, mini_schema):
        issues = vm.validate_override_shadowing([self.labelled("elsewhere")], self.GLOBAL,
                                                mini_schema, "widget")
        assert steps(issues) == [("override-shadowing", "warning")]
        assert "'owner-email' won't be populated" in issues[0].message

    def test_keeping_the_same_destination_is_fine(self, mini_schema):
        assert vm.validate_override_shadowing([self.labelled("owner-email")], self.GLOBAL,
                                              mini_schema, "widget") == []

    def test_destination_repopulated_by_another_override_is_fine(self, mini_schema):
        o = [self.labelled("elsewhere"), Mapping(polearms="name", swords="owner-email")]
        assert vm.validate_override_shadowing(o, self.GLOBAL, mini_schema, "widget") == []

    def test_only_labelled_overrides_can_shadow(self, mini_schema):
        o = [Mapping(polearms="owner.email", swords="elsewhere", mapper={"fn": "map_x"})]
        assert vm.validate_override_shadowing(o, self.GLOBAL, mini_schema, "widget") == []

    def test_a_different_mapper_is_a_different_pair(self, mini_schema):
        o = [Mapping(polearms="owner[y].email", swords="elsewhere", selectors={"y": {"label": "b"}},
               mapper={"fn": "map_y"})]
        assert vm.validate_override_shadowing(o, self.GLOBAL, mini_schema, "widget") == []

    def test_fields_the_class_does_not_have_are_skipped(self, mini_schema):
        globals_ = [Mapping(polearms="bogus[x].f", swords="g", selectors={"x": {"label": "a"}}, mapper={"fn": "map_x"})]
        o = [Mapping(polearms="bogus[y].f", swords="elsewhere", selectors={"y": {"label": "b"}}, mapper={"fn": "map_x"})]
        assert vm.validate_override_shadowing(o, globals_, mini_schema, "widget") == []

    def test_it_is_a_warning_not_an_error(self, mini_schema):
        issues = vm.validate_override_shadowing([self.labelled("elsewhere")], self.GLOBAL,
                                                mini_schema, "widget")
        assert {i.severity for i in issues} == {vm.SEVERITY_WARNING}


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


class TestEntryPoints:
    def config(self, **kw):
        return ClassConfig(name="widget", essential_fields_only=False, essential_fields=[],
                           override_mappings=kw.get("overrides", []))

    def test_global_mappings_clean(self, mini_schema):
        assert vm.validate_global_mappings(GLOBALS, mini_schema, SWORDS_SCHEMA, FNS, "1") == []

    def test_global_mappings_report_issues_from_every_step(self, mini_schema):
        mappings = [
            Mapping(polearms="name", swords="dup"),
            Mapping(polearms="bogus", swords="dup"),                       # unique swords + invalid field
            Mapping(polearms="owner.email", swords="not-in-swords-schema"),
            Mapping(polearms="tags", swords="s", mapper={"fn": "map_nope"}),  # unknown mapper
        ]
        got = {s for s, _ in steps(vm.validate_global_mappings(mappings, mini_schema, SWORDS_SCHEMA, FNS, "1"))}
        assert got == {"unique-swords-field", "valid-polearms-field", "valid-swords-field", "mapper-function"}

    def test_class_without_overrides_has_nothing_to_validate(self, mini_schema):
        assert vm.validate_class_overrides(
            self.config(), GLOBALS, mini_schema, SWORDS_SCHEMA, FNS, "1") == []

    def test_class_overrides_run_every_override_step(self, mini_schema):
        overrides = [
            Mapping(polearms="serial", swords="widget-name"),      # invalid for widget; displaces a global
        ]
        got = {s for s, _ in steps(vm.validate_class_overrides(
            self.config(overrides=overrides), GLOBALS, mini_schema, SWORDS_SCHEMA, FNS, "1"))}
        assert {"valid-polearms-field", "override-relevance"} <= got

    def test_overrides_must_write_arrays_with_a_label(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        overrides = [Mapping(polearms="owner.email", swords="brand-new")]
        got = steps(vm.validate_class_overrides(
            self.config(overrides=overrides), GLOBALS, mini_schema, SWORDS_SCHEMA, FNS, "1"))
        assert ("polearms-field-arrays", "error") in got

    def test_global_mappings_must_write_arrays_with_a_label(self, mini_schema):
        mini_schema.classes["widget"]["attributes"]["owner"]["is_array"] = True
        got = steps(vm.validate_global_mappings(
            [Mapping(polearms="owner.email", swords="s")], mini_schema, SWORDS_SCHEMA, FNS, "1"))
        assert got == [("polearms-field-arrays", "error")]

    def test_overrides_must_map_primitive_fields(self, mini_schema):
        overrides = [Mapping(polearms="owner", swords="brand-new")]
        got = steps(vm.validate_class_overrides(
            self.config(overrides=overrides), GLOBALS, mini_schema, SWORDS_SCHEMA, FNS, "1"))
        assert ("primitive-polearms-field", "error") in got

    def test_global_mappings_must_map_primitive_fields(self, mini_schema):
        got = steps(vm.validate_global_mappings(
            [Mapping(polearms="owner", swords="s")], mini_schema, SWORDS_SCHEMA, FNS, "1"))
        assert got == [("primitive-polearms-field", "error")]

    def test_overrides_are_checked_against_the_swords_schema(self, mini_schema):
        overrides = [Mapping(polearms="tags", swords="not-in-swords-schema")]
        got = steps(vm.validate_class_overrides(
            self.config(overrides=overrides), GLOBALS, mini_schema, SWORDS_SCHEMA, FNS, "1"))
        assert got == [("valid-swords-field", "error")]

    def test_valid_overrides_are_clean(self, mini_schema):
        overrides = [Mapping(polearms="tags", swords="brand-new")]
        assert vm.validate_class_overrides(self.config(overrides=overrides), GLOBALS,
                                           mini_schema, SWORDS_SCHEMA, FNS, "1") == []

    def test_load_mapper_function_names_reads_top_level_defs_without_importing(self, tmp_path):
        path = tmp_path / "cm.py"
        path.write_text("raise RuntimeError('must not be imported')\n"
                        "def map_a(x):\n    return x\n"
                        "async def map_b(x):\n    return x\n"
                        "class K:\n    def map_hidden(self): ...\n")
        assert vm.load_mapper_function_names(path) == {"map_a", "map_b"}

    def test_report_formats_errors_and_warnings(self, capsys):
        vm.report("scope", [vm.error("t", "format", "bad"), vm.warning("t2", "override-shadowing", "hm")])
        out = capsys.readouterr().out
        assert "scope: 1 error(s), 1 warning(s)" in out
        assert "ERROR   [format] t: bad" in out
        assert "WARNING [override-shadowing] t2: hm" in out

    def test_report_ok(self, capsys):
        vm.report("scope", [])
        assert capsys.readouterr().out == "scope: ok\n"


# ---------------------------------------------------------------------------
# main(): run against a fake project
# ---------------------------------------------------------------------------


@pytest.fixture
def project(fake_project, monkeypatch):
    for name, path in {
        "SCHEMA_PATH": fake_project.schema, "SWORDS_MAPPINGS_PATH": fake_project.mappings,
        "VERSION_PATH": fake_project.version, "CONFIG_DIR": fake_project.config_dir,
        "MAPPERS_AND_SELECTORS_PATH": fake_project.mappers_and_selectors,
    }.items():
        monkeypatch.setattr(vm, name, path)
    monkeypatch.setattr(vm, "SWORDS_SCHEMA_PATH", fake_project.swords_schema)
    monkeypatch.setattr(sys, "argv", ["mappings.py"])
    return fake_project


class TestMain:
    def test_passes_on_valid_data(self, project, capsys):
        vm.main()
        out = capsys.readouterr().out
        assert "global mappings: ok" in out and "widget override mappings: ok" in out

    def test_exits_1_on_a_global_error(self, project, capsys):
        project.mappings.write_text(yaml.safe_dump({"mappings": [
            {"polearms": "bogus.field", "swords": "s"}]}))
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        assert "valid-polearms-field" in capsys.readouterr().out

    def test_exits_1_on_an_override_error(self, project, capsys):
        project.widget_config.write_text(yaml.safe_dump({
            "class_name": "widget",
            "override_mappings": [{"polearms": "serial", "swords": "x"}]}))
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        assert "widget override mappings: " in capsys.readouterr().out

    def test_warnings_alone_do_not_fail(self, project, capsys):
        schema = json.loads(project.schema.read_text())
        schema["classes"]["widget"]["attributes"]["owner"]["is_array"] = True
        project.schema.write_text(json.dumps(schema))
        project.mappings.write_text(yaml.safe_dump({"mappings": [
            {"polearms": "owner[x].email", "swords": "owner-email", "selectors": {"x": {"label": "a"}},
             "mapper": {"fn": "map_x"}}]}))
        project.widget_config.write_text(yaml.safe_dump({
            "class_name": "widget",
            "override_mappings": [{"polearms": "owner[y].email", "swords": "elsewhere",
                                   "selectors": {"y": {"label": "b"}}, "mapper": {"fn": "map_x"}}]}))
        vm.main()   # must not raise SystemExit
        out = capsys.readouterr().out
        assert "override-shadowing" in out and "WARNING" in out

    def test_exits_1_on_a_swords_field_missing_from_the_swords_schema(self, project, capsys):
        project.mappings.write_text(yaml.safe_dump({"mappings": [
            {"polearms": "name", "swords": "not-in-swords-schema"}]}))
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        assert "[valid-swords-field]" in capsys.readouterr().out

    def test_exits_1_on_an_override_swords_field_missing_from_the_swords_schema(self, project, capsys):
        project.widget_config.write_text(yaml.safe_dump({
            "class_name": "widget",
            "override_mappings": [{"polearms": "tags", "swords": "not-in-swords-schema"}]}))
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        assert "[valid-swords-field]" in capsys.readouterr().out

    def test_unknown_mapper_in_the_mappings_file_fails(self, project):
        project.mappings.write_text(yaml.safe_dump({"mappings": [
            {"polearms": "name", "swords": "s", "mapper": {"fn": "map_missing"}}]}))
        with pytest.raises(SystemExit):
            vm.main()

    def test_a_structurally_invalid_mappings_file_is_reported_by_the_json_schema(self, project, capsys):
        project.mappings.write_text(yaml.safe_dump({"mappings": [{"polearms": "name"}]}))
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "[json-schema] swords_mappings.yaml:mappings[0]: 'swords' is required" in out

    def test_a_mappings_file_with_the_wrong_shape_does_not_crash(self, project, capsys):
        project.mappings.write_text("- just\n- a list\n")
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        assert "[json-schema]" in capsys.readouterr().out

    def test_semantic_checks_are_skipped_for_a_document_that_fails_the_json_schema(self, project, capsys):
        # `bogus` would also be an invalid field, but the structural error is all that is reported.
        project.mappings.write_text(yaml.safe_dump({"mappings": [
            {"polearms": "bogus.field", "swords": "s", "extra": 1}]}))
        with pytest.raises(SystemExit):
            vm.main()
        out = capsys.readouterr().out
        assert "[json-schema]" in out and "valid-polearms-field" not in out

    def test_a_structurally_invalid_override_is_reported_by_the_json_schema(self, project, capsys):
        project.widget_config.write_text(yaml.safe_dump({
            "class_name": "widget", "override_mappings": [{"polearms": "name"}]}))
        with pytest.raises(SystemExit) as exc:
            vm.main()
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "widget override mappings: 1 error(s)" in out
        assert "[json-schema]" in out and "override_mappings" in out

    def test_overrides_are_not_checked_against_globals_that_failed_the_json_schema(self, project, capsys):
        project.mappings.write_text(yaml.safe_dump({"mappings": [{"polearms": "name"}]}))
        project.widget_config.write_text(yaml.safe_dump({
            "class_name": "widget", "override_mappings": [{"polearms": "serial", "swords": "x"}]}))
        with pytest.raises(SystemExit):
            vm.main()
        out = capsys.readouterr().out
        assert "widget override mappings: skipped (global mappings are invalid)" in out
        assert "override-relevance" not in out

    def test_a_config_without_overrides_is_ok(self, project, capsys):
        vm.main()
        assert "widget override mappings: ok" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Reading selector return annotations
# ---------------------------------------------------------------------------


class TestListSelectorNames:
    def load(self, tmp_path, source):
        path = tmp_path / "m.py"
        path.write_text(source)
        return vm.load_list_selector_names(path)

    def test_functions_annotated_to_return_a_list_are_list_selectors(self, tmp_path):
        names = self.load(tmp_path, (
            "def select_a(items) -> list:\n    return items\n"
            "def select_b(items) -> list[dict]:\n    return items\n"
            "def select_c(items) -> List[dict]:\n    return items\n"))
        assert names == {"select_a", "select_b", "select_c"}

    def test_other_annotations_and_no_annotation_return_one_item(self, tmp_path):
        names = self.load(tmp_path, (
            "def select_a(items) -> dict:\n    return items[0]\n"
            "def select_b(items):\n    return items[0]\n"
            "def select_c(items) -> str | None:\n    return None\n"))
        assert names == frozenset()

    def test_the_real_module_marks_only_select_after_first_as_a_list(self):
        assert vm.load_list_selector_names(vm.MAPPERS_AND_SELECTORS_PATH) == {"select_after_first"}
