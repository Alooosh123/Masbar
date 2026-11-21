from app.core.config import get_settings
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
        assert equipment_file.disclaimer_ar
    for record in kb.components.values():
        assert record.verification_status == "sample"
