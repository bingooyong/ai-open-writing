"""M0 冒烟:包可导入、配置系统行为正确(M0.5 DoD)。"""

import pytest
from pydantic import ValidationError

from novel_agent import __version__
from novel_agent.config import EmbeddingConfig, Settings, SlotConfig


def test_version() -> None:
    assert __version__


def test_default_settings_all_mock() -> None:
    s = Settings(_env_file=None)
    assert s.creative.provider == "mock"
    assert s.max_revision_rounds == 2
    assert s.max_calls_per_chapter == 40


def test_real_provider_requires_api_key() -> None:
    """M0.5 DoD:缺失必填项时报错清晰。"""
    with pytest.raises(ValidationError, match="api_key"):
        SlotConfig(provider="anthropic", model="some-model")


def test_judge_must_differ_from_creative() -> None:
    """Spec D8:judge 与 creative 禁止同模型族。"""
    slot = {
        "provider": "openai_compat",
        "model": "same-model",
        "family": "same-family",
        "api_key": "k",
    }
    with pytest.raises(ValidationError, match="D8"):
        Settings(_env_file=None, creative=slot, judge=slot)


def test_real_provider_requires_explicit_family() -> None:
    with pytest.raises(ValidationError, match="family"):
        SlotConfig(provider="anthropic", model="claude-sonnet", api_key="k")


def test_family_is_canonicalized_before_validation_and_comparison() -> None:
    slot = SlotConfig(
        provider="anthropic", model="claude-sonnet", family="  ClAuDe  ", api_key="k"
    )
    assert slot.family == "claude"

    creative = {
        "provider": "anthropic",
        "model": "claude-sonnet",
        "family": "  Shared-Family ",
        "api_key": "k",
    }
    judge = {
        "provider": "openai_compat",
        "model": "gpt-5",
        "family": "shared-family",
        "api_key": "k",
    }
    with pytest.raises(ValidationError, match="D8"):
        Settings(_env_file=None, creative=creative, judge=judge)


@pytest.mark.parametrize("family", [" MOCK ", "Mock", "\tmOcK\n"])
def test_real_provider_rejects_mock_family_variants(family: str) -> None:
    with pytest.raises(ValidationError, match="family"):
        SlotConfig(
            provider="openai_compat",
            model="gpt-5",
            family=family,
            api_key="k",
        )


def test_price_override_requires_positive_input_and_output_pair() -> None:
    with pytest.raises(ValidationError, match="input/output"):
        SlotConfig(input_price_usd_per_million=1.0)


def test_embedding_defaults_to_mock() -> None:
    s = Settings(_env_file=None)
    assert s.embedding.provider == "mock"
    assert s.embedding.model == "mock-embed"


def test_real_embedding_requires_api_key_and_base_url() -> None:
    with pytest.raises(ValidationError, match="api_key"):
        EmbeddingConfig(provider="openai_compat", model="text-embedding-3-small")
    with pytest.raises(ValidationError, match="base_url"):
        EmbeddingConfig(
            provider="openai_compat", model="text-embedding-3-small", api_key="k"
        )


def test_revision_rounds_not_configurable() -> None:
    """两轮上限是领域固定语义,配置放宽应被拒绝。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_revision_rounds=3)  # type: ignore[arg-type]
