import pytest

from app.adapters.vision.cohere_vlm import CohereVisionAdapter
from app.adapters.vision.openai_vlm import OpenAIVisionAdapter
from app.adapters.vision.factory import build_equipment_vision_adapter, build_vision_adapter
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



def test_openrouter_requires_api_key(kb):
    settings = Settings(
        vision_provider="openrouter",
        openrouter_api_key=None,
        vision_model=None,
    )
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        build_vision_adapter(kb, settings)


def test_openrouter_uses_nemotron_super_vl_free_defaults(kb):
    settings = Settings(
        vision_provider="openrouter",
        openrouter_api_key="test-openrouter-key",
        openrouter_base_url="https://openrouter.ai/api/v1",
        vision_model=None,
    )
    adapter = build_vision_adapter(kb, settings)
    equipment_adapter = build_equipment_vision_adapter(settings)

    assert isinstance(adapter, OpenAIVisionAdapter)
    assert adapter.provider_name == "openrouter"
    assert adapter.model == "nvidia/nemotron-3.5-super-vl:free"
    assert adapter.base_url == "https://openrouter.ai/api/v1"
    assert equipment_adapter.provider == "openrouter"
    assert equipment_adapter.model == "nvidia/nemotron-3.5-super-vl:free"


def test_openrouter_allows_explicit_model_override(kb):
    settings = Settings(
        vision_provider="openrouter",
        openrouter_api_key="test-openrouter-key",
        vision_model="nvidia/nemotron-3.5-super-vl:free",
    )
    adapter = build_vision_adapter(kb, settings)
    assert adapter.model == "nvidia/nemotron-3.5-super-vl:free"
