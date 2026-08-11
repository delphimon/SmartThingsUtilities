"""Normalize SmartThings Z-Wave device and firmware inventory data."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, TextIO


FIRMWARE_REPORTED = "REPORTED"
FIRMWARE_CAPABILITY_NO_VALUE = "CAPABILITY_NO_VALUE"
FIRMWARE_NOT_EXPOSED = "NOT_EXPOSED"

CSV_FIELDS = [
    "label",
    "location",
    "room",
    "health",
    "health_last_updated",
    "firmware_status",
    "firmware_version",
    "firmware_timestamp",
    "available_version",
    "update_available",
    "manufacturer_code",
    "manufacturer_id",
    "product_type",
    "product_id",
    "zwave_node_id",
    "network_security_level",
    "executing_locally",
    "smartthings_device_id",
    "driver_id",
    "hub_id",
    "device_name",
]


def _attribute_value(status: Any, attribute: str) -> Any:
    if not isinstance(status, dict):
        return None
    entry = status.get(attribute)
    if not isinstance(entry, dict):
        return None
    return entry.get("value")


def _attribute_timestamp(status: Any, attribute: str) -> str | None:
    if not isinstance(status, dict):
        return None
    entry = status.get(attribute)
    if not isinstance(entry, dict):
        return None
    timestamp = entry.get("timestamp")
    return timestamp if isinstance(timestamp, str) else None


def _hex16(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return f"0x{value:04X}"


def _manufacturer_code(device: dict[str, Any], zwave: dict[str, Any]) -> str | None:
    supplied = device.get("deviceManufacturerCode")
    if isinstance(supplied, str) and supplied.strip():
        return supplied.strip().upper()

    values = [zwave.get("manufacturerId"), zwave.get("productType"), zwave.get("productId")]
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "-".join(f"{value:04X}" for value in values)
    return None


def _firmware_capabilities(device: dict[str, Any]) -> list[tuple[str | None, dict[str, Any]]]:
    matches: list[tuple[str | None, dict[str, Any]]] = []
    for component in device.get("components") or []:
        if not isinstance(component, dict):
            continue
        component_id = component.get("id") if isinstance(component.get("id"), str) else None
        for capability in component.get("capabilities") or []:
            if isinstance(capability, dict) and capability.get("id") == "firmwareUpdate":
                matches.append((component_id, capability))
    return matches


def _firmware(device: dict[str, Any]) -> dict[str, Any]:
    matches = _firmware_capabilities(device)
    if not matches:
        return {
            "status": FIRMWARE_NOT_EXPOSED,
            "version": None,
            "timestamp": None,
            "component": None,
            "availableVersion": None,
            "updateAvailable": None,
        }

    selected_component, selected = matches[0]
    for component_id, capability in matches:
        current = _attribute_value(capability.get("status"), "currentVersion")
        if current not in (None, ""):
            selected_component, selected = component_id, capability
            break

    status = selected.get("status")
    version = _attribute_value(status, "currentVersion")
    firmware_status = (
        FIRMWARE_REPORTED if version not in (None, "") else FIRMWARE_CAPABILITY_NO_VALUE
    )
    return {
        "status": firmware_status,
        "version": version,
        "timestamp": _attribute_timestamp(status, "currentVersion"),
        "component": selected_component,
        "availableVersion": _attribute_value(status, "availableVersion"),
        "updateAvailable": _attribute_value(status, "updateAvailable"),
    }


def normalize_device(device: dict[str, Any]) -> dict[str, Any]:
    zwave = device.get("zwave") if isinstance(device.get("zwave"), dict) else {}
    health = device.get("healthState") if isinstance(device.get("healthState"), dict) else {}
    firmware = _firmware(device)

    return {
        "label": device.get("label"),
        "location": device.get("location"),
        "room": device.get("room"),
        "health": health.get("state"),
        "healthLastUpdated": health.get("lastUpdatedDate"),
        "firmwareStatus": firmware["status"],
        "firmwareVersion": firmware["version"],
        "firmwareTimestamp": firmware["timestamp"],
        "firmwareComponent": firmware["component"],
        "availableVersion": firmware["availableVersion"],
        "updateAvailable": firmware["updateAvailable"],
        "manufacturerCode": _manufacturer_code(device, zwave),
        "manufacturerId": _hex16(zwave.get("manufacturerId")),
        "productType": _hex16(zwave.get("productType")),
        "productId": _hex16(zwave.get("productId")),
        "zwaveNodeId": zwave.get("networkId"),
        "networkSecurityLevel": zwave.get("networkSecurityLevel"),
        "executingLocally": zwave.get("executingLocally"),
        "smartthingsDeviceId": device.get("deviceId"),
        "driverId": zwave.get("driverId"),
        "hubId": zwave.get("hubId"),
        "deviceName": device.get("name"),
    }


def normalize_devices(devices: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = [normalize_device(device) for device in devices if isinstance(device, dict)]
    normalized.sort(
        key=lambda item: (
            str(item.get("location") or "").casefold(),
            str(item.get("room") or "").casefold(),
            str(item.get("label") or "").casefold(),
            str(item.get("smartthingsDeviceId") or ""),
        )
    )
    return normalized


def summary(devices: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "totalDevices": 0,
        FIRMWARE_REPORTED: 0,
        FIRMWARE_CAPABILITY_NO_VALUE: 0,
        FIRMWARE_NOT_EXPOSED: 0,
    }
    for device in devices:
        counts["totalDevices"] += 1
        firmware_status = device.get("firmwareStatus")
        if firmware_status in counts:
            counts[firmware_status] += 1
    return counts


def build_inventory(
    devices: Iterable[dict[str, Any]],
    *,
    generated_at: datetime | None = None,
    source: str = "smartthings-cli",
) -> dict[str, Any]:
    normalized = normalize_devices(devices)
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "schemaVersion": 1,
        "generatedAt": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source,
        "readOnly": True,
        "summary": summary(normalized),
        "devices": normalized,
    }


def _csv_row(device: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": device.get("label"),
        "location": device.get("location"),
        "room": device.get("room"),
        "health": device.get("health"),
        "health_last_updated": device.get("healthLastUpdated"),
        "firmware_status": device.get("firmwareStatus"),
        "firmware_version": device.get("firmwareVersion"),
        "firmware_timestamp": device.get("firmwareTimestamp"),
        "available_version": device.get("availableVersion"),
        "update_available": device.get("updateAvailable"),
        "manufacturer_code": device.get("manufacturerCode"),
        "manufacturer_id": device.get("manufacturerId"),
        "product_type": device.get("productType"),
        "product_id": device.get("productId"),
        "zwave_node_id": device.get("zwaveNodeId"),
        "network_security_level": device.get("networkSecurityLevel"),
        "executing_locally": device.get("executingLocally"),
        "smartthings_device_id": device.get("smartthingsDeviceId"),
        "driver_id": device.get("driverId"),
        "hub_id": device.get("hubId"),
        "device_name": device.get("deviceName"),
    }


def write_csv(inventory: dict[str, Any], destination: TextIO) -> None:
    writer = csv.DictWriter(destination, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for device in inventory.get("devices") or []:
        writer.writerow(_csv_row(device))


def _atomic_write(path: Path, writer: Any, *, newline: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline=newline,
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            writer(temporary)
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def write_inventory_files(
    inventory: dict[str, Any],
    output_directory: Path,
    *,
    prefix: str = "zwave-firmware-inventory",
    generated_at: datetime | None = None,
) -> tuple[Path, Path]:
    timestamp = generated_at or datetime.now()
    filename_timestamp = timestamp.strftime("%Y%m%d-%H%M%S")
    stem = f"{prefix}-{filename_timestamp}"
    csv_path = output_directory / f"{stem}.csv"
    json_path = output_directory / f"{stem}.json"
    collision_number = 2
    while csv_path.exists() or json_path.exists():
        csv_path = output_directory / f"{stem}-{collision_number}.csv"
        json_path = output_directory / f"{stem}-{collision_number}.json"
        collision_number += 1

    _atomic_write(csv_path, lambda destination: write_csv(inventory, destination), newline="")
    _atomic_write(
        json_path,
        lambda destination: json.dump(inventory, destination, indent=2, ensure_ascii=False),
    )
    return csv_path.resolve(), json_path.resolve()
