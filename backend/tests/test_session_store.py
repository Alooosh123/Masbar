from datetime import timedelta

import pytest

from app.services.session import SessionNotFound, SessionStore, utc_now


def test_session_state_and_audit_survive_store_restart(tmp_path):
    database = tmp_path / "sessions.sqlite3"

    first_store = SessionStore(ttl_minutes=60, db_path=database)
    created = first_store.create("Caterpillar C15 ACERT")
    created.part_number = "312-5620"
    created.loto_confirmed = True
    created.confirmed_items = {"battery_disconnected", "pressure_released"}
    first_store.audit(created, "loto_confirmed", "تم تأكيد قائمة العزل")

    restarted_store = SessionStore(ttl_minutes=60, db_path=database)
    restored = restarted_store.get(created.id)

    assert restored.id == created.id
    assert restored.equipment_model == "Caterpillar C15 ACERT"
    assert restored.part_number == "312-5620"
    assert restored.loto_confirmed is True
    assert restored.confirmed_items == {"battery_disconnected", "pressure_released"}
    assert [entry.event for entry in restored.audit] == ["session_created", "loto_confirmed"]


def test_expired_persistent_sessions_are_removed(tmp_path):
    database = tmp_path / "sessions.sqlite3"
    store = SessionStore(ttl_minutes=5, db_path=database)
    created = store.create("Caterpillar C15 ACERT")
    created.updated_at = utc_now() - timedelta(minutes=10)
    store._persist(created)

    restarted_store = SessionStore(ttl_minutes=5, db_path=database)
    assert restarted_store.count() == 0
    with pytest.raises(SessionNotFound):
        restarted_store.get(created.id)


def test_in_memory_mode_remains_available():
    store = SessionStore(ttl_minutes=60)
    session = store.create("Siemens S7-1200 Control Panel")
    assert store.get(session.id).equipment_model == "Siemens S7-1200 Control Panel"
    assert store.count() == 1
