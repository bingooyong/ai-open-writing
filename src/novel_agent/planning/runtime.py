"""规划链 CLI 运行时装配:Settings → Gateway → AgentDeps。"""

from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.gateway.base import ModelGateway, Provider
from novel_agent.gateway.providers.mock import MockProvider
from novel_agent.gateway.providers.real import AnthropicProvider, OpenAICompatProvider
from novel_agent.planning.mock_fixtures import register_planning_defaults
from novel_agent.runtime.agents import AgentDeps

_SLOT_NAMES = ("creative", "review", "judge", "extract")


def build_planning_deps(
    settings: Settings,
    session: Session,
    project_id: int,
    mock: MockProvider | None = None,
) -> AgentDeps:
    """按槽位注册 provider;mock 槽位带规划链默认 fixture。"""
    providers: dict[str, Provider] = {}
    used = {getattr(settings, name).provider for name in _SLOT_NAMES}
    if "mock" in used:
        mock_provider = mock or MockProvider()
        register_planning_defaults(mock_provider)
        providers["mock"] = mock_provider
    if "openai_compat" in used:
        providers["openai_compat"] = OpenAICompatProvider()
    if "anthropic" in used:
        providers["anthropic"] = AnthropicProvider()
    return AgentDeps(
        gateway=ModelGateway(settings, session, providers),
        project_id=project_id,
    )
