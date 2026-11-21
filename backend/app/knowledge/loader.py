from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from app.domain.kb import ComponentRecord, EquipmentFile


class KnowledgeBaseError(RuntimeError):
    """Raised when the knowledge base is missing, malformed, or inconsistent."""


@dataclass
class KnowledgeBase:
    files: list[EquipmentFile] = field(default_factory=list)
    components: dict[str, ComponentRecord] = field(default_factory=dict)
    equipment: dict[str, list[ComponentRecord]] = field(default_factory=dict)
    equipment_files: dict[str, EquipmentFile] = field(default_factory=dict)

    def get_component(self, part_number: str) -> ComponentRecord | None:
        return self.components.get(part_number.strip().upper())

    def require_component(self, part_number: str) -> ComponentRecord:
        component = self.get_component(part_number)
        if component is None:
            raise KeyError(part_number)
        return component

    def components_for(self, equipment_model: str) -> list[ComponentRecord]:
        return list(self.equipment.get(equipment_model, []))

    def equipment_names(self) -> list[str]:
        return sorted(self.equipment)

    def disclaimer_for(self, part_number: str) -> str:
        component = self.get_component(part_number)
        if component is None:
            return ""
        for model in component.equipment_models:
            equipment_file = self.equipment_files.get(model)
            if equipment_file is not None:
                return equipment_file.disclaimer_ar
        return ""

    def data_status_for(self, part_number: str) -> str:
        component = self.get_component(part_number)
        if component is None:
            return "unknown"
        for model in component.equipment_models:
            equipment_file = self.equipment_files.get(model)
            if equipment_file is not None:
                return equipment_file.data_status
        return "sample"


def load_knowledge_base(kb_dir: Path | str) -> KnowledgeBase:
    path = Path(kb_dir)
    if not path.exists():
        raise KnowledgeBaseError(f"Knowledge base directory does not exist: {path}")

    files = sorted(p for p in path.glob("*.json") if p.is_file())
    if not files:
        raise KnowledgeBaseError(f"No JSON knowledge files found in: {path}")

    kb = KnowledgeBase()
    for file_path in files:
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise KnowledgeBaseError(f"Invalid JSON in {file_path.name}: {exc}") from exc

        try:
            equipment_file = EquipmentFile.model_validate(raw)
        except ValidationError as exc:
            raise KnowledgeBaseError(f"Invalid knowledge file {file_path.name}:\n{exc}") from exc

        kb.files.append(equipment_file)
        kb.equipment_files[equipment_file.equipment_family] = equipment_file

        for component in equipment_file.components:
            key = component.part_number.strip().upper()
            if key in kb.components:
                raise KnowledgeBaseError(
                    f"Duplicate part number {component.part_number!r} in {file_path.name}"
                )
            kb.components[key] = component
            for model in component.equipment_models:
                kb.equipment.setdefault(model, [])
                if component not in kb.equipment[model]:
                    kb.equipment[model].append(component)

    return kb
