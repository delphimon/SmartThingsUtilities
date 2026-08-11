# SmartThings Utilities

Read-only command-line utilities for SmartThings inventory and diagnostics.

The utilities create local device and firmware inventories without sending device
commands, changing Edge drivers, or requiring a live log process.

## Enriched inventory for every device type

Run exactly one command:

```bash
./smartthings-utils device-inventory
```

That single process:

1. asks the authenticated SmartThings CLI for all devices, status, and health;
2. resolves Z-Wave manufacturer/model names from the bundled Z-Wave JS database,
   with official Edge-driver fingerprints as a fallback, and resolves Zigbee and
   Matter names from exact Edge-driver fingerprints;
3. checks every eligible Z-Wave device with the
   [Z-Wave JS Firmware Update Service](https://github.com/zwave-js/firmware-updates),
   beginning with one batch and isolating smaller batches only if the service
   rejects the combined request;
4. checks exact Zigbee model matches in the
   [zigbee-OTA index](https://github.com/Koenkk/zigbee-OTA); and
5. writes timestamped CSV and JSON files, then exits.

```text
device-inventory-YYYYMMDD-HHMMSS.csv
device-inventory-YYYYMMDD-HHMMSS.json
```

The result includes Z-Wave, Zigbee, Matter, LAN, OCF, virtual, hub, mobile, and
other types returned by SmartThings. Use `--type zwave`, repeat `--type` for
several types, or omit it for all types.

### Name and firmware evidence

- `EXACT_FINGERPRINT_MATCH` means the complete protocol identifier matched one
  unambiguous model. For Z-Wave, the manufacturer ID, model, and description come
  from the revision-pinned Z-Wave JS configuration database.
- `SMARTTHINGS_METADATA` uses manufacturer/model text already reported by
  SmartThings. It is useful identification evidence but is not a catalog match.
- `CATALOG_AMBIGUOUS` and `UNKNOWN` deliberately avoid choosing among multiple
  products or inventing a name.
- `SMARTTHINGS_REPORTED` is an available version exposed by the existing driver.
- `CATALOG_UPDATE_AVAILABLE` or `CATALOG_LATEST` comes from the named online
  catalog and includes its URL in each row.
- `CATALOG_LATEST_INCOMPATIBLE_BRANCH` records the newest published firmware
  for that exact fingerprint while making clear that the device's current
  firmware branch is outside the package's supported range. Its update status
  is `NOT_COMPATIBLE_WITH_CURRENT_FIRMWARE_BRANCH`, not `UPDATE_AVAILABLE`.
- `CATALOG_LATEST_DIFFERENT_HARDWARE_FINGERPRINT` reports the newest firmware
  found for the same named model family when it targets a different Z-Wave
  fingerprint. It is explicitly marked `NOT_COMPATIBLE_WITH_DEVICE_FINGERPRINT`.
- `NOT_IN_CATALOG`, `CURRENT_VERSION_OR_FINGERPRINT_REQUIRED`,
  `NO_SUPPORTED_PUBLIC_CATALOG`, and `LOOKUP_FAILED` are unknown outcomes—not
  proof that a device cannot be updated.

The `manufacturer` and `model` columns contain resolved values. The original
SmartThings strings remain available as `reported_manufacturer` and
`reported_model`, while `manufacturer_code` preserves the complete Z-Wave
fingerprint. A Z-Wave fingerprint such as `027A-B112-1F1C` therefore produces
manufacturer `Zooz`, model `ZEN22`, and the descriptive device name rather than
presenting the numeric identifier as a company name.

The Z-Wave service requires both the exact three-part fingerprint and the current
firmware version. The Zigbee public index is safe to use only when SmartThings
exposes an exact model identifier covered by that index; the Zigbee manufacturer
name alone is insufficient. Matter and vendor-cloud/LAN devices have no single
public, cross-vendor latest-firmware catalog, so the utility uses SmartThings'
`firmwareUpdate.availableVersion` when present and otherwise reports unknown.

The public catalogs are discovery evidence, not an instruction to flash a file.
An entry does not prove that SmartThings can install it, that the hardware revision
is compatible, or that installing it is safe. The utility downloads metadata only.

The repository also bundles a revision-pinned, reduced copy of the public Z-Wave
JS firmware definitions. This provides deterministic compatibility results when
the online API fails and distinguishes “a firmware file exists” from “that file
supports this device's current firmware/hardware branch.”

For the online check, the process sends each eligible Z-Wave fingerprint and its
current firmware version to `firmware.zwave-js.io`; it downloads the public Zigbee
OTA index without sending Zigbee device details to that server. It does not send
device labels, rooms, SmartThings UUIDs, hub IDs, or network IDs to either catalog.
Use `--offline` if you do not want those external requests.

### Options

```bash
# Only Z-Wave and Zigbee rows.
./smartthings-utils device-inventory --type zwave --type zigbee

# Use cached catalog responses and make no internet requests.
./smartthings-utils device-inventory --offline

# Normalize an existing SmartThings response.
./smartthings-utils device-inventory --input devices.json

# Put output somewhere specific.
./smartthings-utils device-inventory --output-dir ~/Documents
```

The live SmartThings request performed internally is equivalent to:

```bash
smartthings devices --verbose --status --health --json
```

The bundled name catalog records the official repository revision from which it
was generated. Maintainers can rebuild it from an Edge-driver checkout with:

```bash
python3 scripts/build_device_catalog.py \
  /path/to/SmartThingsEdgeDrivers \
  src/smartthings_utilities/data/device_catalog.json \
  --source-revision EDGE_COMMIT_SHA \
  --zwave-js-root /path/to/zwave-js \
  --zwave-js-revision ZWAVE_JS_COMMIT_SHA \
  --firmware-updates-root /path/to/firmware-updates \
  --firmware-updates-revision FIRMWARE_CATALOG_COMMIT_SHA
```

## Z-Wave firmware inventory

Prerequisites:

- Python 3.10 or newer.
- The current [SmartThings CLI](https://github.com/SmartThingsCommunity/smartthings-cli), already authenticated.

The original Z-Wave-only command remains available:

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
