import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_wildcard_cors_is_rejected_in_production():
    with pytest.raises(ValidationError, match="explicit trusted origins"):
        Settings(environment="production", cors_origins="*")


def test_explicit_cors_origins_are_allowed_in_production():
    settings = Settings(
        environment="production",
        cors_origins="https://demo.example.test,https://admin.example.test",
    )
    assert settings.cors_origin_list == [
        "https://demo.example.test",
        "https://admin.example.test",
    ]


def test_wildcard_cors_remains_available_for_local_development():
    settings = Settings(environment="development", cors_origins="*")
    assert settings.cors_origin_list == ["*"]
