from __future__ import annotations

import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

from smartthings_utilities.zwave_inventory import (
    FIRMWARE_CAPABILITY_NO_VALUE,
    FIRMWARE_NOT_EXPOSED,
    FIRMWARE_REPORTED,
    build_inventory,
    normalize_devices,
    write_csv,
    write_inventory_files,
)


FIXTURE = Path(__file__).parent / "fixtures" / "devices.json"


class ZWaveInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with FIXTURE.open(encoding="utf-8") as source:
            cls.devices = json.load(source)

    def test_normalizes_firmware_status_and_exact_fingerprint(self) -> None:
        normalized = normalize_devices(self.devices)
        by_label = {device["label"]: device for device in normalized}

        reported = by_label["Reported Switch"]
        self.assertEqual(reported["firmwareStatus"], FIRMWARE_REPORTED)
        self.assertEqual(reported["firmwareVersion"], "3.40")
        self.assertEqual(reported["manufacturerCode"], "027A-A000-A002")
        self.assertEqual(reported["manufacturerId"], "0x027A")
        self.assertEqual(reported["productType"], "0xA000")
        self.assertEqual(reported["productId"], "0xA002")

        no_value = by_label["Capability Without Value"]
        self.assertEqual(no_value["firmwareStatus"], FIRMWARE_CAPABILITY_NO_VALUE)
        self.assertIsNone(no_value["firmwareVersion"])
        self.assertEqual(no_value["manufacturerCode"], "014A-0001-0002")

        not_exposed = by_label["No Firmware Capability"]
        self.assertEqual(not_exposed["firmwareStatus"], FIRMWARE_NOT_EXPOSED)

    def test_builds_summary_without_inventing_missing_versions(self) -> None:
        inventory = build_inventory(
            self.devices,
            generated_at=datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc),
            source="fixture",
        )
        self.assertEqual(
            inventory["summary"],
            {
                "totalDevices": 3,
                FIRMWARE_REPORTED: 1,
                FIRMWARE_CAPABILITY_NO_VALUE: 1,
                FIRMWARE_NOT_EXPOSED: 1,
            },
        )
        self.assertTrue(inventory["readOnly"])
        self.assertEqual(inventory["generatedAt"], "2026-08-11T12:00:00Z")

    def test_writes_csv_with_one_row_per_device(self) -> None:
        inventory = build_inventory(self.devices, source="fixture")
        output = io.StringIO(newline="")
        write_csv(inventory, output)
        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {row["firmware_status"] for row in rows},
            {FIRMWARE_REPORTED, FIRMWARE_CAPABILITY_NO_VALUE, FIRMWARE_NOT_EXPOSED},
        )

    def test_writes_timestamped_csv_and_json_atomically(self) -> None:
        inventory = build_inventory(self.devices, source="fixture")
        generated_at = datetime(2026, 8, 11, 13, 14, 15)
        with tempfile.TemporaryDirectory() as temporary_directory:
            csv_path, json_path = write_inventory_files(
                inventory,
                Path(temporary_directory),
                generated_at=generated_at,
            )
            self.assertEqual(csv_path.name, "zwave-firmware-inventory-20260811-131415.csv")
            self.assertEqual(json_path.name, "zwave-firmware-inventory-20260811-131415.json")
            self.assertTrue(csv_path.is_file())
            self.assertTrue(json_path.is_file())

            second_csv_path, second_json_path = write_inventory_files(
                inventory,
                Path(temporary_directory),
                generated_at=generated_at,
            )
            self.assertEqual(second_csv_path.name, "zwave-firmware-inventory-20260811-131415-2.csv")
            self.assertEqual(second_json_path.name, "zwave-firmware-inventory-20260811-131415-2.json")


if __name__ == "__main__":
    unittest.main()
