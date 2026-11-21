from app.core.config import get_settings
from app.knowledge.loader import load_knowledge_base
from app.knowledge.retrieval import HybridRetriever


def _retriever() -> HybridRetriever:
    return HybridRetriever(load_knowledge_base(get_settings().kb_dir))


def test_valve_leak_query_matches_injection_actuator():
    hits = _retriever().search(
        "هذا البلف يهرب ديزل، كم عزم الشد حقه؟", "Caterpillar C15 ACERT"
    )
    assert hits
    assert hits[0].record.part_number == "312-5620"


def test_pump_query_matches_hydraulic_pump():
    hits = _retriever().search(
        "الطرمبة الهيدروليكية تسرب زيت", "Caterpillar 320D Excavator"
    )
    assert hits
    assert hits[0].record.part_number == "DEMO-320D-HYD-01"


def test_relay_query_matches_relay_module():
    hits = _retriever().search("الريليه لا يعمل", "Siemens S7-1200 Control Panel")
    assert hits
    assert hits[0].record.part_number == "DEMO-S7-RLY-01"


def test_equipment_scope_excludes_other_equipment():
    hits = _retriever().search("البلف يهرب ديزل", "Siemens S7-1200 Control Panel")
    assert all(hit.record.part_number != "312-5620" for hit in hits)


def test_part_number_search_works_without_hyphen():
    hits = _retriever().search("3125620", "Caterpillar C15 ACERT")
    assert hits
    assert hits[0].record.part_number == "312-5620"


def test_gibberish_returns_no_hits():
    assert _retriever().search("zzzz qqqq", "Caterpillar C15 ACERT") == []
