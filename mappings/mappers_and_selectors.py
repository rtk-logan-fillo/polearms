from datetime import datetime, timezone
from pathlib import Path

import yaml

DATETIME_FORMAT_MILLI = "%Y-%m-%dT%H:%M:%S.%f"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

MD5, SHA1, SHA256, IMPHASH = 1, 2, 3, 18

CLASS_MAPPINGS_PATH = Path(__file__).resolve().parent / "class_mappings.yaml"
with open(CLASS_MAPPINGS_PATH) as _class_map_file:
    TELEMETRY_TYPES = yaml.safe_load(_class_map_file)["classes"]


def map_telemetry_types(class_uid):
    telemetry_type = TELEMETRY_TYPES.get(class_uid)
    return [telemetry_type] if telemetry_type else None


def map_time(time):
    datetime_format = DATETIME_FORMAT if time % 1000 == 0 else DATETIME_FORMAT_MILLI
    return datetime.fromtimestamp(time / 1000, tz=timezone.utc).strftime(datetime_format)


def map_to_string(value):
    return None if value is None else str(value)


def map_activity_id(activity_id):
    return str(activity_id)


def _first_with_algorithm(items, algorithm_id):
    for item in items:
        if item.get("algorithm_id") == algorithm_id:
            return item
    return None


def select_first_md5(items):
    return _first_with_algorithm(items, MD5)


def select_first_sha1(items):
    return _first_with_algorithm(items, SHA1)


def select_first_sha256(items):
    return _first_with_algorithm(items, SHA256)


def select_first_imphash(items):
    return _first_with_algorithm(items, IMPHASH)


def select_after_first(items) -> list:
    return items[1:]


MAPPERS = {
    "map_telemetry_types": map_telemetry_types,
    "map_time": map_time,
    "map_activity_id": map_activity_id,
    "map_to_string": map_to_string,
}


SELECTORS = {
    "select_first_md5": select_first_md5,
    "select_first_sha1": select_first_sha1,
    "select_first_sha256": select_first_sha256,
    "select_first_imphash": select_first_imphash,
    "select_after_first": select_after_first,
}


def get_mapper(name):
    return MAPPERS[name]


def get_selector(name):
    return SELECTORS[name]
