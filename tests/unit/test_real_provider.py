"""Provider boundary contracts for real HTTP-compatible model APIs."""

import json

import pytest

from novel_agent.config import SlotConfig
from novel_agent.gateway.base import ModelRequest
from novel_agent.gateway.providers import real


async def test_anthropic_json_mode_uses_schema_tool_and_returns_tool_input(
    monkeypatch,
) -> None:
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "content": [
                    {"type": "text", "text": "I will return the requested structure."},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "return_structured_output",
                        "input": {"answer": "ok"},
                    },
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7},
                "stop_reason": "tool_use",
            }

    class Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 600.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

        async def post(self, url: str, *, headers: dict, json: dict) -> Response:
            captured.update({"url": url, "headers": headers, "body": json})
            return Response()

    monkeypatch.setattr(real.httpx, "AsyncClient", Client)
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    response = await real.AnthropicProvider().complete(
        SlotConfig(
            provider="anthropic",
            model="MiniMax-M2.7",
            family="minimax-m2",
            api_key="secret",
            base_url="https://api.example/anthropic",
        ),
        ModelRequest(user="return data", json_mode=True, json_schema=schema),
        "planner",
    )

    assert captured["body"]["tools"] == [
        {
            "name": "return_structured_output",
            "description": "Return the requested output as a JSON object matching this schema.",
            "input_schema": schema,
        }
    ]
    assert captured["body"]["tool_choice"] == {"type": "auto"}
    assert json.loads(response.text) == {"answer": "ok"}


@pytest.mark.parametrize(
    "envelope_key,enveloped",
    [
        ("json_data", {"answer": "ok"}),
        ("json_data", json.dumps({"answer": "ok"})),
        ("return", {"answer": "ok"}),
        ("return", {"value": {"answer": "ok"}}),
    ],
)
async def test_anthropic_json_mode_unwraps_minimax_json_data_envelope(
    monkeypatch, envelope_key: str, enveloped: object
) -> None:
    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "return_structured_output",
                        "input": {envelope_key: enveloped},
                    }
                ],
                "usage": {"input_tokens": 11, "output_tokens": 7},
                "stop_reason": "tool_use",
            }

    class Client:
        def __init__(self, *, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

        async def post(self, url: str, *, headers: dict, json: dict) -> Response:
            return Response()

    monkeypatch.setattr(real.httpx, "AsyncClient", Client)
    response = await real.AnthropicProvider().complete(
        SlotConfig(
            provider="anthropic",
            model="MiniMax-M2.7",
            family="minimax-m2",
            api_key="secret",
        ),
        ModelRequest(
            user="return data",
            json_mode=True,
            json_schema={
                "type": "object",
                "properties": {"answer": {"type": "string"}},
            },
        ),
        "planner",
    )

    assert json.loads(response.text) == {"answer": "ok"}


async def test_openai_compat_minimax_json_mode_disables_thinking(
    monkeypatch,
) -> None:
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"answer": "ok"}'},
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }

    class Client:
        def __init__(self, *, timeout: float) -> None:
            assert timeout == 600.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

        async def post(self, url: str, *, headers: dict, json: dict) -> Response:
            captured.update({"url": url, "headers": headers, "body": json})
            return Response()

    monkeypatch.setattr(real.httpx, "AsyncClient", Client)
    response = await real.OpenAICompatProvider().complete(
        SlotConfig(
            provider="openai_compat",
            model="MiniMax-M3",
            family="minimax-m3",
            api_key="secret",
            base_url="https://api.example/v1",
        ),
        ModelRequest(
            user="return data",
            json_mode=True,
            json_schema={"type": "object", "properties": {"answer": {"type": "string"}}},
            max_tokens=32768,
        ),
        "outline_planner",
    )

    body = captured["body"]
    assert body["thinking"] == {"type": "disabled"}
    assert body["reasoning_split"] is True
    assert body["max_tokens"] == 32768
    assert body["max_completion_tokens"] == 32768
    assert response.text == '{"answer": "ok"}'
    assert response.finish_reason == "stop"


async def test_openai_compat_non_minimax_omits_thinking_extras(monkeypatch) -> None:
    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> dict:
            return {
                "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            }

    class Client:
        def __init__(self, *, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

        async def post(self, url: str, *, headers: dict, json: dict) -> Response:
            captured["body"] = json
            return Response()

    monkeypatch.setattr(real.httpx, "AsyncClient", Client)
    await real.OpenAICompatProvider().complete(
        SlotConfig(
            provider="openai_compat",
            model="deepseek-chat",
            family="deepseek",
            api_key="secret",
            base_url="https://api.example/v1",
        ),
        ModelRequest(user="hello", json_mode=True),
        "kernel_planner",
    )
    assert "thinking" not in captured["body"]
    assert "reasoning_split" not in captured["body"]
    assert "max_completion_tokens" not in captured["body"]


async def test_openai_compat_http_error_includes_truncated_body(monkeypatch) -> None:
    body = '{"message":"input new_sensitive (1026)"}' + ("垫" * 800)

    class Response:
        status_code = 422
        text = body

        def raise_for_status(self) -> None:
            raise AssertionError("≥400 应先带上响应体再抛")

        def json(self) -> dict:
            raise AssertionError("≥400 不应再解析成功体")

    class Client:
        def __init__(self, *, timeout: float) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            pass

        async def post(self, url: str, *, headers: dict, json: dict) -> Response:
            assert "secret" not in json
            return Response()

    monkeypatch.setattr(real.httpx, "AsyncClient", Client)
    with pytest.raises(Exception, match="input new_sensitive") as exc:
        await real.OpenAICompatProvider().complete(
            SlotConfig(
                provider="openai_compat",
                model="MiniMax-M3",
                family="minimax-m3",
                api_key="secret-should-not-leak",
                base_url="https://api.example/v1",
            ),
            ModelRequest(user="judge packet"),
            "judge",
        )
    message = str(exc.value)
    assert "422" in message
    assert "secret-should-not-leak" not in message
    assert "垫" * 800 not in message
