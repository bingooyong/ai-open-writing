"""OpenAI 兼容与 Anthropic provider(httpx 直连,不引 SDK)。

真实调用只发生在 M2.6/M3.3 冒烟与 M4.2 验收(V3 槽位确认后);
此前全链路走 mock。密钥仅从 SlotConfig(env 注入)读取。
"""

import json
import time
from typing import Any

import httpx

from novel_agent.config import SlotConfig
from novel_agent.gateway.base import ModelRequest, ModelResponse

REAL_REQUEST_TIMEOUT_S = 600.0
_HTTP_ERROR_BODY_LIMIT = 500


def _http_error_body(response: httpx.Response) -> str:
    """截断错误响应体,供 ≥400 诊断;不含请求头/密钥。"""
    text = (getattr(response, "text", None) or "").strip()
    if len(text) > _HTTP_ERROR_BODY_LIMIT:
        return text[:_HTTP_ERROR_BODY_LIMIT] + "…"
    return text


def _is_minimax(slot: SlotConfig) -> bool:
    return "minimax" in f"{slot.model} {slot.family}".casefold()


def _apply_minimax_openai_extras(body: dict[str, Any], req: ModelRequest) -> None:
    """Official MiniMax OpenAI-compat fields only.

    Source: https://platform.minimax.io/docs/api-reference/text-openai-api
    ``thinking.type=disabled`` skips M3 adaptive thinking (M2.x accepts but keeps
    thinking on). ``reasoning_split`` moves leftover thinking out of ``content``.
    ``max_completion_tokens`` is the documented generation cap.
    """
    body["reasoning_split"] = True
    if req.json_mode:
        body["thinking"] = {"type": "disabled"}
    body["max_completion_tokens"] = req.max_tokens


def _unwrap_structured_tool_input(
    value: dict[str, Any], schema: dict[str, Any] | None
) -> dict[str, Any]:
    if not schema:
        return value
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return value
    candidate = value
    for _ in range(3):
        if len(candidate) != 1:
            return candidate
        key, nested = next(iter(candidate.items()))
        if key in properties:
            return candidate
        if isinstance(nested, str):
            try:
                parsed: object = json.loads(nested)
            except json.JSONDecodeError:
                return value
            if not isinstance(parsed, dict):
                return value
            nested = parsed
        if not isinstance(nested, dict):
            return value
        if set(nested).intersection(properties):
            return nested
        candidate = nested
    return value


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
        if _is_minimax(slot):
            _apply_minimax_openai_extras(body, req)

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=REAL_REQUEST_TIMEOUT_S) as client:
            r = await client.post(
                f"{slot.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {slot.api_key.get_secret_value()}"},
                json=body,
            )
            if getattr(r, "status_code", 0) >= 400:
                raise RuntimeError(
                    f"openai_compat HTTP {r.status_code}: {_http_error_body(r)}"
                )
            r.raise_for_status()
            data = r.json()
        usage = data.get("usage", {})
        choice = data["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content")
        return ModelResponse(
            text=content if isinstance(content, str) else "",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            provider="openai_compat",
            model=slot.model,
            finish_reason=str(choice.get("finish_reason") or ""),
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
        if req.json_mode and req.json_schema is not None:
            body["tools"] = [
                {
                    "name": "return_structured_output",
                    "description": (
                        "Return the requested output as a JSON object matching this schema."
                    ),
                    "input_schema": req.json_schema,
                }
            ]
            body["tool_choice"] = {"type": "auto"}

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=REAL_REQUEST_TIMEOUT_S) as client:
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
        content = data.get("content", [])
        tool_inputs = [
            block.get("input")
            for block in content
            if block.get("type") == "tool_use"
            and block.get("name") == "return_structured_output"
            and isinstance(block.get("input"), dict)
        ]
        text = (
            json.dumps(
                _unwrap_structured_tool_input(tool_inputs[0], req.json_schema),
                ensure_ascii=False,
            )
            if tool_inputs
            else "".join(
                block.get("text", "")
                for block in content
                if block.get("type") == "text"
            )
        )
        return ModelResponse(
            text=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            provider="anthropic",
            model=slot.model,
            finish_reason=str(data.get("stop_reason") or ""),
        )
