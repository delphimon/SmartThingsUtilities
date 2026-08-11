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
HEX_TRIPLET = re.compile(r"^(?:0x)?([0-9A-Fa-f]{4})/(?:0x)?([0-9A-Fa-f]{4})/(?:0x)?([0-9A-Fa-f]{4})$")


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


def _json_string(text: str, field: str) -> str | None:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"([^"]+)"', text)
    return match.group(1) if match else None


def _matching_bracket(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return index
    return None


def zwave_js_catalog(root: Path) -> tuple[dict[str, str], dict[str, list[dict[str, str]]]]:
    manufacturers_path = root / "packages" / "config" / "config" / "manufacturers.json"
    manufacturers = {
        match.group(1).upper(): match.group(2)
        for match in re.finditer(
            r'^\s*"0x([0-9A-Fa-f]{4})"\s*:\s*"([^"]+)"',
            manufacturers_path.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    devices: dict[str, list[dict[str, str]]] = {}
    device_root = root / "packages" / "config" / "config" / "devices"
    for path in device_root.rglob("*.json"):
        if "templates" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        manufacturer_id = _json_string(text, "manufacturerId")
        manufacturer = _json_string(text, "manufacturer")
        label = _json_string(text, "label")
        description = _json_string(text, "description")
        array_match = re.search(r'"devices"\s*:\s*\[', text)
        if not manufacturer_id or not manufacturer or not label or not array_match:
            continue
        end = _matching_bracket(text, array_match.end() - 1)
        if end is None:
            continue
        array = text[array_match.end():end]
        for match in re.finditer(
            r'"productType"\s*:\s*"0x([0-9A-Fa-f]{4})"[\s\S]*?'
            r'"productId"\s*:\s*"0x([0-9A-Fa-f]{4})"',
            array,
        ):
            key = f"{int(manufacturer_id, 0):04X}-{match.group(1).upper()}-{match.group(2).upper()}"
            record = {"manufacturer": manufacturer, "model": label}
            if description:
                record["description"] = description
            if record not in devices.setdefault(key, []):
                devices[key].append(record)
    return manufacturers, devices


def build(
    root: Path,
    source_url: str,
    source_revision: str | None,
    zwave_js_root: Path | None,
    zwave_js_revision: str | None,
) -> dict[str, Any]:
    zwave: dict[str, set[str]] = {}
    zigbee: dict[str, set[str]] = {}
    matter: dict[str, set[str]] = {}
    for path in root.rglob("fingerprints.yml"):
        for section, item in entries(path):
            label = item.get("deviceLabel")
            if not isinstance(label, str) or not label.strip():
                continue
            if section == "zwaveManufacturer":
                values = [item.get("manufacturerId"), item.get("productType"), item.get("productId")]
                structured_id = HEX_TRIPLET.fullmatch(str(item.get("id", "")))
                if structured_id:
                    for index, part in enumerate(structured_id.groups()):
                        if not isinstance(values[index], int):
                            values[index] = int(part, 16)
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

    manufacturers: dict[str, str] = {}
    zwave_js: dict[str, list[dict[str, str]]] = {}
    if zwave_js_root is not None:
        manufacturers, zwave_js = zwave_js_catalog(zwave_js_root)

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source_url,
        "sourceRevision": source_revision,
        "zwaveJsSource": "https://github.com/zwave-js/zwave-js",
        "zwaveJsSourceRevision": zwave_js_revision,
        "matching": "Exact identifiers only; multiple names are retained as ambiguous.",
        "zwave": clean(zwave),
        "zwaveManufacturers": manufacturers,
        "zwaveJs": dict(sorted(zwave_js.items())),
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
    parser.add_argument("--zwave-js-root", type=Path)
    parser.add_argument("--zwave-js-revision")
    args = parser.parse_args()
    payload = build(
        args.drivers_root,
        args.source_url,
        args.source_revision,
        args.zwave_js_root,
        args.zwave_js_revision,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
