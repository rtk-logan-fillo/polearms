#!/usr/bin/env python3
"""Generate a YAML map from class_uid to class caption from the OCSF schema.

Usage:
    python3 scripts/generate_class_map.py                       # write mappings/class_map.yaml
    python3 scripts/generate_class_map.py -o -                  # write to stdout
    python3 scripts/generate_class_map.py path/to/schema.json
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

DEFAULT_SCHEMA = Path(__file__).resolve().parent.parent / "schema" / "schema.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "mappings" / "class_map.yaml"


def load_schema(path):
    with open(path) as handle:
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(handle)
        return json.load(handle)


def build_class_map(schema):
    classes = schema.get("classes")
    if not classes:
        raise SystemExit("schema has no 'classes' section")

    class_map = {}
    for key, cls in classes.items():
        uid = cls.get("uid")
        caption = cls.get("caption")
        if uid is None or not caption:
            print(f"skipping {key}: missing uid or caption", file=sys.stderr)
            continue
        if uid in class_map and class_map[uid] != caption:
            raise SystemExit(f"duplicate class_uid {uid}: {class_map[uid]!r} vs {caption!r}")
        class_map[uid] = caption
    return dict(sorted(class_map.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema", nargs="?", type=Path, default=DEFAULT_SCHEMA,
                        help=f"path to the OCSF schema (.json or .yaml), default: {DEFAULT_SCHEMA}")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT),
                        help=f"output path, or '-' for stdout, default: {DEFAULT_OUTPUT}")
    args = parser.parse_args()

    class_map = build_class_map(load_schema(args.schema))
    document = yaml.safe_dump({"classes": class_map}, sort_keys=False, default_flow_style=False)

    if args.output == "-":
        sys.stdout.write(document)
    else:
        Path(args.output).write_text(document)
        print(f"wrote {len(class_map)} classes to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
