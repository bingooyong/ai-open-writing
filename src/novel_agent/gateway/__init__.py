"""模型网关(M2.1):四槽位路由、重试、ModelRun 落库、成本估算(D7/D8)。"""

from novel_agent.gateway.base import (
    GatewayError,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    Provider,
)
from novel_agent.gateway.providers.mock import MockProvider

__all__ = [
    "GatewayError",
    "MockProvider",
    "ModelGateway",
    "ModelRequest",
    "ModelResponse",
    "Provider",
]
