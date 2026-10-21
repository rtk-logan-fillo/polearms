import inspect

import pytest
import yaml

import complex_mappings as cm
from scripts.common import MAPPINGS_PATH, CONFIG_DIR, discover_class_configs


# ---------------------------------------------------------------------------
# Helpers and the registry
# ---------------------------------------------------------------------------


def public_mapper_names():
    return {n for n, f in inspect.getmembers(cm, inspect.isfunction)
            if n.startswith("map_") and f.__module__ == cm.__name__}


class TestRegistry:
    def test_get_mapper_returns_the_named_function(self):
        assert cm.get_mapper("map_time") is cm.map_time

    def test_get_mapper_unknown_name_raises(self):
        with pytest.raises(KeyError):
            cm.get_mapper("map_nope")

    def test_registry_contains_every_mapper_function(self):
        assert set(cm.MAPPERS) == public_mapper_names()

    def test_registry_keys_match_function_names(self):
        assert all(fn.__name__ == name for name, fn in cm.MAPPERS.items())

    def test_every_mapper_referenced_by_the_yaml_is_defined(self):
        referenced = set()
        raw = yaml.safe_load(MAPPINGS_PATH.read_text())
        referenced |= {m["mapper"]["fn"] for m in raw["mappings"] if m.get("mapper")}
        for path in discover_class_configs(CONFIG_DIR):
            cfg = yaml.safe_load(path.read_text()) or {}
            referenced |= {m["mapper"]["fn"] for m in cfg.get("override_mappings") or []
                           if m.get("mapper")}
        assert referenced, "expected the repo to reference at least one mapper"
        assert referenced <= set(cm.MAPPERS), referenced - set(cm.MAPPERS)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestGet:
    def test_walks_nested_dicts(self):
        assert cm._get({"a": {"b": {"c": 1}}}, "a.b.c") == 1

    def test_missing_key_is_none(self):
        assert cm._get({"a": {}}, "a.b.c") is None

    def test_non_dict_midway_is_none(self):
        assert cm._get({"a": [1, 2]}, "a.b") is None
        assert cm._get({"a": "str"}, "a.b") is None

    def test_falsy_values_are_returned(self):
        assert cm._get({"a": 0}, "a") == 0
        assert cm._get({"a": ""}, "a") == ""


class TestAttackValues:
    def test_skips_missing_values_and_keeps_order(self):
        attacks = [{"tactic": {"uid": "TA1"}}, {"tactic": {}}, {}, {"tactic": {"uid": "TA2"}}]
        assert cm._attack_values(attacks, "tactic.uid") == ["TA1", "TA2"]

    def test_empty(self):
        assert cm._attack_values([], "tactic.uid") == []


class TestFirstEvidenceValue:
    def test_uses_only_the_first_evidence(self):
        evidences = [{"src_endpoint": {"ip": "1.1.1.1"}}, {"src_endpoint": {"ip": "2.2.2.2"}}]
        assert cm._first_evidence_value(evidences, "src_endpoint.ip") == "1.1.1.1"

    @pytest.mark.parametrize("evidences", [None, []])
    def test_no_evidence_is_none(self, evidences):
        assert cm._first_evidence_value(evidences, "src_endpoint.ip") is None


# ---------------------------------------------------------------------------
# Scalar mappers
# ---------------------------------------------------------------------------


class TestTelemetryTypes:
    @pytest.mark.parametrize("uid,name", [
        (2004, "Detection Finding"), (3001, "Account Change"), (3002, "Authentication"),
        (4002, "HTTP Activity"), (98500000, "Vendor Overflow"),
    ])
    def test_known_classes_come_from_the_class_map(self, uid, name):
        assert cm.map_telemetry_types(uid) == [name]

    def test_unknown_class_is_none(self):
        assert cm.map_telemetry_types(123456789) is None

    def test_loaded_from_class_map_yaml(self):
        expected = yaml.safe_load(cm.CLASS_MAP_PATH.read_text())["classes"]
        assert cm.TELEMETRY_TYPES == expected


class TestMapTime:
    def test_whole_seconds_have_no_fraction(self):
        assert cm.map_time(1700000000000) == "2023-11-14T22:13:20"

    def test_milliseconds_use_the_fractional_format(self):
        assert cm.map_time(1700000000123) == "2023-11-14T22:13:20.123000"

    def test_epoch(self):
        assert cm.map_time(0) == "1970-01-01T00:00:00"

    def test_is_utc_not_local_time(self, monkeypatch):
        import time
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        time.tzset()
        try:
            assert cm.map_time(1700000000000) == "2023-11-14T22:13:20"
        finally:
            monkeypatch.undo()
            time.tzset()


class TestMapActivityId:
    @pytest.mark.parametrize("value,expected", [(1, "1"), (0, "0"), (99, "99")])
    def test_to_string(self, value, expected):
        assert cm.map_activity_id(value) == expected


class TestUserResultGroupsUid:
    def test_collects_uids_and_skips_groups_without_one(self):
        groups = [{"uid": "g1"}, {"name": "no-uid"}, {"uid": "g2"}]
        assert cm.map_user_result_groups_uid(groups) == ["g1", "g2"]

    def test_empty(self):
        assert cm.map_user_result_groups_uid([]) == []


class TestMalwareScanInfo:
    def test_size_is_stringified_and_wrapped(self):
        assert cm.map_malware_scan_info_size(2048) == [{"indicator": {"file": {"size": "2048"}}}]

    def test_type_is_wrapped(self):
        assert cm.map_malware_scan_info_type("PE") == [{"indicator": {"file": {"type": "PE"}}}]


# ---------------------------------------------------------------------------
# Attack mappers
# ---------------------------------------------------------------------------

ATTACKS = [
    {"tactic": {"uid": "TA1", "name": "Recon", "src_url": "http://t1"},
     "technique": {"uid": "T1", "name": "Scan", "src_url": "http://q1"},
     "sub_technique": {"src_url": "http://s1"}},
    {"tactic": {"uid": "TA2", "name": "Exec", "src_url": "http://t2"},
     "technique": {"uid": "T2", "name": "Run", "src_url": "http://q2"}},
]

ATTACK_CASES = [
    ("map_attack_tactic_id", ["TA1", "TA2"]),
    ("map_attack_tactic_name", ["Recon", "Exec"]),
    ("map_attack_tactic_reference", ["http://t1", "http://t2"]),
    ("map_attack_technique_id", ["T1", "T2"]),
    ("map_attack_technique_name", ["Scan", "Run"]),
    ("map_attack_technique_reference", ["http://q1", "http://q2"]),
    ("map_attack_subtechnique_reference", ["http://s1"]),
]


class TestAttackMappers:
    @pytest.mark.parametrize("name,expected", ATTACK_CASES)
    def test_collects_values_across_attacks(self, name, expected):
        assert cm.get_mapper(name)(ATTACKS) == expected

    @pytest.mark.parametrize("name,_", ATTACK_CASES)
    def test_attacks_missing_the_field_are_skipped(self, name, _):
        result = cm.get_mapper(name)([{"unrelated": 1}])
        assert not result

    @pytest.mark.parametrize("name", [
        "map_attack_tactic_id", "map_attack_tactic_name", "map_attack_technique_id",
        "map_attack_technique_name",
    ])
    def test_list_valued_mappers_return_none_when_empty(self, name):
        assert cm.get_mapper(name)([]) is None

    @pytest.mark.parametrize("name", [
        "map_attack_tactic_reference", "map_attack_technique_reference",
        "map_attack_subtechnique_reference",
    ])
    def test_reference_mappers_return_an_empty_list_when_empty(self, name):
        # These feed a joined string, so an empty list (not None) is the contract.
        assert cm.get_mapper(name)([]) == []


# ---------------------------------------------------------------------------
# Evidence mappers
# ---------------------------------------------------------------------------

EVIDENCE = {
    "src_endpoint": {"ip": "10.0.0.1", "port": 5555,
                     "location": {"city": "Paris", "country": "FR", "lat": 48.85, "long": 2.35}},
    "dst_endpoint": {"ip": "10.0.0.2", "port": 443, "hostname": "srv.example"},
    "http_request": {"http_method": "GET", "referrer": "http://ref", "user_agent": "UA/1.0",
                     "uid": "req-1", "length": 120,
                     "url": {"url_string": "http://x/y?z=1", "scheme": "http", "path": "/y"}},
    "http_response": {"code": 200, "body_length": 999},
}

FIRST_EVIDENCE_CASES = [
    ("map_evidence_client_ip", "10.0.0.1"),
    ("map_evidence_client_port", 5555),
    ("map_evidence_server_ip", "10.0.0.2"),
    ("map_evidence_geoip_city", "Paris"),
    ("map_evidence_geoip_country", "FR"),
    ("map_evidence_http_status", 200),
    ("map_evidence_http_method", "GET"),
    ("map_evidence_http_referer", "http://ref"),
    ("map_evidence_http_uri", "http://x/y?z=1"),
    ("map_evidence_server_hostname", "srv.example"),
    ("map_evidence_server_port", 443),
    ("map_evidence_request_length", 120),
    ("map_evidence_request_scheme", "http"),
    ("map_evidence_request_uid", "req-1"),
    ("map_evidence_request_path", "/y"),
    ("map_evidence_response_body_length", 999),
    ("map_evidence_user_agent", "UA/1.0"),
]


class TestFirstEvidenceMappers:
    @pytest.mark.parametrize("name,expected", FIRST_EVIDENCE_CASES)
    def test_reads_the_first_evidence(self, name, expected):
        assert cm.get_mapper(name)([EVIDENCE]) == expected

    @pytest.mark.parametrize("name,_", FIRST_EVIDENCE_CASES)
    def test_ignores_later_evidence(self, name, _):
        assert cm.get_mapper(name)([{}, EVIDENCE]) is None

    @pytest.mark.parametrize("name,_", FIRST_EVIDENCE_CASES)
    @pytest.mark.parametrize("evidences", [None, [], [{}]])
    def test_missing_evidence_is_none(self, name, _, evidences):
        assert cm.get_mapper(name)(evidences) is None

    def test_latitude_and_longitude_are_stringified(self):
        assert cm.map_evidence_geoip_latitude([EVIDENCE]) == "48.85"
        assert cm.map_evidence_geoip_longitude([EVIDENCE]) == "2.35"

    def test_zero_coordinates_are_not_treated_as_missing(self):
        zero = {"src_endpoint": {"location": {"lat": 0, "long": 0}}}
        assert cm.map_evidence_geoip_latitude([zero]) == "0"
        assert cm.map_evidence_geoip_longitude([zero]) == "0"

    def test_missing_coordinates_are_none(self):
        assert cm.map_evidence_geoip_latitude([{}]) is None
        assert cm.map_evidence_geoip_longitude([]) is None


class TestSecurityZone:
    def test_first_resource_with_a_hostname(self):
        evidences = [{"resources": [{"name": "x"}, {"hostname": "zone-a"}, {"hostname": "zone-b"}]}]
        assert cm.map_evidence_security_zone(evidences) == "zone-a"

    def test_non_dict_resources_are_skipped(self):
        assert cm.map_evidence_security_zone([{"resources": ["str", {"hostname": "z"}]}]) == "z"

    @pytest.mark.parametrize("evidences", [
        None, [], [{}], [{"resources": []}], [{"resources": [{"name": "x"}]}],
    ])
    def test_none_when_nothing_matches(self, evidences):
        assert cm.map_evidence_security_zone(evidences) is None

    def test_only_the_first_evidence_is_considered(self):
        assert cm.map_evidence_security_zone([{}, {"resources": [{"hostname": "z"}]}]) is None


class TestRelatedIp:
    def test_first_evidence_contributes_only_its_proxy(self):
        evidences = [{"src_endpoint": {"ip": "1.1.1.1"}, "dst_endpoint": {"ip": "2.2.2.2",
                      "proxy_endpoint": {"ip": "9.9.9.9"}}}]
        assert cm.map_evidence_related_ip(evidences) == ["9.9.9.9"]

    def test_later_evidence_contributes_src_dst_and_proxy_in_order(self):
        evidences = [
            {"src_endpoint": {"ip": "0.0.0.0"}},
            {"src_endpoint": {"ip": "1.1.1.1"},
             "dst_endpoint": {"ip": "2.2.2.2", "proxy_endpoint": {"ip": "3.3.3.3"}}},
            {"dst_endpoint": {"ip": "4.4.4.4"}},
        ]
        assert cm.map_evidence_related_ip(evidences) == ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]

    @pytest.mark.parametrize("evidences", [[], [{}], [{"src_endpoint": {"ip": "1.1.1.1"}}]])
    def test_none_when_there_is_nothing_related(self, evidences):
        assert cm.map_evidence_related_ip(evidences) is None


FINGERPRINTS = [
    {"algorithm_id": 1, "value": "md5-a"},
    {"algorithm_id": 2, "value": "sha1-a"},
    {"algorithm_id": 3, "value": "sha256-a"},
    {"algorithm_id": 1, "value": "md5-b"},
]


def with_fingerprints(*fingerprints):
    return {"tls": {"certificate": {"fingerprints": list(fingerprints)}}}


class TestHashEnrichments:
    @pytest.mark.parametrize("name,algorithm,values", [
        ("map_evidence_hash_md5", "md5", ["md5-a", "md5-b"]),
        ("map_evidence_hash_sha1", "sha1", ["sha1-a"]),
        ("map_evidence_hash_sha256", "sha256", ["sha256-a"]),
    ])
    def test_selects_by_algorithm(self, name, algorithm, values):
        result = cm.get_mapper(name)([with_fingerprints(*FINGERPRINTS)])
        assert result == [{"indicator": {"hash": {algorithm: v}}} for v in values]

    def test_collects_across_all_evidence(self):
        evidences = [with_fingerprints({"algorithm_id": 1, "value": "a"}),
                     with_fingerprints({"algorithm_id": 1, "value": "b"})]
        assert cm.map_evidence_hash_md5(evidences) == [
            {"indicator": {"hash": {"md5": "a"}}}, {"indicator": {"hash": {"md5": "b"}}}]

    @pytest.mark.parametrize("name", [
        "map_evidence_hash_md5", "map_evidence_hash_sha1", "map_evidence_hash_sha256"])
    @pytest.mark.parametrize("evidences", [
        [], [{}], [with_fingerprints()], [with_fingerprints({"algorithm_id": 99, "value": "x"})],
    ])
    def test_none_when_no_matching_fingerprint(self, name, evidences):
        assert cm.get_mapper(name)(evidences) is None
