"""Small, read-only adapter around the authenticated SmartThings CLI."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


class SmartThingsCLIError(RuntimeError):
    """Raised when the SmartThings CLI cannot return a usable response."""


def load_devices_file(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
    except OSError as error:
        raise SmartThingsCLIError(f"Unable to read {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise SmartThingsCLIError(f"{path} does not contain valid JSON: {error}") from error

    if not isinstance(payload, list):
        raise SmartThingsCLIError(
            f"Expected a JSON array of SmartThings devices in {path}, got {type(payload).__name__}"
        )
    return payload


def fetch_zwave_devices(profile: str = "default") -> list[dict[str, Any]]:
    executable = shutil.which("smartthings")
    if executable is None:
        raise SmartThingsCLIError(
            "The SmartThings CLI was not found in PATH. Install it and run 'smartthings login' first."
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="smartthings-zwave-",
            suffix=".json",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        command = [
            executable,
            "devices",
            "--type",
            "zwave",
            "--verbose",
            "--status",
            "--health",
            "--json",
            "--output",
            str(temporary_path),
        ]
        if profile != "default":
            command.extend(["--profile", profile])

        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout).strip()
            if details:
                details = f"\n{details}"
            raise SmartThingsCLIError(
                f"SmartThings CLI failed with exit code {completed.returncode}.{details}"
            )

        return load_devices_file(temporary_path)
    except OSError as error:
        raise SmartThingsCLIError(f"Unable to execute the SmartThings CLI: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
