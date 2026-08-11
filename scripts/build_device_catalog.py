#!/usr/bin/env python3
"""Build the bundled exact-fingerprint catalog from SmartThings Edge drivers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


FIELD = re.compile(r"^    ([A-Za-z][A-Za-z0-9]*):\s*(.*?)\s*$")


def scalar(value: str) -> str | int:
    value = value.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    try:
        return int(value, 0)
    except ValueError:
        return value


def entries(path: Path) -> list[tuple[str, dict[str, Any]]]:
    section: str | None = None
    current: dict[str, Any] | None = None
    found: list[tuple[str, dict[str, Any]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line in {"zwaveManufacturer:", "zigbeeManufacturer:", "matterManufacturer:"}:
            section = line[:-1]
            continue
        if line.startswith("  - id:"):
            if section and current:
                found.append((section, current))
            current = {"id": scalar(line.split(":", 1)[1])}
            continue
        match = FIELD.match(line)
        if current is not None and match:
            current[match.group(1)] = scalar(match.group(2))
    if section and current:
        found.append((section, current))
    return found


def build(root: Path, source_url: str, source_revision: str | None) -> dict[str, Any]:
    zwave: dict[str, set[str]] = {}
    zigbee: dict[str, set[str]] = {}
    matter: dict[str, set[str]] = {}
    for path in root.rglob("fingerprints.yml"):
        for section, item in entries(path):
            label = item.get("deviceLabel")
            if not isinstance(label, str) or not label.strip():
                continue
            if section == "zwaveManufacturer":
                values = (item.get("manufacturerId"), item.get("productType"), item.get("productId"))
                if not all(isinstance(value, int) for value in values):
                    continue
                key = "-".join(f"{value:04X}" for value in values)
                zwave.setdefault(key, set()).add(label.strip())
            elif section == "zigbeeManufacturer":
                manufacturer, model = item.get("manufacturer"), item.get("model")
                if not isinstance(manufacturer, str) or not isinstance(model, str):
                    continue
                key = f"{manufacturer.casefold()}\0{model.casefold()}"
                zigbee.setdefault(key, set()).add(label.strip())
            elif section == "matterManufacturer":
                vendor_id, product_id = item.get("vendorId"), item.get("productId")
                if not isinstance(vendor_id, int) or not isinstance(product_id, int):
                    continue
                key = f"{vendor_id:04X}-{product_id:04X}"
                matter.setdefault(key, set()).add(label.strip())

    def clean(items: dict[str, set[str]]) -> dict[str, list[str]]:
        return {key: sorted(labels) for key, labels in sorted(items.items())}

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source_url,
        "sourceRevision": source_revision,
        "matching": "Exact identifiers only; multiple names are retained as ambiguous.",
        "zwave": clean(zwave),
        "zigbee": clean(zigbee),
        "matter": clean(matter),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("drivers_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--source-url",
        default="https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers",
    )
    parser.add_argument("--source-revision")
    args = parser.parse_args()
    payload = build(args.drivers_root, args.source_url, args.source_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
