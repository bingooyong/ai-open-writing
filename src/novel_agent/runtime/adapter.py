"""Bounded cognitive-task runtime adapter.

Workflow and domain layers exchange only Pydantic schemas with this module.  The
current stage-0 implementation deliberately uses the ModelGateway directly as
the G0 fallback: AgentScope 2.0's public Agent is a tool-using ReAct loop, while
these tasks are single-shot and must not acquire workflow control or tools.
"""

from dataclasses import dataclass
from typing import Protocol, TypeVar

from pydantic import BaseModel

from novel_agent.gateway.base import ModelGateway, ModelRequest
from novel_agent.gateway.structured import call_structured, call_two_part

OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass(frozen=True)
class RuntimeCall:
    """Transport-neutral metadata recorded for one cognitive task call."""

    agent_role: str
    prompt_version: str
    project_id: int | None = None
    chapter_key: str = ""


class CognitiveRuntime(Protocol):
    """Replaceable boundary for bounded model calls; no AgentScope types escape."""

    async def structured(
        self,
        slot: str,
        request: ModelRequest,
        output_schema: type[OutputT],
        call: RuntimeCall,
    ) -> OutputT: ...

    async def two_part(
        self,
        slot: str,
        request: ModelRequest,
        scene_ids: list[str],
        call: RuntimeCall,
    ) -> tuple[dict[str, str], dict]: ...


@dataclass(frozen=True)
class GatewayRuntimeAdapter:
    """Stage-0 G0 adapter: single-shot calls through the audited ModelGateway."""

    gateway: ModelGateway

    async def structured(
        self,
        slot: str,
        request: ModelRequest,
        output_schema: type[OutputT],
        call: RuntimeCall,
    ) -> OutputT:
        return await call_structured(
            self.gateway,
            slot,
            request,
            output_schema,
            agent_role=call.agent_role,
            prompt_version=call.prompt_version,
            project_id=call.project_id,
            chapter_key=call.chapter_key,
        )

    async def two_part(
        self,
        slot: str,
        request: ModelRequest,
        scene_ids: list[str],
        call: RuntimeCall,
    ) -> tuple[dict[str, str], dict]:
        return await call_two_part(
            self.gateway,
            slot,
            request,
            scene_ids,
            agent_role=call.agent_role,
            prompt_version=call.prompt_version,
            project_id=call.project_id,
            chapter_key=call.chapter_key,
        )
