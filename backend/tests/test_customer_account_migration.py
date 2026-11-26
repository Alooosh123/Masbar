import sqlite3

from app.security.auth import AuthStore


LEGACY_PASSWORD = "Legacy-owner-password-2026-is-strong"


def test_existing_sqlite_auth_table_migrates_without_losing_users(tmp_path):
    database = tmp_path / "sessions.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            """
            CREATE TABLE auth_users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner','admin','technician','viewer')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                failed_login_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                token_version INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            INSERT INTO auth_users(
                id,email,display_name,password_hash,role,is_active,created_at,
                failed_login_attempts,token_version
            ) VALUES(?,?,?,?,?,1,?,2,4)
            """,
            (
                "owner-existing",
                "owner@example.test",
                "المالك الحالي",
                AuthStore._hash_password(LEGACY_PASSWORD),
                "owner",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()

    store = AuthStore(
        database,
        auth_required=False,
        bootstrap_email=None,
        bootstrap_password=None,
    )

    existing_owner = store.authenticate("owner@example.test", LEGACY_PASSWORD)
    assert existing_owner is not None
    assert existing_owner.id == "owner-existing"
    assert existing_owner.role == "owner"
    assert existing_owner.token_version == 4

    customer = store.create_user(
        email="customer@example.test",
        display_name="عميل بعد التحديث",
        password="Customer-password-2026-is-strong",
        role="customer",
    )
    assert customer.role == "customer"
