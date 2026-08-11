from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from smartthings_utilities.cli import main


FIXTURE = Path(__file__).parent / "fixtures" / "devices.json"


class CLITests(unittest.TestCase):
    def test_offline_inventory_is_one_command_and_writes_both_formats(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            result = main(
                [
                    "zwave-firmware-inventory",
                    "--input",
                    str(FIXTURE),
                    "--output-dir",
                    temporary_directory,
                ]
            )
            self.assertEqual(result, 0)
            self.assertEqual(len(list(Path(temporary_directory).glob("*.csv"))), 1)
            self.assertEqual(len(list(Path(temporary_directory).glob("*.json"))), 1)


if __name__ == "__main__":
    unittest.main()
