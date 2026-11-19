import inspect

import pytest
import yaml

import mappers_and_selectors as cm


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
        expected = yaml.safe_load(cm.CLASS_MAPPINGS_PATH.read_text())["classes"]
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

class TestMapToString:
    @pytest.mark.parametrize("value,expected", [(48.85, "48.85"), (0, "0"), (0.0, "0.0"), (7, "7")])
    def test_stringifies_the_value(self, value, expected):
        assert cm.map_to_string(value) == expected

    def test_none_stays_none(self):
        assert cm.map_to_string(None) is None


ITEMS = [
    {"algorithm_id": 1, "value": "md5-a"},
    {"algorithm_id": 2, "value": "sha1-a"},
    {"algorithm_id": 3, "value": "sha256-a"},
    {"algorithm_id": 18, "value": "imphash-a"},
    {"algorithm_id": 1, "value": "md5-b"},
    {"algorithm_id": 99, "algorithm": "ssdeep", "value": "other"},
]

SELECTOR_CASES = [
    ("select_first_md5", ["md5-a", "md5-b"]),
    ("select_first_sha1", ["sha1-a"]),
    ("select_first_sha256", ["sha256-a"]),
    ("select_first_imphash", ["imphash-a"]),
]


class TestSelectors:
    @pytest.mark.parametrize("name,values", SELECTOR_CASES)
    def test_first_selectors_return_the_first_match_as_one_item(self, name, values):
        item = cm.get_selector(name)(ITEMS)
        assert item == next(i for i in ITEMS if i["value"] == values[0])

    @pytest.mark.parametrize("name,_", SELECTOR_CASES)
    @pytest.mark.parametrize("items", [[], [{}], [{"algorithm_id": 99, "value": "x"}]])
    def test_first_selectors_return_none_when_nothing_matches(self, name, _, items):
        assert cm.get_selector(name)(items) is None

    def test_select_after_first_drops_only_the_first_item(self):
        assert cm.select_after_first([1, 2, 3]) == [2, 3]

    @pytest.mark.parametrize("items", [[], [1]])
    def test_select_after_first_is_empty_with_at_most_one_item(self, items):
        assert cm.select_after_first(items) == []

    def test_get_selector_unknown_name_raises(self):
        with pytest.raises(KeyError):
            cm.get_selector("select_nope")

    def test_registry_contains_every_selector_function(self):
        assert set(cm.SELECTORS) == {n for n, f in inspect.getmembers(cm, inspect.isfunction)
                                     if n.startswith("select_") and f.__module__ == cm.__name__}

    def test_registry_keys_match_function_names(self):
        assert all(fn.__name__ == name for name, fn in cm.SELECTORS.items())
