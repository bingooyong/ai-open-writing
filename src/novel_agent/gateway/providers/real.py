"""OpenAI 兼容与 Anthropic provider(httpx 直连,不引 SDK)。

真实调用只发生在 M2.6/M3.3 冒烟与 M4.2 验收(V3 槽位确认后);
此前全链路走 mock。密钥仅从 SlotConfig(env 注入)读取。
"""

import time

import httpx

from novel_agent.config import SlotConfig
from novel_agent.gateway.base import ModelRequest, ModelResponse


class OpenAICompatProvider:
    """POST {base_url}/chat/completions(OpenAI 兼容协议,覆盖多数国产供应商)。"""

    async def complete(
        self, slot: SlotConfig, req: ModelRequest, agent_role: str
    ) -> ModelResponse:
        assert slot.api_key is not None and slot.base_url, "openai_compat 需要 api_key 与 base_url"
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.user})
        body: dict = {
            "model": slot.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        if req.json_mode:
            body["response_format"] = {"type": "json_object"}

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=280.0) as client:
            r = await client.post(
                f"{slot.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {slot.api_key.get_secret_value()}"},
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        usage = data.get("usage", {})
        return ModelResponse(
            text=data["choices"][0]["message"]["content"],
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            provider="openai_compat",
            model=slot.model,
        )


class AnthropicProvider:
    """POST /v1/messages(Anthropic Messages API)。"""

    BASE = "https://api.anthropic.com"

    async def complete(
        self, slot: SlotConfig, req: ModelRequest, agent_role: str
    ) -> ModelResponse:
        assert slot.api_key is not None, "anthropic 需要 api_key"
        body: dict = {
            "model": slot.model,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "messages": [{"role": "user", "content": req.user}],
        }
        if req.system:
            body["system"] = req.system

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=280.0) as client:
            r = await client.post(
                f"{(slot.base_url or self.BASE).rstrip('/')}/v1/messages",
                headers={
                    "x-api-key": slot.api_key.get_secret_value(),
                    "anthropic-version": "2023-06-01",
                },
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        usage = data.get("usage", {})
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        return ModelResponse(
            text=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            provider="anthropic",
            model=slot.model,
        )
