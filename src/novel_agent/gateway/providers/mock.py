"""mock provider(M2.2):按 agent_role 返回可注入的 fixture,支撑全链路离线测试。"""

import inspect
from collections.abc import Awaitable, Callable

from novel_agent.config import SlotConfig
from novel_agent.gateway.base import ModelRequest, ModelResponse

Handler = Callable[[ModelRequest], str | Awaitable[str]]


class MockProvider:
    """role → handler 注册表。未注册的 role 返回缺省回声(便于冒烟)。

    测试用法:
        mock = MockProvider()
        mock.register("writer", lambda req: fixture_text)
        mock.register("judge", make_verdict_json)      # 可注入缺陷
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}
        self.calls: list[tuple[str, ModelRequest]] = []  # 断言用调用记录

    def register(self, agent_role: str, handler: Handler) -> None:
        self._handlers[agent_role] = handler

    async def complete(
        self, slot: SlotConfig, req: ModelRequest, agent_role: str
    ) -> ModelResponse:
        self.calls.append((agent_role, req))
        handler = self._handlers.get(agent_role)
        result = handler(req) if handler else f'{{"echo": "{agent_role}"}}'
        text = await result if inspect.isawaitable(result) else result
        return ModelResponse(
            text=text,
            input_tokens=len(req.system) + len(req.user),
            output_tokens=len(text),
            latency_ms=1,
            provider="mock",
            model=slot.model,
        )
