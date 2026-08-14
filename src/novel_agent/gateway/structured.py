"""结构化输出层(M2.3):JSON 校验+修复重试;D16 两段式正文协议。

两段式协议(Writer/Reviser 专用,规避长中文进 JSON):
    <<<SCENE:场景id>>>
    正文纯文本……
    <<<END>>>
    (每场景一组,顺序任意但 id 必须与场景卡集合一致)
    <<<META>>>
    {"chapter_summary": ..., "deviation_notes": ..., ...}
"""

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from novel_agent.gateway.base import ModelGateway, ModelRequest, ModelResponse

T = TypeVar("T", bound=BaseModel)

_REASONING_BLOCK_RE = re.compile(
    r"<(think|thinking|reason|reasoning)\b[^>]*>.*?</\1\s*>",
    re.DOTALL | re.IGNORECASE,
)
_REASONING_OPEN_RE = re.compile(
    r"<(think|thinking|reason|reasoning)\b[^>]*>",
    re.IGNORECASE,
)
_TRUNCATION_REASONS = frozenset({"length", "max_tokens"})


class StructuredOutputError(Exception):
    """修复重试后仍无法产出合法结构。按节点失败策略处理(Spec §7)。"""


def _strip_reasoning_wrappers(text: str) -> str:
    """去掉思维链包装后再找 JSON / 两段式标记。

    MiniMax-M3 OpenAI 兼容默认把自适应思考内联为 ``<think>...</think>``;
    块内若出现 ``{`` ,旧逻辑会从思维链截到正文末尾,json.loads 报
    ``line 2 column 11``。
    """
    t = _REASONING_BLOCK_RE.sub("", text)
    open_match = _REASONING_OPEN_RE.search(t)
    if open_match:
        rest = t[open_match.end() :]
        cut_at = [idx for idx in (rest.find("{"), rest.find("<<<")) if idx >= 0]
        t = t[: open_match.start()] + (rest[min(cut_at) :] if cut_at else "")
    return t.strip()


def _extract_json(text: str) -> str:
    """剥离思维链包装、markdown 代码栅栏与前后噪声,取第一个完整 JSON 对象。

    用 raw_decode 丢掉首个对象之后的拼接 JSON / 尾部垃圾,避免
    ``json.loads`` 报 Extra data。首个对象本身非法时回退到首 ``{`` 至末 ``}``。
    """
    t = _strip_reasoning_wrappers(text)
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    start = t.find("{")
    if start < 0:
        return t
    snippet = t[start:]
    try:
        _, end = json.JSONDecoder().raw_decode(snippet)
        return snippet[:end]
    except json.JSONDecodeError:
        end = t.rfind("}")
        if end > start:
            return t[start : end + 1]
        return t


def _output_truncated(resp: ModelResponse, req: ModelRequest) -> bool:
    if resp.finish_reason in _TRUNCATION_REASONS:
        return True
    return req.max_tokens > 0 and resp.output_tokens >= req.max_tokens


def _repair_previous_output(text: str) -> str:
    snippet = _extract_json(text).strip()
    if not snippet:
        return "(无合法 JSON 片段;上次输出可能只有思维链或被截断)"
    return snippet


async def call_structured(
    gateway: ModelGateway,
    slot_name: str,
    req: ModelRequest,
    schema: type[T],
    *,
    repair_attempts: int = 1,
    repair_instructions: str | None = None,
    **meta: object,
) -> T:
    """强制 JSON → Pydantic 校验 → 失败带错误信息修复重试 → 仍失败上抛。"""
    req = req.model_copy(
        update={
            "json_mode": True,
            "json_schema": schema.model_json_schema(),
            "temperature": 0.0,
        }
    )
    resp = await gateway.call(slot_name, req, **meta)  # type: ignore[arg-type]
    last_err: Exception | None = None
    text = resp.text
    truncated = _output_truncated(resp, req)

    for attempt in range(repair_attempts + 1):
        try:
            return schema.model_validate(json.loads(_extract_json(text)))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_err = exc
        if attempt == repair_attempts:
            break
        # 修复轮:回传校验错误与剥离后的片段,要求只输出修正后的 JSON
        note = ""
        if truncated:
            note = (
                "上次输出因达到 max_tokens 被截断,请重新输出完整 JSON,"
                "不要思维链或解释。\n\n"
            )
        repair_req = ModelRequest(
            system=req.system,
            user=(
                f"你上一次的输出无法通过 Schema 校验。错误信息:\n{last_err}\n\n"
                f"{note}"
                f"上一次输出:\n{_repair_previous_output(text)}\n\n"
                + (f"{repair_instructions}\n\n" if repair_instructions else "")
                + "请只输出修正后的 JSON,不要任何解释。"
            ),
            max_tokens=req.max_tokens,
            temperature=0.0,
            json_mode=True,
            json_schema=req.json_schema,
        )
        resp = await gateway.call(slot_name, repair_req, **meta)  # type: ignore[arg-type]
        text = resp.text
        truncated = truncated or _output_truncated(resp, req)

    suffix = "; 输出因 max_tokens 被截断" if truncated else ""
    raise StructuredOutputError(
        f"{schema.__name__} 校验失败(修复后仍不合法): {last_err}{suffix}"
    ) from last_err


# ---------- D16 两段式协议 ----------

_SCENE_RE = re.compile(r"<<<SCENE:(?P<sid>[^>]+)>>>\s*(?P<body>.*?)\s*<<<END>>>", re.DOTALL)
_META_RE = re.compile(r"<<<META>>>\s*(?P<meta>.*)\s*$", re.DOTALL)


class TwoPartParseError(Exception):
    pass


def parse_two_part(text: str, expected_scene_ids: list[str]) -> tuple[dict[str, str], dict]:
    """解析两段式输出 → ({scene_id: 正文}, meta dict)。

    校验:场景 id 集合与场景卡一致;正文非空;META 可解析。
    """
    text = _strip_reasoning_wrappers(text)
    blocks = [
        (match.group("sid").strip(), match.group("body").strip())
        for match in _SCENE_RE.finditer(text)
    ]
    seen: set[str] = set()
    duplicates: set[str] = set()
    for scene_id, _ in blocks:
        if scene_id in seen:
            duplicates.add(scene_id)
        seen.add(scene_id)
    if duplicates:
        raise TwoPartParseError(f"场景块重复: {sorted(duplicates)}")
    scenes = dict(blocks)
    missing = [sid for sid in expected_scene_ids if sid not in scenes]
    extra = [sid for sid in scenes if sid not in expected_scene_ids]
    if missing or extra:
        raise TwoPartParseError(f"场景 id 不匹配: 缺失={missing} 多余={extra}")
    empty = [sid for sid, body in scenes.items() if not body]
    if empty:
        raise TwoPartParseError(f"场景正文为空: {empty}")

    meta_match = _META_RE.search(text)
    if not meta_match:
        raise TwoPartParseError("缺少 <<<META>>> 段")
    # META 段截到 SCENE 标记之外(防御 META 在中间的畸形输出)
    raw = meta_match.group("meta").strip()
    try:
        meta = json.loads(_extract_json(raw))
    except json.JSONDecodeError as exc:
        raise TwoPartParseError(f"META JSON 解析失败: {exc}") from exc
    if not isinstance(meta, dict):
        raise TwoPartParseError("META JSON 必须是对象")
    return scenes, meta


TWO_PART_FORMAT_INSTRUCTIONS = """输出格式(严格遵守,不要输出其它内容):
对每个场景输出一组:
<<<SCENE:场景id>>>
(该场景的正文,纯文本,不要 JSON、不要标题、不要解释)
<<<END>>>
全部场景输出完后,最后输出:
<<<META>>>
{"chapter_summary": "本章摘要", "deviation_notes": "对章纲的偏离说明,无则留空字符串"}"""


async def call_two_part(
    gateway: ModelGateway,
    slot_name: str,
    req: ModelRequest,
    expected_scene_ids: list[str],
    *,
    repair_attempts: int = 1,
    **meta_kwargs: object,
) -> tuple[dict[str, str], dict]:
    """两段式调用:解析失败 → 带错误修复重试一次 → 仍失败上抛。"""
    resp = await gateway.call(slot_name, req, **meta_kwargs)  # type: ignore[arg-type]
    text = resp.text
    last_err: Exception | None = None

    for attempt in range(repair_attempts + 1):
        try:
            return parse_two_part(text, expected_scene_ids)
        except TwoPartParseError as exc:
            last_err = exc
        if attempt == repair_attempts:
            break
        repair_req = ModelRequest(
            system=req.system,
            user=(
                f"你上一次的输出不符合两段式格式。错误:\n{last_err}\n\n"
                f"期望的场景 id:{expected_scene_ids}\n\n上一次输出:\n{text}\n\n"
                f"请严格按以下格式重新输出全部内容:\n{TWO_PART_FORMAT_INSTRUCTIONS}"
            ),
            max_tokens=req.max_tokens,
            temperature=0.0,
        )
        resp = await gateway.call(slot_name, repair_req, **meta_kwargs)  # type: ignore[arg-type]
        text = resp.text

    raise StructuredOutputError(f"两段式解析失败(修复后仍不合法): {last_err}") from last_err
