# SmartThings Utilities

Read-only command-line utilities for SmartThings inventory and diagnostics.

The first utility creates a complete inventory of every Z-Wave device returned
by SmartThings and records the firmware version exposed by each device's current
Edge driver. It performs one bulk SmartThings request, sends no device commands,
changes no drivers, and does not require a live log process.

## Z-Wave firmware inventory

Prerequisites:

- Python 3.10 or newer.
- The current [SmartThings CLI](https://github.com/SmartThingsCommunity/smartthings-cli), already authenticated.

Run exactly one command from this repository:

```bash
./smartthings-utils zwave-firmware-inventory
```

The command invokes the SmartThings CLI once and exits after creating two
timestamped files in the current directory:

```text
zwave-firmware-inventory-YYYYMMDD-HHMMSS.csv
zwave-firmware-inventory-YYYYMMDD-HHMMSS.json
```

The CSV is the easy-to-read list. The normalized JSON retains the same data plus
summary counts and provenance. Generated inventories are ignored by Git so
device labels, rooms, IDs, and driver IDs cannot be committed accidentally.

### What the firmware status means

- `REPORTED`: the existing driver exposes a non-empty
  `firmwareUpdate.currentVersion` value.
- `CAPABILITY_NO_VALUE`: the profile exposes `firmwareUpdate`, but its current
  version is empty.
- `NOT_EXPOSED`: the existing driver/profile does not expose the firmware
  capability.

`CAPABILITY_NO_VALUE` and `NOT_EXPOSED` do **not** mean a device has no firmware
or cannot be updated. SmartThings does not provide a network-wide API that lets
an unrelated utility actively issue Version Get to devices owned by other Edge
drivers.

### Options

```bash
# Put generated files in a particular directory.
./smartthings-utils zwave-firmware-inventory --output-dir ~/Documents

# Use a non-default SmartThings CLI profile.
./smartthings-utils zwave-firmware-inventory --profile my-profile

# Normalize a previously captured SmartThings JSON response without going online.
./smartthings-utils zwave-firmware-inventory --input devices.json
```

The live request performed internally is equivalent to:

```bash
smartthings devices \
  --type zwave \
  --verbose \
  --status \
  --health \
  --json
```

The raw response is held in a temporary file only long enough to parse it, then
deleted. The generated CSV and JSON remain local until you choose to move or
share them.

## Development

The project has no third-party Python dependencies.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

New utilities should be implemented as subcommands under the shared
`smartthings-utils` executable. Keep inventory commands read-only by default and
make any command that changes SmartThings state explicit in its name and help.
