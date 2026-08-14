"""M2.1/M2.3 DoD:槽位路由、ModelRun 字段完整、重试、结构化修复、两段式协议。"""

import pytest
from sqlmodel import Session, select
from test_schemas import KERNEL

from novel_agent.config import Settings
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.models import ModelRunRecord
from novel_agent.domain.schemas import JudgeVerdict, StoryKernel
from novel_agent.gateway import (
    GatewayError,
    MockProvider,
    ModelGateway,
    ModelRequest,
    ModelResponse,
    ResponsePolicyError,
)
from novel_agent.gateway.structured import (
    StructuredOutputError,
    _extract_json,
    call_structured,
    call_two_part,
    parse_two_part,
)


@pytest.fixture()
def session(tmp_path):
    engine = build_engine(tmp_path / "t.db")
    create_all(engine)
    with Session(engine) as s:
        yield s


def _gateway(session, provider, **settings_over):
    settings = Settings(_env_file=None, **settings_over)
    return ModelGateway(settings, session, {"mock": provider}, max_retries=1)


async def test_call_records_model_run_full_fields(session) -> None:
    """M2.1 DoD:token/耗时/成本/prompt_version/关联版本字段非空。"""
    mock = MockProvider()
    gw = _gateway(session, mock)
    resp = await gw.call(
        "creative",
        ModelRequest(user="写一段"),
        agent_role="writer",
        prompt_version="writer_v1",
        chapter_key="v1c001",
        input_ref="ctx_v1",
        output_ref="draft_v1",
    )
    assert resp.provider == "mock"

    runs = session.exec(select(ModelRunRecord)).all()
    assert len(runs) == 1
    r = runs[0]
    assert r.prompt_version == "writer_v1"
    assert r.input_tokens > 0 and r.output_tokens > 0
    assert r.latency_ms >= 0 and r.status == "ok"
    assert r.input_ref == "ctx_v1" and r.output_ref == "draft_v1"
    assert r.agent_role == "writer" and r.chapter_key == "v1c001"


async def test_retry_then_success_and_exhaustion(session) -> None:
    class Flaky:
        def __init__(self, fail_times: int) -> None:
            self.n = fail_times

        async def complete(self, slot, req, agent_role):
            if self.n > 0:
                self.n -= 1
                raise RuntimeError("网络抖动")
            return await MockProvider().complete(slot, req, agent_role)

    gw = _gateway(session, Flaky(1))
    resp = await gw.call(
        "review", ModelRequest(user="x"), agent_role="r", prompt_version="v1"
    )
    assert resp.retries == 1
    statuses = [r.status for r in session.exec(select(ModelRunRecord)).all()]
    assert statuses == ["error", "ok"]

    gw2 = _gateway(session, Flaky(99))
    with pytest.raises(GatewayError, match="重试耗尽"):
        await gw2.call("review", ModelRequest(user="x"), agent_role="r", prompt_version="v1")


async def test_post_response_policy_error_preserves_usage_without_retry(session) -> None:
    class RejectReturnedResponse:
        calls = 0

        async def complete(self, slot, req, agent_role):
            self.calls += 1
            response = ModelResponse(
                text="billable output",
                input_tokens=321,
                output_tokens=45,
                latency_ms=9,
                provider="mock",
                model=slot.model,
            )
            raise ResponsePolicyError(response, "usage rejected")

    provider = RejectReturnedResponse()
    gateway = ModelGateway(
        Settings(_env_file=None), session, {"mock": provider}, max_retries=2
    )

    with pytest.raises(GatewayError, match="策略拒绝"):
        await gateway.call(
            "creative",
            ModelRequest(user="x"),
            agent_role="writer",
            prompt_version="writer_v1",
        )

    assert provider.calls == 1
    run = session.exec(select(ModelRunRecord)).one()
    assert run.status == "error"
    assert run.input_tokens == 321 and run.output_tokens == 45
    assert run.latency_ms == 9
    assert run.error == "ResponsePolicyError: usage rejected"


async def test_unknown_slot_rejected(session) -> None:
    gw = _gateway(session, MockProvider())
    with pytest.raises(GatewayError, match="未知模型槽位"):
        await gw.call("nonexistent", ModelRequest(user="x"), agent_role="r", prompt_version="v")


# ---------- M2.3 结构化三分支 ----------

async def test_structured_direct_pass(session) -> None:
    import json

    def handler(req: ModelRequest) -> str:
        assert req.json_mode is True
        assert req.json_schema == StoryKernel.model_json_schema()
        assert req.temperature == 0.0
        return json.dumps(KERNEL, ensure_ascii=False)

    mock = MockProvider()
    mock.register("planner", handler)
    gw = _gateway(session, mock)
    k = await call_structured(
        gw, "creative", ModelRequest(user="出内核"), StoryKernel,
        agent_role="planner", prompt_version="v1",
    )
    assert k.premise == KERNEL["premise"]


async def test_structured_repair_success(session) -> None:
    import json

    state = {"n": 0}

    def handler(req: ModelRequest) -> str:
        state["n"] += 1
        if state["n"] == 1:
            return "这不是JSON"
        assert "校验" in req.user  # 修复轮带了错误信息
        assert req.json_schema == StoryKernel.model_json_schema()
        return json.dumps(KERNEL, ensure_ascii=False)

    mock = MockProvider()
    mock.register("planner", handler)
    gw = _gateway(session, mock)
    k = await call_structured(
        gw, "creative", ModelRequest(user="出内核"), StoryKernel,
        agent_role="planner", prompt_version="v1",
    )
    assert k.logline and state["n"] == 2


async def test_structured_final_failure(session) -> None:
    mock = MockProvider()
    mock.register("planner", lambda req: "永远不是JSON")
    gw = _gateway(session, mock)
    with pytest.raises(StructuredOutputError):
        await call_structured(
            gw, "creative", ModelRequest(user="x"), StoryKernel,
            agent_role="planner", prompt_version="v1",
        )


def test_extract_json_strips_think_prefix_that_failed_line2_col11() -> None:
    """Live MiniMax-M3: think 块内的 `{` 曾让 json.loads 报 line 2 column 11."""
    import json

    text = (
        "<think>{\n"
        "          先规划单元与章纲\n"
        "</think>\n"
        + json.dumps(KERNEL, ensure_ascii=False)
    )
    naive = text[text.find("{") : text.rfind("}") + 1]
    with pytest.raises(json.JSONDecodeError, match="line 2 column 11") as exc:
        json.loads(naive)
    assert exc.value.pos == 12
    parsed = json.loads(_extract_json(text))
    assert parsed["premise"] == KERNEL["premise"]


def test_extract_json_drops_trailing_second_object() -> None:
    """Live MiniMax Judge: 合法对象后再拼一段 JSON,json.loads 报 Extra data。"""
    import json

    first = json.dumps(KERNEL, ensure_ascii=False)
    text = first + '{"downweighted": true}'
    with pytest.raises(json.JSONDecodeError, match="Extra data"):
        json.loads(text)
    parsed = json.loads(_extract_json(text))
    assert parsed["premise"] == KERNEL["premise"]
    assert "downweighted" not in parsed


async def test_structured_judge_accepts_ruling_extra_and_trailing_json(session) -> None:
    import json

    payload = (
        json.dumps(
            {
                "verdict": "PASS",
                "selected_candidate": "candidate_1",
                "reasoning_summary": "无硬门禁失败",
                "rulings": [
                    {
                        "issue_id": "issue_1",
                        "accepted": False,
                        "reason": "证据不足",
                        "downweighted": True,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + '{"extra": 1}'
    )

    mock = MockProvider()
    mock.register("judge", lambda req: payload)
    gw = _gateway(session, mock)
    verdict = await call_structured(
        gw,
        "judge",
        ModelRequest(user="裁"),
        JudgeVerdict,
        agent_role="judge",
        prompt_version="v1",
    )
    assert verdict.verdict.value == "PASS"
    assert verdict.rulings[0].issue_id == "issue_1"
    assert "downweighted" not in verdict.rulings[0].model_dump()


async def test_structured_repair_from_think_only_truncated_json(session) -> None:
    """首包只有思维链 + 截断 JSON 时,修复轮仍能吃带 think 的完整 JSON."""
    import json

    state = {"n": 0}

    def handler(req: ModelRequest) -> str:
        state["n"] += 1
        if state["n"] == 1:
            return (
                "<think>{\n"
                "          只推理还没写完\n"
                "</think>\n"
                '{"premise": "截断'
            )
        assert "校验" in req.user
        assert "<think>" not in req.user
        assert "截断" in req.user
        return (
            "<think>{\n"
            "          补全 JSON\n"
            "</think>\n"
            + json.dumps(KERNEL, ensure_ascii=False)
        )

    mock = MockProvider()
    mock.register("planner", handler)
    gw = _gateway(session, mock)
    k = await call_structured(
        gw,
        "creative",
        ModelRequest(user="出内核", max_tokens=40),
        StoryKernel,
        agent_role="planner",
        prompt_version="v1",
    )
    assert k.premise == KERNEL["premise"] and state["n"] == 2


# ---------- D16 两段式 ----------

GOOD_TWO_PART = """<<<SCENE:s1>>>
茶楼里灯火通明,说书人一拍醒木。
<<<END>>>
<<<SCENE:s2>>>
散场后他数着铜钱,听见巷口的马蹄声。
<<<END>>>
<<<META>>>
{"chapter_summary": "说书人卷入失火案", "deviation_notes": ""}"""


def test_parse_two_part_good() -> None:
    scenes, meta = parse_two_part(GOOD_TWO_PART, ["s1", "s2"])
    assert scenes["s1"].startswith("茶楼") and meta["chapter_summary"]


def test_parse_two_part_strips_think_wrapper() -> None:
    scenes, meta = parse_two_part(
        "<think>{\n          先想场景再写正文\n</think>\n" + GOOD_TWO_PART,
        ["s1", "s2"],
    )
    assert scenes["s1"].startswith("茶楼") and meta["chapter_summary"]


def test_parse_two_part_mismatch_and_missing_meta() -> None:
    from novel_agent.gateway.structured import TwoPartParseError

    with pytest.raises(TwoPartParseError, match="不匹配"):
        parse_two_part(GOOD_TWO_PART, ["s1", "s2", "s3"])
    with pytest.raises(TwoPartParseError, match="META"):
        parse_two_part("<<<SCENE:s1>>>x<<<END>>>", ["s1"])


async def test_call_two_part_repair(session) -> None:
    state = {"n": 0}

    def handler(req: ModelRequest) -> str:
        state["n"] += 1
        return "格式全错" if state["n"] == 1 else GOOD_TWO_PART

    mock = MockProvider()
    mock.register("writer", handler)
    gw = _gateway(session, mock)
    scenes, meta = await call_two_part(
        gw, "creative", ModelRequest(user="写"), ["s1", "s2"],
        agent_role="writer", prompt_version="v1",
    )
    assert set(scenes) == {"s1", "s2"} and state["n"] == 2
