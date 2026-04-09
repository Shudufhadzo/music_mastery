from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from mastery_native.engine import MasteringControls


def default_preset_path() -> Path:
    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local_app_data / "Mastery" / "presets.json"

    return Path.home() / ".mastery" / "presets.json"


class MasteringPresetStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_preset_path()

    def list_names(self) -> list[str]:
        return sorted(self._read_payload().keys())

    def load_preset(self, name: str) -> MasteringControls | None:
        payload = self._read_payload().get(name)
        if payload is None:
            return None

        try:
            return MasteringControls(**payload)
        except TypeError:
            return None

    def save_preset(self, name: str, controls: MasteringControls) -> None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("Preset name is required.")

        payload = self._read_payload()
        payload[cleaned_name] = asdict(controls)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _read_payload(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            return {}

        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
