import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.domain.kb import EquipmentFile
from app.knowledge.loader import load_knowledge_base


def _kb():
    return load_knowledge_base(get_settings().kb_dir)


def test_counts_and_equipment():
    kb = _kb()
    assert len(kb.components) == 9
    assert len(kb.equipment) == 3
    assert "Caterpillar C15 ACERT" in kb.equipment
    assert "Caterpillar 320D Excavator" in kb.equipment
    assert "Siemens S7-1200 Control Panel" in kb.equipment


def test_all_records_are_complete():
    kb = _kb()
    for part_number, record in kb.components.items():
        assert record.arabic_name, part_number
        assert record.english_name, part_number
        assert record.manual_doc_id, part_number
        assert record.manual_page >= 1, part_number
        assert len(record.steps) >= 2, part_number
        assert [step.step_number for step in record.steps] == list(
            range(1, len(record.steps) + 1)
        ), part_number


def test_torque_steps_have_a_source_value():
    kb = _kb()
    for record in kb.components.values():
        for step in record.steps:
            if step.requires_torque:
                assert step.torque_nm is not None or record.torque_nm is not None, (
                    f"{record.part_number} step {step.step_number}"
                )


def test_loto_checklists_are_unique_and_complete():
    kb = _kb()
    for record in kb.components.values():
        if record.safety.loto_required:
            ids = [item.id for item in record.safety.checklist]
            assert len(ids) >= 2, record.part_number
            assert len(ids) == len(set(ids)), record.part_number
            assert record.safety.warnings_ar, record.part_number


def test_all_sample_data_is_labeled_as_sample():
    kb = _kb()
    for equipment_file in kb.files:
        assert equipment_file.data_status == "sample"
        assert equipment_file.equipment_verification_evidence is None
        assert equipment_file.disclaimer_ar
    for record in kb.components.values():
        assert record.verification_status == "sample"
        assert record.verification_evidence is None


def test_verified_equipment_cannot_be_loaded_without_evidence():
    raw = _kb().files[0].model_dump(mode="json")
    raw["data_status"] = "verified"
    with pytest.raises(ValidationError, match="equipment_verification_evidence"):
        EquipmentFile.model_validate(raw)


def test_verified_component_cannot_be_loaded_without_component_and_equipment_evidence():
    raw = _kb().files[0].model_dump(mode="json")
    raw["components"][0]["verification_status"] = "verified"
    with pytest.raises(ValidationError, match="verification_evidence"):
        EquipmentFile.model_validate(raw)


def test_verified_component_must_include_all_applicable_review_scopes():
    raw = _kb().files[0].model_dump(mode="json")
    component = raw["components"][0]
    component["verification_status"] = "verified"
    equipment = raw["equipment_family"]
    page = component["manual_page"]
    doc_id = component["manual_doc_id"]
    evidence = {
        "source_document_id": doc_id,
        "source_document_number": "SYNTHETIC-OEM-001",
        "source_revision": "Rev A",
        "source_sha256": "c" * 64,
        "source_page": page,
        "equipment_model": equipment,
        "nameplate_reference": "SYNTHETIC-ASSET-001",
        "reviewed_by": "reviewer",
        "reviewed_at": "2026-11-21T10:00:00Z",
        "approved_by": "approver",
        "approved_at": "2026-11-21T10:05:00Z",
        "approval_reference": "SYNTHETIC-APPROVAL-001",
        "reviewed_scopes": ["identity", "procedure"],
    }
    component["verification_evidence"] = evidence
    raw["data_status"] = "verified"
    raw["equipment_verification_evidence"] = {
        **evidence,
        "source_document_id": "EQUIPMENT-NAMEPLATE-001",
        "source_document_number": "EQUIPMENT-ID-001",
        "source_page": 1,
        "reviewed_scopes": ["identity"],
    }
    with pytest.raises(ValidationError, match="torque"):
        EquipmentFile.model_validate(raw)


def test_verified_evidence_must_match_source_page():
    raw = _kb().files[0].model_dump(mode="json")
    component = raw["components"][0]
    component["verification_status"] = "verified"
    equipment = raw["equipment_family"]
    evidence = {
        "source_document_id": component["manual_doc_id"],
        "source_document_number": "SYNTHETIC-OEM-001",
        "source_revision": "Rev A",
        "source_sha256": "d" * 64,
        "source_page": component["manual_page"] + 1,
        "equipment_model": equipment,
        "nameplate_reference": "SYNTHETIC-ASSET-001",
        "reviewed_by": "reviewer",
        "reviewed_at": "2026-11-21T10:00:00Z",
        "approved_by": "approver",
        "approved_at": "2026-11-21T10:05:00Z",
        "approval_reference": "SYNTHETIC-APPROVAL-001",
        "reviewed_scopes": ["identity", "procedure", "torque", "safety"],
    }
    component["verification_evidence"] = evidence
    raw["data_status"] = "verified"
    raw["equipment_verification_evidence"] = {
        **evidence,
        "source_document_id": "EQUIPMENT-NAMEPLATE-001",
        "source_document_number": "EQUIPMENT-ID-001",
        "source_page": 1,
        "reviewed_scopes": ["identity"],
    }
    with pytest.raises(ValidationError, match="manual_page"):
        EquipmentFile.model_validate(raw)


def test_equipment_status_cannot_promote_sample_component_to_verified():
    from copy import deepcopy

    kb = _kb()
    cloned = deepcopy(kb)
    cloned.equipment_files["Caterpillar C15 ACERT"].data_status = "verified"
    assert cloned.data_status_for("312-5620") == "sample"

