"""Command-line entry point for SmartThings Utilities."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .smartthings_cli import SmartThingsCLIError, fetch_zwave_devices, load_devices_file
from .zwave_inventory import build_inventory, write_inventory_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartthings-utils",
        description="Read-only SmartThings inventory and diagnostic utilities.",
    )
    subcommands = parser.add_subparsers(dest="subcommand", required=True)

    inventory = subcommands.add_parser(
        "zwave-firmware-inventory",
        help="export all Z-Wave devices and driver-exposed firmware versions",
        description=(
            "Make one read-only bulk request through the authenticated SmartThings CLI, "
            "then write normalized CSV and JSON inventories."
        ),
    )
    inventory.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="directory for timestamped CSV and JSON files (default: current directory)",
    )
    inventory.add_argument(
        "--profile",
        default="default",
        help="SmartThings CLI profile name (default: default)",
    )
    inventory.add_argument(
        "--input",
        type=Path,
        help="normalize an existing SmartThings devices JSON file instead of going online",
    )
    return parser


def _run_zwave_inventory(args: argparse.Namespace) -> int:
    if args.input is None:
        devices = fetch_zwave_devices(profile=args.profile)
        source = "smartthings-cli"
    else:
        devices = load_devices_file(args.input)
        source = str(args.input.resolve())

    inventory = build_inventory(devices, source=source)
    csv_path, json_path = write_inventory_files(inventory, args.output_dir)
    counts = inventory["summary"]

    print(f"Z-Wave inventory complete: {counts['totalDevices']} device(s)")
    print(f"  Firmware reported:             {counts['REPORTED']}")
    print(f"  Firmware capability, no value: {counts['CAPABILITY_NO_VALUE']}")
    print(f"  Firmware not exposed:          {counts['NOT_EXPOSED']}")
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "zwave-firmware-inventory":
            return _run_zwave_inventory(args)
    except SmartThingsCLIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: unable to write inventory: {error}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.subcommand}")
    return 2
