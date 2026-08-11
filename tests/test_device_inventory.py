from __future__ import annotations

from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import tempfile
import unittest

from smartthings_utilities.device_inventory import build_inventory, write_inventory_files


FIXTURE = Path(__file__).parent / "fixtures" / "all_devices.json"


class DeviceInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.devices = json.loads(FIXTURE.read_text(encoding="utf-8"))

    @staticmethod
    def loader(url: str, **kwargs):
        if "firmware.zwave-js.io" in url:
            return [{
                "manufacturerId": "0x027a", "productType": "0xb112",
                "productId": "0x1f1c", "firmwareVersion": "20.15",
                "updates": [{
                    "version": "20.16", "normalizedVersion": "20.16.0",
                    "channel": "stable", "downgrade": False, "files": [],
                }],
            }]
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
        self.assertEqual(zooz["latestFirmware"], "20.16")
        self.assertEqual(zooz["updateStatus"], "UPDATE_AVAILABLE")

        zigbee = by_label["Aqara Weather"]
        self.assertEqual(zigbee["resolvedDeviceName"], "LUMI lumi.weather")
        self.assertEqual(zigbee["latestFirmwareStatus"], "NOT_IN_CATALOG")
        self.assertIsNone(zigbee["latestFirmware"])

        lan = by_label["Kasa Plug"]
        self.assertEqual(lan["resolvedDeviceName"], "TP-Link | Kasa Home KP115(US)")
        self.assertEqual(lan["latestFirmwareStatus"], "NO_SUPPORTED_PUBLIC_CATALOG")
        self.assertEqual(inventory["summary"]["byProtocol"], {"LAN": 1, "ZIGBEE": 1, "ZWAVE": 1})

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
