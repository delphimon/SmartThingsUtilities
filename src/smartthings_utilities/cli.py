"""Command-line entry point for SmartThings Utilities."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .device_inventory import build_inventory as build_device_inventory
from .device_inventory import write_inventory_files as write_device_inventory_files
from .smartthings_cli import SmartThingsCLIError, fetch_devices, fetch_zwave_devices, load_devices_file
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

    devices = subcommands.add_parser(
        "device-inventory",
        help="export and enrich devices of every SmartThings connection type",
        description=(
            "Make one read-only SmartThings request, resolve exact device names, "
            "and check supported public firmware catalogs without touching devices."
        ),
    )
    devices.add_argument(
        "--output-dir", type=Path, default=Path.cwd(),
        help="directory for timestamped CSV and JSON files (default: current directory)",
    )
    devices.add_argument("--profile", default="default", help="SmartThings CLI profile name")
    devices.add_argument(
        "--input", type=Path,
        help="use an existing SmartThings devices JSON file instead of querying SmartThings",
    )
    devices.add_argument(
        "--type", action="append", dest="device_types",
        help="include only this SmartThings type; repeat for multiple types (default: all)",
    )
    devices.add_argument(
        "--offline", action="store_true",
        help="use cached catalog responses only; never access online firmware catalogs",
    )
    devices.add_argument(
        "--cache-dir", type=Path,
        help="catalog response cache (default: ~/.cache/smartthings-utilities)",
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


def _run_device_inventory(args: argparse.Namespace) -> int:
    if args.input is None:
        devices = fetch_devices(profile=args.profile)
        source = "smartthings-cli"
    else:
        devices = load_devices_file(args.input)
        source = str(args.input.resolve())

    if args.device_types:
        wanted = {value.upper() for value in args.device_types}
        devices = [device for device in devices if str(device.get("type", "")).upper() in wanted]
    options = {"source": source, "offline": args.offline}
    if args.cache_dir is not None:
        options["cache_dir"] = args.cache_dir
    inventory = build_device_inventory(devices, **options)
    csv_path, json_path = write_device_inventory_files(inventory, args.output_dir)
    summary = inventory["summary"]
    print(f"Device inventory complete: {summary['totalDevices']} device(s)")
    print("  By protocol: " + ", ".join(f"{key}={value}" for key, value in summary["byProtocol"].items()))
    print(f"  Updates found: {summary['updatesAvailable']}")
    for provider, warning in inventory["lookupWarnings"].items():
        print(f"  Warning ({provider} catalog): {warning}", file=sys.stderr)
    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.subcommand == "zwave-firmware-inventory":
            return _run_zwave_inventory(args)
        if args.subcommand == "device-inventory":
            return _run_device_inventory(args)
    except SmartThingsCLIError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: unable to write inventory: {error}", file=sys.stderr)
        return 2

    parser.error(f"unknown command: {args.subcommand}")
    return 2
