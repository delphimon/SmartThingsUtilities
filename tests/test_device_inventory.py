from __future__ import annotations

from datetime import datetime, timezone
import csv
import copy
import json
from pathlib import Path
import tempfile
import unittest

from smartthings_utilities.device_inventory import (
    CatalogLookupError,
    build_inventory,
    lookup_zwave_updates,
    write_inventory_files,
)


FIXTURE = Path(__file__).parent / "fixtures" / "all_devices.json"


class DeviceInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.devices = json.loads(FIXTURE.read_text(encoding="utf-8"))

    @staticmethod
    def loader(url: str, **kwargs):
        if "firmware.zwave-js.io" in url:
            return []
        return []

    def test_enriches_protocols_names_and_latest_firmware_without_guessing(self) -> None:
        inventory = build_inventory(
            self.devices, source="fixture", loader=self.loader,
            generated_at=datetime(2026, 8, 11, 12, tzinfo=timezone.utc),
        )
        by_label = {device["label"]: device for device in inventory["devices"]}
        zooz = by_label["Zooz Dimmer"]
        self.assertEqual(zooz["resolvedDeviceName"], "Zooz ZEN22 — Dimmer Paddle Switch")
        self.assertEqual(zooz["deviceNameStatus"], "EXACT_FINGERPRINT_MATCH")
        self.assertEqual(zooz["manufacturer"], "Zooz")
        self.assertEqual(zooz["manufacturerStatus"], "EXACT_MANUFACTURER_ID_MATCH")
        self.assertEqual(zooz["model"], "ZEN22")
        self.assertEqual(zooz["reportedManufacturer"], "027A-B112-1F1C")
        self.assertEqual(zooz["reportedModel"], "B112-1F1C")
        self.assertEqual(zooz["latestFirmware"], "4.4.1")
        self.assertEqual(zooz["latestFirmwareStatus"], "CATALOG_LATEST_INCOMPATIBLE_BRANCH")
        self.assertEqual(
            zooz["updateStatus"], "NOT_COMPATIBLE_WITH_CURRENT_FIRMWARE_BRANCH"
        )

        zigbee = by_label["Aqara Weather"]
        self.assertEqual(zigbee["resolvedDeviceName"], "LUMI lumi.weather")
        self.assertEqual(zigbee["latestFirmwareStatus"], "NOT_IN_CATALOG")
        self.assertIsNone(zigbee["latestFirmware"])

        lan = by_label["Kasa Plug"]
        self.assertEqual(lan["resolvedDeviceName"], "TP-Link | Kasa Home KP115(US)")
        self.assertEqual(lan["latestFirmwareStatus"], "NO_SUPPORTED_PUBLIC_CATALOG")
        self.assertEqual(inventory["summary"]["byProtocol"], {"LAN": 1, "ZIGBEE": 1, "ZWAVE": 1})

    def test_failed_batch_is_split_so_valid_devices_still_return(self) -> None:
        first = copy.deepcopy(self.devices[0])
        second = copy.deepcopy(first)
        second["components"][0]["capabilities"][0]["status"]["currentVersion"]["value"] = "4.0"
        batch_sizes = []

        def loader(url: str, **kwargs):
            devices = kwargs["payload"]["devices"]
            batch_sizes.append(len(devices))
            if len(devices) > 1:
                raise CatalogLookupError("synthetic batch rejection")
            device = devices[0]
            if device["firmwareVersion"] != "4.0.0":
                return []
            return [{**device, "updates": [{
                "version": "4.4.1", "normalizedVersion": "4.4.1",
                "channel": "stable", "downgrade": False, "files": [],
            }]}]

        updates, error = lookup_zwave_updates(
            [first, second], cache_dir=Path("/unused"), offline=False, loader=loader
        )
        self.assertEqual(batch_sizes, [2, 1, 1])
        self.assertIsNone(error)
        self.assertEqual(updates[("0x027a", "0xb112", "0x1f1c", "4.0.0")]["latest"], "4.4.1")

    def test_model_family_firmware_with_other_fingerprint_is_not_offered(self) -> None:
        device = copy.deepcopy(self.devices[0])
        device["deviceManufacturerCode"] = "027A-B111-1E1C"
        device["deviceModel"] = "B111-1E1C"
        device["zwave"]["productType"] = 0xB111
        device["zwave"]["productId"] = 0x1E1C
        inventory = build_inventory([device], source="fixture", loader=self.loader)
        result = inventory["devices"][0]
        self.assertEqual(result["model"], "ZEN21")
        self.assertEqual(result["latestFirmware"], "4.5.1")
        self.assertEqual(
            result["latestFirmwareStatus"],
            "CATALOG_LATEST_DIFFERENT_HARDWARE_FINGERPRINT",
        )
        self.assertEqual(
            result["updateStatus"], "NOT_COMPATIBLE_WITH_DEVICE_FINGERPRINT"
        )

    def test_writes_csv_and_json(self) -> None:
        inventory = build_inventory(self.devices, source="fixture", loader=self.loader)
        with tempfile.TemporaryDirectory() as directory:
            csv_path, json_path = write_inventory_files(
                inventory, Path(directory), generated_at=datetime(2026, 8, 11, 13, 14, 15)
            )
            self.assertEqual(csv_path.name, "device-inventory-20260811-131415.csv")
            self.assertTrue(json_path.is_file())
            with csv_path.open(newline="", encoding="utf-8") as source:
                rows = {row["label"]: row for row in csv.DictReader(source)}
            zooz = rows["Zooz Dimmer"]
            self.assertEqual(zooz["manufacturer"], "Zooz")
            self.assertEqual(zooz["model"], "ZEN22")
            self.assertEqual(zooz["resolved_device_name"], "Zooz ZEN22 — Dimmer Paddle Switch")
            self.assertEqual(zooz["manufacturer_code"], "027A-B112-1F1C")


if __name__ == "__main__":
    unittest.main()
