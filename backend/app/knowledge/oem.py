from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from app.domain.oem import OemManufacturer, OemRegistryFile


class OemRegistryError(RuntimeError):
    """Raised when the OEM source registry is missing or malformed."""


@dataclass
class OemRegistry:
    payload: OemRegistryFile
    manufacturers: list[OemManufacturer]
    by_id: dict[str, OemManufacturer]

    @property
    def count(self) -> int:
        return len(self.manufacturers)

    def get(self, manufacturer_id: str) -> OemManufacturer | None:
        return self.by_id.get(manufacturer_id.strip().lower())

    def search(self, query: str) -> list[OemManufacturer]:
        needle = (query or "").strip().lower()
        if not needle:
            return list(self.manufacturers)
        return [
            item
            for item in self.manufacturers
            if needle in item.name_ar.lower()
            or needle in item.name_en.lower()
            or needle in item.id
            or any(needle in model.model.lower() for model in item.model_families)
        ]


def load_oem_registry(path: Path | str) -> OemRegistry:
    file_path = Path(path)
    if not file_path.exists():
        raise OemRegistryError(f"OEM registry file does not exist: {file_path}")

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OemRegistryError(f"Invalid OEM registry JSON: {exc}") from exc

    try:
        payload = OemRegistryFile.model_validate(raw)
    except ValidationError as exc:
        raise OemRegistryError(f"Invalid OEM registry:\n{exc}") from exc

    by_id: dict[str, OemManufacturer] = {}
    for manufacturer in payload.manufacturers:
        key = manufacturer.id.lower()
        if key in by_id:
            raise OemRegistryError(f"Duplicate OEM id: {manufacturer.id!r}")
        by_id[key] = manufacturer

    return OemRegistry(payload=payload, manufacturers=payload.manufacturers, by_id=by_id)
