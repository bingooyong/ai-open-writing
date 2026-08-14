"""网关核心:请求/响应契约、Provider 协议、ModelGateway。

密钥只在 Provider 内部使用;日志与 ModelRun 不落提示词正文(PRD §18.3,
debug_log=True 时由调用方显式开启并自担风险)。
"""

import asyncio
import time
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from novel_agent.config import Settings, SlotConfig
from novel_agent.domain.repos.ops import OpsRepo


class ModelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = ""
    user: str = Field(min_length=1)
    max_tokens: int = 4096
    temperature: float = 0.7
    json_mode: bool = False
    json_schema: dict[str, Any] | None = None


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    provider: str = ""
    model: str = ""
    retries: int = 0
    finish_reason: str = ""


class GatewayError(Exception):
    """重试耗尽后的最终失败。"""


class ResponsePolicyError(Exception):
    """Provider returned billable usage that a post-response policy rejected."""

    def __init__(self, response: ModelResponse, reason: str) -> None:
        super().__init__(reason)
        self.response = response


class Provider(Protocol):
    async def complete(self, slot: SlotConfig, req: ModelRequest, agent_role: str) -> ModelResponse:
        """执行一次补全。实现方负责鉴权与协议细节。"""
        ...


# 粗略成本表(USD / 1M tokens,按模型名前缀匹配;未知=0)。M4.2 实测后校准。
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus": (15.0, 75.0),
    "claude-sonnet": (3.0, 15.0),
    "claude-haiku": (0.8, 4.0),
    "gpt-5": (5.0, 15.0),
    "deepseek": (0.27, 1.1),
    "qwen": (0.5, 1.5),
    "glm": (0.6, 2.2),
    "kimi": (0.6, 2.5),
}


def model_pricing(model: str) -> tuple[float, float] | None:
    for prefix, (pin, pout) in _PRICING.items():
        if model.lower().startswith(prefix):
            return pin, pout
    return None


def slot_pricing(slot: SlotConfig) -> tuple[float, float] | None:
    if (
        slot.input_price_usd_per_million is not None
        and slot.output_price_usd_per_million is not None
    ):
        return slot.input_price_usd_per_million, slot.output_price_usd_per_million
    return model_pricing(slot.model)


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    pricing: tuple[float, float] | None = None,
) -> float:
    resolved = pricing or model_pricing(model)
    if resolved is None:
        return 0.0
    pin, pout = resolved
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)


class ModelGateway:
    """槽位路由 + 重试 + ModelRun 记录。业务代码不得绕过网关直调 SDK(D7)。"""

    def __init__(
        self,
        settings: Settings,
        session: Session,
        providers: dict[str, Provider],
        max_retries: int = 2,
        timeout_s: float = 300.0,
    ) -> None:
        self.settings = settings
        self.ops = OpsRepo(session)
        self.providers = providers
        self.max_retries = max_retries
        self.timeout_s = timeout_s

    def slot_config(self, slot_name: str) -> SlotConfig:
        cfg = getattr(self.settings, slot_name, None)
        if not isinstance(cfg, SlotConfig):
            raise GatewayError(f"未知模型槽位: {slot_name}(可用: creative/review/judge/extract)")
        return cfg

    async def call(
        self,
        slot_name: str,
        req: ModelRequest,
        *,
        agent_role: str,
        prompt_version: str,
        project_id: int | None = None,
        chapter_key: str = "",
        input_ref: str = "",
        output_ref: str = "",
    ) -> ModelResponse:
        cfg = self.slot_config(slot_name)
        provider = self.providers.get(cfg.provider)
        if provider is None:
            raise GatewayError(f"provider 未注册: {cfg.provider}")

        last_error = ""
        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                resp = await asyncio.wait_for(
                    provider.complete(cfg, req, agent_role), timeout=self.timeout_s
                )
            except ResponsePolicyError as exc:
                resp = exc.response
                resp.retries = attempt
                last_error = f"ResponsePolicyError: {exc}"
                self._record(
                    cfg,
                    agent_role,
                    prompt_version,
                    project_id,
                    chapter_key,
                    input_ref,
                    output_ref,
                    status="error",
                    error=last_error,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    latency_ms=resp.latency_ms,
                    retries=attempt,
                )
                raise GatewayError(
                    f"槽位 {slot_name}({cfg.provider}/{cfg.model})响应被策略拒绝: {exc}"
                ) from exc
            except Exception as exc:  # noqa: BLE001 — 网关边界统一兜底
                last_error = f"{type(exc).__name__}: {exc}"
                self._record(
                    cfg, agent_role, prompt_version, project_id, chapter_key,
                    input_ref, output_ref, status="error", error=last_error,
                    latency_ms=int((time.monotonic() - start) * 1000), retries=attempt,
                )
                if attempt < self.max_retries:
                    await asyncio.sleep(min(2**attempt, 8))
                continue
            resp.retries = attempt
            self._record(
                cfg, agent_role, prompt_version, project_id, chapter_key,
                input_ref, output_ref, status="ok",
                input_tokens=resp.input_tokens, output_tokens=resp.output_tokens,
                latency_ms=resp.latency_ms, retries=attempt,
            )
            return resp
        raise GatewayError(f"槽位 {slot_name}({cfg.provider}/{cfg.model})重试耗尽: {last_error}")

    def _record(
        self,
        cfg: SlotConfig,
        agent_role: str,
        prompt_version: str,
        project_id: int | None,
        chapter_key: str,
        input_ref: str,
        output_ref: str,
        *,
        status: str,
        error: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        retries: int = 0,
    ) -> None:
        """每次调用(含失败)落 ModelRun,字段齐全(PRD §8.11 / M2.1 DoD)。"""
        self.ops.record_model_run(
            project_id=project_id,
            chapter_key=chapter_key,
            agent_role=agent_role,
            provider=cfg.provider,
            model=cfg.model,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            retries=retries,
            cost_estimate=estimate_cost(
                cfg.model, input_tokens, output_tokens, pricing=slot_pricing(cfg)
            ),
            status=status,
            error=error,
            input_ref=input_ref,
            output_ref=output_ref,
        )
        self.ops.s.commit()  # 调用记录立即持久化,不受外层事务影响
