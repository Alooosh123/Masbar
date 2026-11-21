from copy import deepcopy

import pytest

from app.core.config import get_settings
from app.domain.kb import CueSpec, StepRecord
from app.knowledge.loader import load_knowledge_base
from app.safety.guard import SafetyGuard, SafetyViolation


@pytest.fixture(scope="module")
def kb():
    return load_knowledge_base(get_settings().kb_dir)


@pytest.fixture(scope="module")
def guard(kb):
    return SafetyGuard(kb, min_visual_confidence=0.85)


def test_unknown_part_is_rejected(guard):
    with pytest.raises(SafetyViolation) as exc:
        guard.require_component("999-9999")
    assert exc.value.code == "unknown_part_number"
    assert exc.value.status_code == 404


def test_wrong_equipment_is_rejected(guard, kb):
    record = kb.require_component("312-5620")
    with pytest.raises(SafetyViolation) as exc:
        guard.ensure_equipment(record, "Siemens S7-1200 Control Panel")
    assert exc.value.code == "equipment_mismatch"


def test_confidence_threshold_is_strict(guard):
    assert guard.confidence_allowed(0.85)
    assert not guard.confidence_allowed(0.8499)


def test_torque_only_for_torque_steps(guard, kb):
    record = kb.require_component("312-5620")
    torque_step = record.steps[-1]
    assert torque_step.requires_torque

    assert guard.build_torque(record, record.steps[0]) is None

    torque = guard.build_torque(record, torque_step)
    assert torque is not None
    assert torque.value_nm == 45.0
    assert torque.verified_from_manual is False
    assert torque.source_status == "sample"
    assert torque.source_document_id == "SENR9834-08"



def test_torque_provenance_requires_verified_equipment_and_component(kb):
    sample_record = kb.require_component("312-5620")
    sample_torque = SafetyGuard(kb).build_torque(sample_record, sample_record.steps[-1])
    assert sample_torque is not None
    assert sample_torque.verified_from_manual is False
    assert sample_torque.source_status == "sample"

    verified_kb = deepcopy(kb)
    verified_kb.equipment_files["Caterpillar C15 ACERT"].data_status = "verified"
    verified_record = verified_kb.require_component("312-5620")
    verified_record.verification_status = "verified"

    verified_torque = SafetyGuard(verified_kb).build_torque(
        verified_record, verified_record.steps[-1]
    )
    assert verified_torque is not None
    assert verified_torque.verified_from_manual is True
    assert verified_torque.source_status == "verified"


def test_missing_torque_is_never_invented(guard, kb):
    record = kb.require_component("312-5620").model_copy(deep=True)
    record.torque_nm = None
    step = StepRecord(
        step_number=1,
        instruction_ar="خطوة اختبار",
        tool_required_ar="مفتاح",
        requires_torque=True,
        cue=CueSpec(),
    )
    record.steps = [step]
    assert guard.build_torque(record, step) is None


def test_loto_gate_blocks_execution(guard, kb):
    record = kb.require_component("312-5620")
    with pytest.raises(SafetyViolation) as exc:
        guard.ensure_execution_allowed(record, acknowledged=False)
    assert exc.value.code == "loto_required"

    guard.ensure_execution_allowed(record, acknowledged=True)


def test_safety_protocol_exposes_checklist_state(guard, kb):
    record = kb.require_component("312-5620")
    protocol = guard.build_safety(record, {"battery_disconnected"}, acknowledged=False)
    assert protocol is not None
    assert protocol.loto_required is True
    assert protocol.blocked_reason_ar is not None
    states = {item.id: item.confirmed for item in protocol.checklist}
    assert states["battery_disconnected"] is True
    assert states["pressure_released"] is False
