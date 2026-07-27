"""M0 冒烟:包可导入、配置系统行为正确(M0.5 DoD)。"""

import pytest
from pydantic import ValidationError

from novel_agent import __version__
from novel_agent.config import Settings, SlotConfig


def test_version() -> None:
    assert __version__


def test_default_settings_all_mock() -> None:
    s = Settings(_env_file=None)
    assert s.creative.provider == "mock"
    assert s.max_revision_rounds == 2
    assert s.max_calls_per_chapter == 25


def test_real_provider_requires_api_key() -> None:
    """M0.5 DoD:缺失必填项时报错清晰。"""
    with pytest.raises(ValidationError, match="api_key"):
        SlotConfig(provider="anthropic", model="some-model")


def test_judge_must_differ_from_creative() -> None:
    """Spec D8:judge 与 creative 禁止同型号。"""
    slot = {"provider": "openai_compat", "model": "same-model", "api_key": "k"}
    with pytest.raises(ValidationError, match="D8"):
        Settings(_env_file=None, creative=slot, judge=slot)


def test_revision_rounds_not_configurable() -> None:
    """两轮上限是领域固定语义,配置放宽应被拒绝。"""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, max_revision_rounds=3)  # type: ignore[arg-type]
