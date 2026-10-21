import json
from types import SimpleNamespace

import pytest
import yaml

from scripts.common import OCSFSchema

MINI_SCHEMA = {
    "classes": {
        "widget": {
            "uid": 1,
            "caption": "Widget",
            "description": "A <b>widget</b>.",
            "attributes": {
                "name": {"caption": "Name", "description": "The <i>name</i>.",
                         "type": "string_t", "requirement": "required"},
                "tags": {"caption": "Tags", "description": "Labels.",
                         "type": "string_t", "requirement": "optional"},
                "owner": {"caption": "Owner", "description": "Who owns it.", "type": "object_t",
                          "object_type": "person", "requirement": "recommended"},
            },
        },
        "gadget": {
            "uid": 2,
            "caption": "Gadget",
            "description": "",
            "attributes": {
                "serial": {"caption": "Serial", "description": "Serial number.",
                           "type": "string_t", "requirement": "required"},
            },
        },
    },
    "objects": {
        "person": {"attributes": {
            "email": {"caption": "Email", "description": "Email address.",
                      "type": "email_t", "requirement": "optional"},
            "address": {"caption": "Address", "description": "Where.", "type": "object_t",
                        "object_type": "address", "requirement": "optional"},
        }},
        "address": {"attributes": {
            "city": {"caption": "City", "description": "The city.",
                     "type": "string_t", "requirement": "optional"},
        }},
    },
}


@pytest.fixture
def mini_schema() -> OCSFSchema:
    return OCSFSchema(json.loads(json.dumps(MINI_SCHEMA)))


@pytest.fixture
def fake_project(tmp_path):
    """A tiny repo layout (version.json, mappings, schema, one class config) in a temp dir.

    Returns the paths, named like the constants in common, ready to monkeypatch in.
    """
    version = tmp_path / "version.json"
    version.write_text(json.dumps({"version": "1.2.3"}))

    mappings = tmp_path / "mappings.yaml"
    mappings.write_text(yaml.safe_dump({"mappings": [
        {"polearms": "name", "swords": "widget-name"},
        {"polearms": "owner.email", "swords": "owner-email"},
    ]}))

    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(MINI_SCHEMA))

    complex_mappings = tmp_path / "complex_mappings.py"
    complex_mappings.write_text("def map_x(value):\n    return value\n")

    config_dir = tmp_path / "config"
    (config_dir / "widget").mkdir(parents=True)
    (config_dir / "widget" / "config.yaml").write_text(yaml.safe_dump({
        "class_name": "widget",
        "class_uid": 1,
        "essential_fields": [{"polearms": "name", "expected": True}, {"polearms": "tags"}],
    }))

    return SimpleNamespace(
        root=tmp_path, version=version, mappings=mappings, schema=schema,
        complex_mappings=complex_mappings, config_dir=config_dir,
        widget_config=config_dir / "widget" / "config.yaml",
    )
