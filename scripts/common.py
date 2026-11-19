"""Shared loading code for the polearms scripts: mappings, class configs and the OCSF schema."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = ROOT / "version.json"
CONFIG_DIR = ROOT / "config"
SWORDS_MAPPINGS_PATH = ROOT / "mappings" / "swords_mappings.yaml"
SCHEMA_PATH = ROOT / "schema" / "schema.json"
SCHEMA_DEFINITION_PATH = ROOT / "schema" / "schema_definition.yaml"
SWORDS_SCHEMA_PATH = ROOT / "schema" / "carser_swords_schema.json"
AXES_MAPPINGS_PATH = ROOT / "schema" / "axes_mappings.json"
MAPPERS_AND_SELECTORS_PATH = ROOT / "mappings" / "mappers_and_selectors.py"
CLASS_MAPPINGS_PATH = ROOT / "mappings" / "class_mappings.yaml"


_BRACKET = re.compile(r"\[[^\]]*\]")
_INDEX = re.compile(r"[0-9]+")


def is_index(key: str) -> bool:
    """Whether a bracket's content is an array index, like the 0 in 'evidences[0]'."""
    return _INDEX.fullmatch(key) is not None


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
    selectors: dict[str, dict] = field(default_factory=dict)
    mapper: dict | None = None
    join: str | None = None
    first: bool = False

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
            selectors={k: dict(v) for k, v in (raw.get("selectors") or {}).items()},
            mapper=raw.get("mapper"),
            join=raw.get("join"),
            first=bool(raw.get("first", False)),
        )

    @property
    def labels(self) -> dict[str, str]:
        """Each selector's label, by bracket key, for showing in paths."""
        return {k: v.get("label", "") for k, v in self.selectors.items()}

    def selector_fn(self, key: str) -> str:
        return (self.selectors.get(key) or {}).get("fn") or ""

    def path_produces_list(self, path: str, list_selectors: frozenset[str] | None = None) -> bool:
        """Whether one polearms path gives several items: it has a bare [] or a selector that
        returns a list. An index [N], a selector that returns one item, and a documentation-only
        selector do not. With list_selectors left out, every selector function counts as list-returning."""
        for key in label_keys(path):
            if key == "":
                return True
            fn = self.selector_fn(key)
            if not is_index(key) and fn and (list_selectors is None or fn in list_selectors):
                return True
        return False

    def produces_list(self, list_selectors: frozenset[str] | None = None) -> bool:
        """Whether every polearms path gives a list. A mapping combining several paths gives one
        only if each of them does, because the lists are joined end to end."""
        paths = [p for p in self.polearms if p]
        return bool(paths) and all(self.path_produces_list(p, list_selectors) for p in paths)

    def logic_key(self) -> str:
        """What computes the value: the mapper function plus the selector functions, so two
        mappings of one field that pick different items (file.hashes by algorithm) are told apart."""
        selectors = ",".join(self.selector_fn(k) for k in sorted(self.selectors) if self.selector_fn(k))
        return self.mapper_fn() + (f"+{selectors}" if selectors else "")

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
        item" and a [N] index picks one; neither needs a selectors entry."""
        return {k for p in [self.swords, *self.polearms] for k in label_keys(p) if k and not is_index(k)}

    def mapper_fn(self) -> str:
        return (self.mapper or {}).get("fn") or ""

    def is_many_to_one(self) -> bool:
        return len(self.polearms) > 1

    def display_swords(self) -> str:
        return display_path(self.swords, self.labels)

    def swords_field_path(self) -> str:
        return base_path(self.swords)

    def join_separator(self) -> str | None:
        return self.join


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


@dataclass(frozen=True)
class Constraint:
    """A constraint (at_least_one, just_one) on a group of fields; members are full field paths."""
    kind: str
    members: tuple[str, ...]


def is_object_field(attr: dict) -> bool:
    """Whether an OCSF attribute is an object (or an array of objects) rather than a primitive."""
    return attr.get("type") == "object_t" or "object_type" in attr


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

    def array_segments(self, class_name: str, dot_path: str) -> list[bool] | None:
        """For each dot-separated segment of the path, whether that attribute is an array.
        None if the path is not a field of the class. [key] suffixes are ignored."""
        cls = self.classes.get(class_name)
        if cls is None:
            return None
        attrs = cls["attributes"]
        parts = dot_path.split(".")
        flags: list[bool] = []
        for i, part in enumerate(parts):
            attr = attrs.get(part.split("[", 1)[0])
            if attr is None:
                return None
            flags.append(bool(attr.get("is_array")))
            if i < len(parts) - 1:
                obj = self.objects.get(attr.get("object_type", ""))
                if obj is None:
                    return None
                attrs = obj["attributes"]
        return flags

    def field_constraints(self, class_name: str, dot_path: str) -> list[Constraint]:
        """The constraints the path's last attribute takes part in, with each member written as a
        full field path: for actor.user.name, the user object's [account, name, uid] become
        actor.user.account, actor.user.name, actor.user.uid.

        Constraints belong to the class or object that owns the attribute, and name that owner's
        attributes. [key] suffixes are ignored.
        """
        cls = self.classes.get(class_name)
        if cls is None:
            return []
        owner, attrs = cls, cls["attributes"]
        parts = [part.split("[", 1)[0] for part in dot_path.split(".")]
        for i, name in enumerate(parts):
            attr = attrs.get(name)
            if attr is None:
                return []
            if i == len(parts) - 1:
                prefix = "".join(f"{p}." for p in parts[:-1])
                found = self._constraints_naming(owner, prefix, name)
                if owner is not cls:
                    # A class constraint can name a nested field by its full path.
                    found += self._constraints_naming(cls, "", ".".join(parts))
                return found
            owner = self.objects.get(attr.get("object_type", ""))
            if owner is None:
                return []
            attrs = owner["attributes"]
        return []

    @staticmethod
    def _constraints_naming(owner: dict, prefix: str, member: str) -> list[Constraint]:
        return [Constraint(kind, tuple(prefix + m for m in members))
                for kind, members in (owner.get("constraints") or {}).items()
                if member in members]

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
