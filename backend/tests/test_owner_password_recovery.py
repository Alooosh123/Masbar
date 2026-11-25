import pytest

from app.security.auth import AuthStore


OLD_PASSWORD = "Existing-owner-password-2026-long"
NEW_PASSWORD = "New-owner-strong-password-with-43-random-characters"
RECOVERY_TOKEN = "owner-recovery-token-for-one-time-rotation-2026-unique"


def _store(path):
    return AuthStore(
        path,
        auth_required=True,
        bootstrap_email="owner@example.test",
        bootstrap_password=OLD_PASSWORD,
    )


def test_owner_recovery_rotates_password_once_and_invalidates_old_sessions(tmp_path):
    store = _store(tmp_path / "auth.sqlite3")
    owner_before = store.authenticate("owner@example.test", OLD_PASSWORD)
    assert owner_before is not None
    old_token_version = owner_before.token_version

    recovered = store.reset_primary_owner_password_once(RECOVERY_TOKEN, NEW_PASSWORD)

    assert recovered is not None
    assert recovered.email == "owner@example.test"
    assert recovered.role == "owner"
    assert recovered.token_version == old_token_version + 1
    assert store.authenticate("owner@example.test", OLD_PASSWORD) is None
    assert store.authenticate("owner@example.test", NEW_PASSWORD) is not None

    # The same recovery secret cannot rotate the password a second time.
    assert store.reset_primary_owner_password_once(RECOVERY_TOKEN, "Another-owner-password-2026-long") is None
    assert store.authenticate("owner@example.test", NEW_PASSWORD) is not None


def test_owner_recovery_rejects_short_secrets_without_mutating_password(tmp_path):
    store = _store(tmp_path / "auth.sqlite3")

    with pytest.raises(ValueError):
        store.reset_primary_owner_password_once("short", NEW_PASSWORD)
    with pytest.raises(ValueError):
        store.reset_primary_owner_password_once(RECOVERY_TOKEN, "too-short")

    assert store.authenticate("owner@example.test", OLD_PASSWORD) is not None


def test_owner_recovery_requires_an_existing_active_owner(tmp_path):
    store = AuthStore(
        tmp_path / "auth.sqlite3",
        auth_required=False,
        bootstrap_email=None,
        bootstrap_password=None,
    )

    with pytest.raises(RuntimeError, match="no active owner"):
        store.reset_primary_owner_password_once(RECOVERY_TOKEN, NEW_PASSWORD)
