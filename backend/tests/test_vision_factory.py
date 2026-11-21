import pytest

from app.adapters.vision.cohere_vlm import CohereVisionAdapter
from app.adapters.vision.factory import build_vision_adapter
from app.core.config import Settings, get_settings
from app.knowledge.loader import load_knowledge_base


@pytest.fixture(scope="module")
def kb():
    return load_knowledge_base(get_settings().kb_dir)


def test_cohere_requires_a_key(kb):
    settings = Settings(
        vision_provider="cohere",
        cohere_api_key=None,
        vision_model=None,
    )
    with pytest.raises(RuntimeError, match="COHERE_API_KEY"):
        build_vision_adapter(kb, settings)


def test_cohere_uses_provider_defaults(kb):
    settings = Settings(
        vision_provider="cohere",
        cohere_api_key="test-key",
        cohere_base_url="https://api.cohere.com/v2",
        vision_model=None,
    )
    adapter = build_vision_adapter(kb, settings)

    assert isinstance(adapter, CohereVisionAdapter)
    assert adapter.model == "command-a-vision-07-2025"
    assert adapter.base_url == "https://api.cohere.com/v2"


def test_unknown_provider_fails_fast(kb):
    settings = Settings(
        vision_provider="not-a-provider",
        vision_model="some-model",
    )
    with pytest.raises(RuntimeError, match="Unsupported VISION_PROVIDER"):
        build_vision_adapter(kb, settings)
