"""Protocol-neutral device inventory with conservative catalog enrichment."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Iterable, TextIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .zwave_inventory import _firmware, _hex16, _manufacturer_code, _atomic_write


ZWAVE_FIRMWARE_URL = "https://firmware.zwave-js.io/api/v4/updates"
ZIGBEE_OTA_URL = "https://raw.githubusercontent.com/Koenkk/zigbee-OTA/master/index.json"
CATALOG_URL = "https://github.com/SmartThingsCommunity/SmartThingsEdgeDrivers"
USER_AGENT = "SmartThingsUtilities/0.2.2 (+https://github.com/delphimon/SmartThingsUtilities)"

CSV_FIELDS = [
    "label", "protocol", "resolved_device_name", "device_name_status",
    "manufacturer", "manufacturer_status", "model", "model_status",
    "reported_manufacturer", "reported_model", "manufacturer_code", "manufacturer_id",
    "product_type", "product_id", "matter_vendor_id", "matter_product_id",
    "current_firmware", "current_firmware_status", "latest_firmware",
    "latest_firmware_status", "update_status", "firmware_source",
    "firmware_source_url", "health", "location", "room", "network_id",
    "smartthings_device_id", "driver_id", "hub_id", "executing_locally",
]


class CatalogLookupError(RuntimeError):
    """A catalog was unavailable or returned unusable data."""


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _bundled_catalog() -> dict[str, Any]:
    return _read_json(Path(__file__).parent / "data" / "device_catalog.json")


def _protocol(device: dict[str, Any]) -> str:
    value = device.get("type")
    return value.upper() if isinstance(value, str) and value else "UNKNOWN"


def _protocol_block(device: dict[str, Any], protocol: str) -> dict[str, Any]:
    value = device.get(protocol.casefold())
    return value if isinstance(value, dict) else {}


def _catalog_name(device: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    protocol = _protocol(device)
    candidates: list[str] = []
    resolved_manufacturer: str | None = None
    resolved_model: str | None = None
    manufacturer_status = "UNKNOWN"
    model_status = "UNKNOWN"
    if protocol != "ZWAVE":
        if isinstance(device.get("deviceManufacturerCode"), str):
            resolved_manufacturer = device["deviceManufacturerCode"]
            manufacturer_status = "SMARTTHINGS_METADATA"
        if isinstance(device.get("deviceModel"), str):
            resolved_model = device["deviceModel"]
            model_status = "SMARTTHINGS_METADATA"
    if protocol == "ZWAVE":
        block = _protocol_block(device, protocol)
        code = _manufacturer_code(device, block)
        manufacturer_id = block.get("manufacturerId")
        if isinstance(manufacturer_id, int) and not isinstance(manufacturer_id, bool):
            resolved_manufacturer = catalog.get("zwaveManufacturers", {}).get(f"{manufacturer_id:04X}")
            if resolved_manufacturer:
                manufacturer_status = "EXACT_MANUFACTURER_ID_MATCH"
        records = catalog.get("zwaveJs", {}).get(code, []) if code else []
        identities = {
            (
                str(record.get("manufacturer") or "").strip(),
                str(record.get("model") or "").strip(),
                str(record.get("description") or "").strip(),
            )
            for record in records if isinstance(record, dict)
        }
        identities.discard(("", "", ""))
        if len(identities) == 1:
            manufacturer, model, description = identities.pop()
            resolved_manufacturer = manufacturer or resolved_manufacturer
            resolved_model = model or None
            display = " ".join(value for value in (resolved_manufacturer, resolved_model) if value)
            if description:
                display = f"{display} — {description}"
            return {
                "name": display, "status": "EXACT_FINGERPRINT_MATCH",
                "source": "ZWAVE_JS_CONFIG_DATABASE",
                "sourceUrl": "https://github.com/zwave-js/zwave-js/tree/master/packages/config/config/devices",
                "candidates": [display], "manufacturer": resolved_manufacturer,
                "manufacturerStatus": "EXACT_MANUFACTURER_ID_MATCH",
                "model": resolved_model, "modelStatus": "EXACT_FINGERPRINT_MATCH",
            }
        if code:
            candidates = catalog.get("zwave", {}).get(code, [])
    elif protocol == "ZIGBEE":
        manufacturer, model = device.get("deviceManufacturerCode"), device.get("deviceModel")
        if isinstance(manufacturer, str) and isinstance(model, str):
            key = f"{manufacturer.casefold()}\0{model.casefold()}"
            candidates = catalog.get("zigbee", {}).get(key, [])
    elif protocol == "MATTER":
        block = _protocol_block(device, protocol)
        vendor_id, product_id = block.get("vendorId"), block.get("productId")
        if isinstance(vendor_id, int) and isinstance(product_id, int):
            candidates = catalog.get("matter", {}).get(f"{vendor_id:04X}-{product_id:04X}", [])

    unique = sorted({str(item).strip() for item in candidates if str(item).strip()})
    if len(unique) == 1:
        return {
            "name": unique[0], "status": "EXACT_FINGERPRINT_MATCH",
            "source": "SMARTTHINGS_EDGE_FINGERPRINTS", "sourceUrl": CATALOG_URL,
            "candidates": unique, "manufacturer": resolved_manufacturer,
            "manufacturerStatus": manufacturer_status, "model": resolved_model or unique[0],
            "modelStatus": model_status if resolved_model else "EXACT_FINGERPRINT_MATCH",
        }

    manufacturer = resolved_manufacturer or device.get("deviceManufacturerCode")
    model = device.get("deviceModel")
    if protocol == "ZWAVE":
        # SmartThings commonly puts the numeric fingerprint in
        # deviceManufacturerCode. It is an identifier, never a company name.
        if resolved_manufacturer:
            manufacturer = resolved_manufacturer
        elif isinstance(manufacturer, str) and re.fullmatch(
            r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}", manufacturer
        ):
            manufacturer = None
    parts = [value.strip() for value in (manufacturer, model) if isinstance(value, str) and value.strip()]
    if parts:
        return {
            "name": " ".join(dict.fromkeys(parts)),
            "status": "CATALOG_AMBIGUOUS" if len(unique) > 1 else "SMARTTHINGS_METADATA",
            "source": "SMARTTHINGS_DEVICE_METADATA", "sourceUrl": None,
            "candidates": unique, "manufacturer": manufacturer,
            "manufacturerStatus": manufacturer_status if resolved_manufacturer else "SMARTTHINGS_METADATA",
            "model": model, "modelStatus": "SMARTTHINGS_METADATA" if model else "UNKNOWN",
        }
    return {
        "name": None, "status": "CATALOG_AMBIGUOUS" if len(unique) > 1 else "UNKNOWN",
        "source": None, "sourceUrl": CATALOG_URL if unique else None, "candidates": unique,
        "manufacturer": resolved_manufacturer, "manufacturerStatus": manufacturer_status,
        "model": None, "modelStatus": "UNKNOWN",
    }


def _cache_path(cache_dir: Path, method: str, url: str, body: bytes | None) -> Path:
    digest = hashlib.sha256(method.encode() + b"\0" + url.encode() + b"\0" + (body or b"")).hexdigest()
    return cache_dir / f"{digest}.json"


def fetch_json(
    url: str,
    *,
    cache_dir: Path,
    offline: bool = False,
    payload: Any = None,
    timeout: float = 20.0,
) -> Any:
    body = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    method = "POST" if body is not None else "GET"
    cache = _cache_path(cache_dir, method, url, body)
    if offline:
        if cache.is_file():
            return _read_json(cache)
        raise CatalogLookupError(f"offline and no cached response exists for {url}")

    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result), encoding="utf-8")
        return result
    except HTTPError as error:
        if cache.is_file():
            return _read_json(cache)
        details = error.read().decode("utf-8", errors="replace").strip()
        suffix = f": {details}" if details else ""
        raise CatalogLookupError(f"{url}: HTTP {error.code}{suffix}") from error
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        if cache.is_file():
            return _read_json(cache)
        raise CatalogLookupError(f"{url}: {error}") from error


def _zwave_key(device: dict[str, Any]) -> tuple[str, str, str, str] | None:
    block = _protocol_block(device, "ZWAVE")
    values = (block.get("manufacturerId"), block.get("productType"), block.get("productId"))
    firmware = _firmware(device)["version"]
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    if firmware in (None, ""):
        return None
    firmware_text = str(firmware)
    if re.fullmatch(r"\d{1,3}\.\d{1,3}", firmware_text):
        firmware_text += ".0"
    return tuple([*(f"0x{value:04x}" for value in values), firmware_text])  # type: ignore[return-value]


def _version_key(value: Any) -> tuple[int, ...] | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return (value,)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if re.fullmatch(r"[0-9A-Fa-f]{8}", text):
        return (int(text, 16),)
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?", text)
    if match:
        return tuple(int(part or 0) for part in match.groups())
    return None


def _update_status(current: Any, latest: Any, smartthings_value: Any = None) -> str:
    if isinstance(smartthings_value, bool):
        return "UPDATE_AVAILABLE" if smartthings_value else "NO_UPDATE_REPORTED"
    current_key, latest_key = _version_key(current), _version_key(latest)
    if latest in (None, ""):
        return "UNKNOWN"
    if current_key is None or latest_key is None:
        return "UNKNOWN_COMPARISON"
    return "UPDATE_AVAILABLE" if latest_key > current_key else "CURRENT_OR_NEWER"


def lookup_zwave_updates(
    devices: Iterable[dict[str, Any]],
    *, cache_dir: Path, offline: bool,
    loader: Callable[..., Any] = fetch_json,
) -> tuple[dict[tuple[str, str, str, str], dict[str, Any]], str | None]:
    keys = sorted({_zwave_key(device) for device in devices if _protocol(device) == "ZWAVE"} - {None})
    if not keys:
        return {}, None
    failures: list[str] = []

    def query(batch: list[tuple[str, str, str, str]]) -> list[Any]:
        payload = {"region": "usa", "devices": [
            {"manufacturerId": key[0], "productType": key[1], "productId": key[2], "firmwareVersion": key[3]}
            for key in batch
        ]}
        try:
            response = loader(
                ZWAVE_FIRMWARE_URL, cache_dir=cache_dir, offline=offline, payload=payload
            )
            return response if isinstance(response, list) else []
        except CatalogLookupError as error:
            if len(batch) > 1 and not offline:
                midpoint = len(batch) // 2
                return query(batch[:midpoint]) + query(batch[midpoint:])
            failures.append(str(error))
            return []

    response = query(keys)
    indexed: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in response if isinstance(response, list) else []:
        if not isinstance(item, dict):
            continue
        key = tuple(str(item.get(field, "")).casefold() for field in (
            "manufacturerId", "productType", "productId", "firmwareVersion"
        ))
        updates = [update for update in item.get("updates", []) if isinstance(update, dict)
                   and update.get("channel") == "stable" and not update.get("downgrade")]
        updates.sort(key=lambda update: _version_key(update.get("normalizedVersion")) or ())
        indexed[key] = {"known": True, "latest": updates[-1].get("version") if updates else None}
    error = "; ".join(dict.fromkeys(failures)) if failures else None
    return indexed, error


def _bundled_zwave_firmware(
    device: dict[str, Any], catalog: dict[str, Any]
) -> dict[str, Any] | None:
    block = _protocol_block(device, "ZWAVE")
    code = _manufacturer_code(device, block)
    current = _firmware(device)["version"]
    current_key = _version_key(current)
    if not code:
        return None
    records = catalog.get("zwaveFirmware", {}).get(code, [])
    different_fingerprint = False
    if not isinstance(records, list) or not records:
        models = {
            str(record.get("model") or "").strip().casefold()
            for record in catalog.get("zwaveJs", {}).get(code, [])
            if isinstance(record, dict) and record.get("model")
        }
        manufacturer_id = block.get("manufacturerId")
        if len(models) != 1 or not isinstance(manufacturer_id, int):
            return None
        model = models.pop()
        records = catalog.get("zwaveFirmwareByModel", {}).get(
            f"{manufacturer_id:04X}\0{model}", []
        )
        if not isinstance(records, list) or not records:
            return None
        different_fingerprint = True

    compatible: list[dict[str, Any]] = []
    all_updates: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        updates = [
            update for update in record.get("updates", [])
            if isinstance(update, dict)
            and update.get("channel", "stable") == "stable"
            and update.get("region") in (None, "usa")
            and isinstance(update.get("version"), str)
        ]
        all_updates.extend(updates)
        minimum = _version_key(record.get("minVersion"))
        maximum = _version_key(record.get("maxVersion"))
        if (
            not different_fingerprint
            and current_key is not None
            and minimum is not None
            and maximum is not None
            and minimum <= current_key <= maximum
        ):
            compatible.extend(updates)

    def latest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not items:
            return None
        return max(items, key=lambda item: _version_key(item.get("version")) or ())

    if compatible:
        selected = latest(compatible)
        return {
            "compatible": True,
            "differentFingerprint": different_fingerprint,
            "latest": selected.get("version") if selected else None,
        }
    selected = latest(all_updates)
    return {
        "compatible": None if current_key is None else False,
        "differentFingerprint": different_fingerprint,
        "latest": selected.get("version") if selected else None,
    }


def lookup_zigbee_updates(
    devices: Iterable[dict[str, Any]],
    *, cache_dir: Path, offline: bool,
    loader: Callable[..., Any] = fetch_json,
) -> tuple[dict[tuple[str, str], dict[str, Any]], str | None]:
    targets: dict[tuple[str, str], int | None] = {}
    for device in devices:
        if _protocol(device) != "ZIGBEE" or not device.get("deviceModel"):
            continue
        key = (
            str(device.get("deviceManufacturerCode") or "").casefold(),
            str(device.get("deviceModel") or "").casefold(),
        )
        parsed = _version_key(_firmware(device)["version"])
        targets[key] = parsed[0] if parsed and len(parsed) == 1 else None
    if not targets:
        return {}, None
    try:
        response = loader(ZIGBEE_OTA_URL, cache_dir=cache_dir, offline=offline)
    except CatalogLookupError as error:
        return {}, str(error)
    matches: dict[tuple[str, str], list[dict[str, Any]]] = {key: [] for key in targets}
    for item in response if isinstance(response, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("modelId"), str):
            continue
        model = item["modelId"].casefold()
        for manufacturer, target_model in targets:
            if model != target_model:
                continue
            allowed = item.get("manufacturerName")
            if isinstance(allowed, list) and manufacturer not in {
                str(value).casefold() for value in allowed
            }:
                continue
            # SmartThings does not expose the Zigbee OTA hardware version. A
            # hardware-gated image therefore cannot be called compatible.
            if "hardwareVersionMin" in item or "hardwareVersionMax" in item:
                continue
            current = targets[(manufacturer, target_model)]
            if isinstance(item.get("minFileVersion"), int) and (
                current is None or current < item["minFileVersion"]
            ):
                continue
            if isinstance(item.get("maxFileVersion"), int) and (
                current is None or current > item["maxFileVersion"]
            ):
                continue
            matches[(manufacturer, target_model)].append(item)
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for key, items in matches.items():
        if not items:
            continue
        identities = {
            (item.get("manufacturerCode"), item.get("imageType")) for item in items
            if isinstance(item.get("manufacturerCode"), int) and isinstance(item.get("imageType"), int)
        }
        versions = {item.get("fileVersion") for item in items if isinstance(item.get("fileVersion"), int)}
        # Without the OTA manufacturer code and image type from SmartThings,
        # two candidate image identities are ambiguous even if the model text matches.
        if versions and len(identities) == 1:
            latest = max(versions)
            result[key] = {"known": True, "latest": f"0x{latest:08X}", "raw": latest}
    return result, None


def normalize_device(
    device: dict[str, Any], catalog: dict[str, Any],
    zwave_updates: dict[tuple[str, str, str, str], dict[str, Any]],
    zigbee_updates: dict[tuple[str, str], dict[str, Any]],
    lookup_errors: dict[str, str],
) -> dict[str, Any]:
    protocol = _protocol(device)
    block = _protocol_block(device, protocol)
    health = device.get("healthState") if isinstance(device.get("healthState"), dict) else {}
    firmware = _firmware(device)
    name = _catalog_name(device, catalog)
    current, latest = firmware["version"], firmware["availableVersion"]
    latest_status = "SMARTTHINGS_REPORTED" if latest not in (None, "") else "UNKNOWN"
    source = "SMARTTHINGS_FIRMWARE_CAPABILITY" if latest_status != "UNKNOWN" else None
    source_url = "https://developer.smartthings.com/docs/devices/capabilities/capabilities-reference#firmwareUpdate" if source else None
    update_status_override: str | None = None

    if latest in (None, "") and protocol == "ZWAVE":
        key = _zwave_key(device)
        match = zwave_updates.get(tuple(part.casefold() for part in key)) if key else None
        bundled = _bundled_zwave_firmware(device, catalog)
        if match and match.get("latest"):
            latest, latest_status = match["latest"], "CATALOG_UPDATE_AVAILABLE"
            source, source_url = "ZWAVE_JS_FIRMWARE_UPDATE_SERVICE", ZWAVE_FIRMWARE_URL
        elif match:
            latest_status, source, source_url = "CATALOG_NO_NEWER_VERSION", "ZWAVE_JS_FIRMWARE_UPDATE_SERVICE", ZWAVE_FIRMWARE_URL
        elif bundled and bundled.get("latest") and bundled.get("compatible"):
            latest, latest_status = bundled["latest"], "CATALOG_LATEST"
            source = "BUNDLED_ZWAVE_JS_FIRMWARE_CATALOG"
            source_url = "https://github.com/zwave-js/firmware-updates"
        elif bundled and bundled.get("latest") and bundled.get("differentFingerprint"):
            latest = bundled["latest"]
            latest_status = "CATALOG_LATEST_DIFFERENT_HARDWARE_FINGERPRINT"
            update_status_override = "NOT_COMPATIBLE_WITH_DEVICE_FINGERPRINT"
            source = "BUNDLED_ZWAVE_JS_FIRMWARE_CATALOG"
            source_url = "https://github.com/zwave-js/firmware-updates"
        elif bundled and bundled.get("latest") and bundled.get("compatible") is None:
            latest = bundled["latest"]
            latest_status = "CATALOG_LATEST_COMPATIBILITY_UNKNOWN"
            update_status_override = "CURRENT_FIRMWARE_REQUIRED_FOR_COMPATIBILITY"
            source = "BUNDLED_ZWAVE_JS_FIRMWARE_CATALOG"
            source_url = "https://github.com/zwave-js/firmware-updates"
        elif bundled and bundled.get("latest"):
            latest = bundled["latest"]
            latest_status = "CATALOG_LATEST_INCOMPATIBLE_BRANCH"
            update_status_override = "NOT_COMPATIBLE_WITH_CURRENT_FIRMWARE_BRANCH"
            source = "BUNDLED_ZWAVE_JS_FIRMWARE_CATALOG"
            source_url = "https://github.com/zwave-js/firmware-updates"
        elif "zwave" in lookup_errors:
            latest_status = (
                "ONLINE_LOOKUP_SKIPPED_NOT_IN_BUNDLED_CATALOG"
                if lookup_errors["zwave"].startswith("offline and no cached response")
                else "LOOKUP_FAILED"
            )
        elif key is None:
            latest_status = "CURRENT_VERSION_OR_FINGERPRINT_REQUIRED"
        else:
            latest_status = "NOT_IN_CATALOG"
    elif latest in (None, "") and protocol == "ZIGBEE":
        key = (str(device.get("deviceManufacturerCode") or "").casefold(), str(device.get("deviceModel") or "").casefold())
        match = zigbee_updates.get(key)
        if match:
            latest, latest_status = match["latest"], "CATALOG_LATEST"
            source, source_url = "KOENKK_ZIGBEE_OTA_INDEX", ZIGBEE_OTA_URL
        elif "zigbee" in lookup_errors:
            latest_status = "LOOKUP_FAILED"
        elif not key[1]:
            latest_status = "MODEL_IDENTIFIER_REQUIRED"
        else:
            latest_status = "NOT_IN_CATALOG"
    elif latest in (None, "") and protocol not in {"ZWAVE", "ZIGBEE"}:
        latest_status = "NO_SUPPORTED_PUBLIC_CATALOG"

    zwave = _protocol_block(device, "ZWAVE")
    matter = _protocol_block(device, "MATTER")
    return {
        "label": device.get("label"), "protocol": protocol,
        "resolvedDeviceName": name["name"], "deviceNameStatus": name["status"],
        "deviceNameSource": name["source"], "deviceNameSourceUrl": name["sourceUrl"],
        "catalogNameCandidates": name["candidates"],
        "manufacturer": name["manufacturer"], "manufacturerStatus": name["manufacturerStatus"],
        "model": name["model"], "modelStatus": name["modelStatus"],
        "reportedManufacturer": device.get("deviceManufacturerCode"),
        "reportedModel": device.get("deviceModel"),
        "manufacturerCode": _manufacturer_code(device, zwave) if protocol == "ZWAVE" else device.get("deviceManufacturerCode"),
        "manufacturerId": _hex16(zwave.get("manufacturerId")),
        "productType": _hex16(zwave.get("productType")), "productId": _hex16(zwave.get("productId")),
        "matterVendorId": _hex16(matter.get("vendorId")), "matterProductId": _hex16(matter.get("productId")),
        "currentFirmware": current, "currentFirmwareStatus": firmware["status"],
        "latestFirmware": latest, "latestFirmwareStatus": latest_status,
        "updateStatus": update_status_override or _update_status(
            current, latest, firmware["updateAvailable"]
        ),
        "firmwareSource": source, "firmwareSourceUrl": source_url,
        "health": health.get("state"), "healthLastUpdated": health.get("lastUpdatedDate"),
        "location": device.get("location"), "room": device.get("room"),
        "networkId": block.get("networkId"), "smartthingsDeviceId": device.get("deviceId"),
        "driverId": block.get("driverId"), "hubId": block.get("hubId"),
        "executingLocally": block.get("executingLocally"), "smartthingsDeviceName": device.get("name"),
    }


def build_inventory(
    devices: Iterable[dict[str, Any]], *, source: str = "smartthings-cli",
    generated_at: datetime | None = None, cache_dir: Path | None = None,
    offline: bool = False, loader: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    raw = [device for device in devices if isinstance(device, dict)]
    cache = cache_dir or Path.home() / ".cache" / "smartthings-utilities"
    zwave, zwave_error = lookup_zwave_updates(raw, cache_dir=cache, offline=offline, loader=loader)
    zigbee, zigbee_error = lookup_zigbee_updates(raw, cache_dir=cache, offline=offline, loader=loader)
    errors = {key: value for key, value in (("zwave", zwave_error), ("zigbee", zigbee_error)) if value}
    catalog = _bundled_catalog()
    normalized = [normalize_device(device, catalog, zwave, zigbee, errors) for device in raw]
    normalized.sort(key=lambda item: (
        str(item.get("location") or "").casefold(), str(item.get("room") or "").casefold(),
        str(item.get("label") or "").casefold(), str(item.get("smartthingsDeviceId") or ""),
    ))
    protocol_counts: dict[str, int] = {}
    updates = 0
    for device in normalized:
        protocol_counts[device["protocol"]] = protocol_counts.get(device["protocol"], 0) + 1
        updates += device["updateStatus"] == "UPDATE_AVAILABLE"
    timestamp = generated_at or datetime.now(timezone.utc)
    return {
        "schemaVersion": 2, "generatedAt": timestamp.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": source, "readOnly": True,
        "summary": {"totalDevices": len(normalized), "byProtocol": dict(sorted(protocol_counts.items())), "updatesAvailable": updates},
        "catalogs": {
            "deviceNames": {
                key: catalog.get(key) for key in (
                    "source", "sourceRevision", "zwaveJsSource",
                    "zwaveJsSourceRevision", "firmwareUpdatesSource",
                    "firmwareUpdatesSourceRevision", "generatedAt",
                )
            },
            "zwaveFirmware": ZWAVE_FIRMWARE_URL, "zigbeeFirmware": ZIGBEE_OTA_URL,
        },
        "lookupWarnings": errors, "devices": normalized,
    }


def _csv_row(device: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "resolved_device_name": "resolvedDeviceName", "device_name_status": "deviceNameStatus",
        "manufacturer_status": "manufacturerStatus", "model_status": "modelStatus",
        "reported_manufacturer": "reportedManufacturer", "reported_model": "reportedModel",
        "manufacturer_code": "manufacturerCode", "manufacturer_id": "manufacturerId",
        "product_type": "productType", "product_id": "productId",
        "matter_vendor_id": "matterVendorId", "matter_product_id": "matterProductId",
        "current_firmware": "currentFirmware", "current_firmware_status": "currentFirmwareStatus",
        "latest_firmware": "latestFirmware", "latest_firmware_status": "latestFirmwareStatus",
        "update_status": "updateStatus", "firmware_source": "firmwareSource",
        "firmware_source_url": "firmwareSourceUrl", "network_id": "networkId",
        "smartthings_device_id": "smartthingsDeviceId", "driver_id": "driverId",
        "hub_id": "hubId", "executing_locally": "executingLocally",
    }
    return {field: device.get(mapping.get(field, field)) for field in CSV_FIELDS}


def write_csv(inventory: dict[str, Any], destination: TextIO) -> None:
    writer = csv.DictWriter(destination, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for device in inventory.get("devices", []):
        writer.writerow(_csv_row(device))


def write_inventory_files(
    inventory: dict[str, Any], output_directory: Path, *,
    generated_at: datetime | None = None,
) -> tuple[Path, Path]:
    timestamp = generated_at or datetime.now()
    stem = f"device-inventory-{timestamp.strftime('%Y%m%d-%H%M%S')}"
    csv_path, json_path = output_directory / f"{stem}.csv", output_directory / f"{stem}.json"
    suffix = 2
    while csv_path.exists() or json_path.exists():
        csv_path, json_path = output_directory / f"{stem}-{suffix}.csv", output_directory / f"{stem}-{suffix}.json"
        suffix += 1
    _atomic_write(csv_path, lambda target: write_csv(inventory, target), newline="")
    _atomic_write(json_path, lambda target: json.dump(inventory, target, indent=2, ensure_ascii=False))
    return csv_path.resolve(), json_path.resolve()
