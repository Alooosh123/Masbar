from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.domain.enums import SafetySeverity
from app.domain.kb import CueSpec, StepRecord, VerificationEvidence
from app.knowledge.loader import load_knowledge_base
from app.safety.guard import SafetyGuard, SafetyViolation


@pytest.fixture(scope="module")
def kb():
    return load_knowledge_base(get_settings().kb_dir)


@pytest.fixture(scope="module")
def guard(kb):
    return SafetyGuard(kb, min_visual_confidence=0.85)


def _verified_evidence(record, equipment_model: str) -> VerificationEvidence:
    reviewed_at = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    return VerificationEvidence(
        source_document_id=record.manual_doc_id,
        source_document_number="SYNTHETIC-QA-001",
        source_revision="test-revision",
        source_sha256="a" * 64,
        source_page=record.manual_page,
        equipment_model=equipment_model,
        nameplate_reference="TEST-ASSET-REFERENCE-001",
        reviewed_by="reviewer-test",
        reviewed_at=reviewed_at,
        approved_by="approver-test",
        approved_at=reviewed_at + timedelta(minutes=5),
        approval_reference="TEST-APPROVAL-001",
        reviewed_scopes=["identity", "procedure", "torque", "safety"],
    )


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
    # Numeric data in demo fixtures must never be exposed as operational torque.
    assert guard.build_torque(record, torque_step) is None


def test_torque_provenance_requires_traceable_independent_review(kb):
    sample_record = kb.require_component("312-5620")
    sample_torque = SafetyGuard(kb).build_torque(sample_record, sample_record.steps[-1])
    assert sample_torque is None

    # Merely flipping status flags must not turn an unreferenced value into an approved one.
    unreviewed_kb = deepcopy(kb)
    unreviewed_kb.equipment_files["Caterpillar C15 ACERT"].data_status = "verified"
    unreviewed_record = unreviewed_kb.require_component("312-5620")
    unreviewed_record.verification_status = "verified"
    unreviewed_torque = SafetyGuard(unreviewed_kb).build_torque(
        unreviewed_record, unreviewed_record.steps[-1]
    )
    assert unreviewed_torque is None

    # A verified value needs a source/page hash, model/nameplate match and two distinct reviewers.
    verified_kb = deepcopy(kb)
    verified_record = verified_kb.require_component("312-5620")
    evidence = _verified_evidence(verified_record, "Caterpillar C15 ACERT")
    verified_record.verification_status = "verified"
    verified_record.verification_evidence = evidence
    verified_equipment = verified_kb.equipment_files["Caterpillar C15 ACERT"]
    verified_equipment.data_status = "verified"
    verified_equipment.equipment_verification_evidence = evidence

    verified_torque = SafetyGuard(verified_kb).build_torque(
        verified_record, verified_record.steps[-1]
    )
    assert verified_torque is not None
    assert verified_torque.verified_from_manual is True
    assert verified_torque.source_status == "verified"


def test_verification_evidence_requires_independent_review_and_timezone():
    valid = {
        "source_document_id": "DOC-001",
        "source_document_number": "OEM-001",
        "source_revision": "Rev A",
        "source_sha256": "b" * 64,
        "source_page": 12,
        "equipment_model": "Machine Model A",
        "nameplate_reference": "ASSET-REF-01",
        "reviewed_by": "reviewer",
        "reviewed_at": "2026-11-21T10:00:00Z",
        "approved_by": "approver",
        "approved_at": "2026-11-21T10:05:00Z",
        "approval_reference": "QA-APPROVAL-01",
        "reviewed_scopes": ["identity", "procedure"],
    }
    assert VerificationEvidence.model_validate(valid)

    same_person = {**valid, "approved_by": " REVIEWER "}
    with pytest.raises(ValueError, match="different people"):
        VerificationEvidence.model_validate(same_person)

    naive_timestamp = {**valid, "reviewed_at": "2026-11-21T10:00:00"}
    with pytest.raises(ValueError, match="timezone"):
        VerificationEvidence.model_validate(naive_timestamp)


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


def test_unverified_safety_data_fails_closed_and_hides_sample_checklist(guard, kb):
    record = kb.require_component("312-5620")
    protocol = guard.build_safety(record, {"battery_disconnected"}, acknowledged=False)
    assert protocol is not None
    assert protocol.source_status == "unverified"
    assert protocol.severity == SafetySeverity.CRITICAL
    assert protocol.loto_required is True
    assert protocol.blocked_reason_ar is not None
    assert protocol.checklist == []
    assert any("غير معتمدة" in warning for warning in protocol.warnings_ar)


def test_unverified_procedure_is_blocked_even_after_loto_confirmation(guard, kb):
    record = kb.require_component("312-5620")
    with pytest.raises(SafetyViolation) as exc:
        guard.ensure_procedure_allowed(record, acknowledged=True)
    assert exc.value.code == "procedure_not_verified"
