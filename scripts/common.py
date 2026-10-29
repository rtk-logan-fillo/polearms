"""Shared loading code for the polearms scripts: mappings, class configs and the OCSF schema."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = ROOT / "version.json"
CONFIG_DIR = ROOT / "config"
MAPPINGS_PATH = ROOT / "mappings" / "mappings.yaml"
SCHEMA_PATH = ROOT / "schema" / "schema.json"
SCHEMA_DEFINITION_PATH = ROOT / "schema" / "schema_definition.yaml"
SWORDS_SCHEMA_PATH = ROOT / "schema" / "carser_swords_schema.json"
COMPLEX_MAPPINGS_PATH = ROOT / "mappings" / "complex_mappings.py"
CLASS_MAP_PATH = ROOT / "mappings" / "class_map.yaml"


_BRACKET = re.compile(r"\[[^\]]*\]")


def base_path(path: str) -> str:
    """Strip every [key] segment: 'attacks[x].tactic.uid' -> 'attacks.tactic.uid'."""
    return _BRACKET.sub("", path)


def label_keys(path: str) -> list[str]:
    """Every [key] token in a path, in order: 'a[x].b[y]' -> ['x', 'y']."""
    return re.findall(r"\[([^\]]*)\]", path)


def display_path(path: str, labels: dict[str, str]) -> str:
    """Replace [key] tokens with their label values: 'attacks[x].uid' -> 'attacks[uid!=null].uid'."""
    for key, label in labels.items():
        path = path.replace(f"[{key}]", f"[{label}]")
    return path


@dataclass
class Mapping:
    # In YAML, polearms is either one path or a list of paths; a single path is stored as a list.
    polearms: list[str] | str
    swords: str
    labels: dict[str, str] = field(default_factory=dict)
    mapper: dict | None = None

    def __post_init__(self):
        if isinstance(self.polearms, str):
            self.polearms = [self.polearms] if self.polearms else []
        else:
            self.polearms = list(self.polearms or [])

    @classmethod
    def from_dict(cls, raw: dict) -> Mapping:
        return cls(
            polearms=raw.get("polearms") or [],
            swords=raw.get("swords") or "",
            labels=dict(raw.get("labels") or {}),
            mapper=raw.get("mapper"),
        )

    def has_polearms(self) -> bool:
        return any(self.polearms)

    def base_paths(self) -> list[str]:
        """Each non-empty polearms path with its [key] segments stripped."""
        return [base_path(p) for p in self.polearms if p]

    def display_name(self) -> str:
        return ", ".join(display_path(p, self.labels) for p in self.polearms)

    def is_list_item(self) -> bool:
        """Whether the swords path targets items of a list, e.g. 'threat.enrichments[].x'."""
        return "[" in self.swords

    def label_keys(self) -> set[str]:
        """The [key] tokens used across the polearms and swords paths. A bare [] means "any
        item" and needs no labels entry."""
        return {k for p in [self.swords, *self.polearms] for k in label_keys(p) if k}

    def mapper_fn(self) -> str:
        return (self.mapper or {}).get("fn") or ""

    def is_many_to_one(self) -> bool:
        return len(self.polearms) > 1

    def display_swords(self) -> str:
        return display_path(self.swords, self.labels)

    def swords_field_path(self) -> str:
        return base_path(self.swords)

    def join_separator(self) -> str | None:
        return (self.mapper or {}).get("join")


@dataclass
class ClassConfig:
    name: str
    essential_fields_only: bool
    essential_fields: list[dict]
    override_mappings: list[Mapping]

    @classmethod
    def load(cls, path: Path) -> ClassConfig:
        raw = yaml.safe_load(path.read_text()) or {}
        return cls(
            name=raw.get("class_name", ""),
            essential_fields_only=bool(raw.get("essential_fields_only", False)),
            essential_fields=list(raw.get("essential_fields") or []),
            override_mappings=[Mapping.from_dict(m) for m in raw.get("override_mappings") or []],
        )

    def covers_path(self, path: str) -> bool:
        """Whether path is an essential field or lies under one. [key] segments are ignored."""
        p = base_path(path)
        for f in self.essential_fields:
            e = base_path(f["polearms"])
            if p == e or p.startswith(e + "."):
                return True
        return False


def load_mappings(path: Path) -> list[Mapping]:
    raw = yaml.safe_load(path.read_text()) or {}
    return [Mapping.from_dict(m) for m in raw.get("mappings") or []]


def load_definition(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def definition_version(definition: dict, section: str) -> str | None:
    """definition[section]['version'] as a string, or None if it is not set."""
    value = (definition.get(section) or {}).get("version")
    return None if value is None else str(value)


def load_version(path: Path) -> str:
    """The "version" string from a version.json such as {"version": "1.10.0-dev"}."""
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as err:
        raise SystemExit(f"{path.name} is not valid JSON: {err}")
    if not isinstance(raw, dict):
        raise SystemExit(f'{path.name} must be a JSON object like {{"version": "1.0.0"}}')
    version = raw.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SystemExit(f'{path.name} must have a non-empty string "version"')
    return version.strip()


class OCSFSchema:
    def __init__(self, data: dict):
        self.classes = data["classes"]
        self.objects = data["objects"]

    @classmethod
    def load(cls, path: Path) -> OCSFSchema:
        with open(path) as handle:
            return cls(json.load(handle))

    def lookup_class(self, class_name: str) -> dict:
        if class_name not in self.classes:
            raise SystemExit(f"class {class_name!r} not found in schema")
        return self.classes[class_name]

    def lookup_field(self, class_name: str, dot_path: str) -> dict | None:
        cls = self.classes.get(class_name)
        if cls is None:
            return None
        attrs = cls["attributes"]
        parts = dot_path.split(".")
        for i, part in enumerate(parts):
            attr = attrs.get(part.split("[", 1)[0])
            if attr is None:
                return None
            if i == len(parts) - 1:
                return attr
            obj = self.objects.get(attr.get("object_type", ""))
            if obj is None:
                return None
            attrs = obj["attributes"]
        return None


def discover_class_configs(config_dir: Path) -> list[Path]:
    return sorted(config_dir.rglob("config.yaml"))
