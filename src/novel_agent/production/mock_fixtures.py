"""单章循环 mock 产物:Writer/评审/Judge/Reviser/CanonCurator,不访问网络。"""

from __future__ import annotations

import json
import re

from novel_agent.gateway.base import ModelRequest
from novel_agent.gateway.providers.mock import MockProvider

LOCATABLE_QUOTE = "茶楼里灯火通明，苏晚生一拍醒木"

SCENE_1 = (
    "临安茶楼里灯火通明，苏晚生一拍醒木，满堂皆静。"
    "他随口编了西市失火的段子，听众叫好。"
    "散场时巷口有人议论，说西市夜里真的走了水。"
    "苏晚生心里发冷，第一次觉得评书和现实对上了。"
)
SCENE_1_REVISED = (
    "临安茶楼里灯火通明，苏晚生一拍醒木，满堂皆静。"
    "他随口编了西市失火的段子，听众叫好。"
    "散场时巷口有人议论，说西市夜里真的走了水。"
    "苏晚生心里发冷，他明白评书已经把西市写进了现实。"
)
SCENE_2 = (
    "入夜后他绕到茶楼后巷，霍执事已经等在那里。"
    "对方不谈天，只问他下一句还讲不讲。"
    "苏晚生想到妹妹，把到嘴边的故事咽了回去，"
    "却知道今晚的压力已经落地，后面还有钩子。"
)

_SCENE_ID_RE = re.compile(r'"scene_id":\s*"([^"]+)"')


def _scene_ids(req: ModelRequest) -> tuple[str, str]:
    found = _SCENE_ID_RE.findall(req.user)
    sid1 = found[0] if found else "v1c001_s1"
    sid2 = found[1] if len(found) > 1 else "v1c001_s2"
    return sid1, sid2


def two_part_text(req: ModelRequest, scene_1: str, scene_2: str, summary: str) -> str:
    sid1, sid2 = _scene_ids(req)
    meta = json.dumps({"chapter_summary": summary, "deviation_notes": ""}, ensure_ascii=False)
    return (
        f"<<<SCENE:{sid1}>>>\n{scene_1}\n<<<END>>>\n"
        f"<<<SCENE:{sid2}>>>\n{scene_2}\n<<<END>>>\n"
        f"<<<META>>>\n{meta}"
    )


def review_report_json(req: ModelRequest, role: str) -> str:
    sid1, _sid2 = _scene_ids(req)
    issues = [
        {
            "issue_id": f"{role}_raw1",
            "reviewer_role": role,
            "claim": "开场因果可以再收紧",
            "evidence": [{"scene_id": sid1, "quote": LOCATABLE_QUOTE}],
            "violated_rule": "因果规则",
            "severity": "P2",
            "failure_consequence": "读者觉得转折偏巧",
            "recommended_rollback_level": "prose",
            "confidence": 0.7,
        },
        {
            "issue_id": f"{role}_raw2",
            "reviewer_role": role,
            "claim": "正史冲突但引文无法定位",
            "evidence": [{"scene_id": sid1, "quote": "正文里根本没有这句话而且足够长"}],
            "violated_rule": "正史一致性",
            "severity": "P0",
            "hard_gate": "canon_conflict",
            "failure_consequence": "若误采纳会误杀干净稿",
            "recommended_rollback_level": "prose",
            "confidence": 0.4,
        },
    ]
    return json.dumps(
        {
            "reviewer_role": role,
            "candidate_id": "candidate_1",
            "issues": issues,
            "overall_note": "含一条可定位软问题与一条无证据降权项",
        },
        ensure_ascii=False,
    )


def verdict_json(
    verdict: str,
    *,
    accepted_issue: str = "continuity_1",
    revision_scope: list[str] | None = None,
    hard_gates: list[str] | None = None,
    rollback_target: str | None = None,
) -> str:
    payload: dict = {
        "verdict": verdict,
        "selected_candidate": "candidate_1",
        "hard_gate_failures": hard_gates or [],
        "rulings": [
            {
                "issue_id": accepted_issue,
                "accepted": verdict != "PASS",
                "reason": "有正文证据的局部问题" if verdict != "PASS" else "软问题不阻断",
            },
            {
                "issue_id": "plot_2",
                "accepted": True,
                "reason": "无证据项仍进入裁决,代码必须降权不得阻断",
            },
        ],
        "reasoning_summary": f"mock 裁决 {verdict}",
    }
    if verdict == "REVISE_LOCAL":
        payload["revision_scope"] = revision_scope or ["v1c001_s1"]
        payload["locked_strengths"] = ["开场醒木"]
    if verdict in {"REPLAN_SCENE", "REPLAN_CHAPTER"}:
        payload["rollback_target"] = rollback_target or "chapter_outline"
    return json.dumps(payload, ensure_ascii=False)


def canon_delta_json() -> str:
    return json.dumps(
        {
            "chapter_key": "v1c001",
            "base_canon_version": "canon_v0",
            "new_facts": [
                {
                    "entity_id": "ch_su",
                    "state_type": "status",
                    "old_value": "",
                    "new_value": "已知评书会成真",
                    "reason": "西市失火应验",
                }
            ],
        },
        ensure_ascii=False,
    )


def register_chapter_loop_defaults(mock: MockProvider) -> None:
    """为 mock provider 注册单章循环各角色的合法回包。"""
    mock.register(
        "writer_a",
        lambda req: two_part_text(req, SCENE_1, SCENE_2, "评书成真，执事上门"),
    )
    mock.register(
        "reviser",
        lambda req: two_part_text(req, SCENE_1_REVISED, SCENE_2, "评书成真，执事上门"),
    )
    def _bind_reviewer(role: str):
        def handler(req: ModelRequest) -> str:
            return review_report_json(req, role)

        return handler

    for role in ("red_team", "plot", "character", "continuity", "prose"):
        mock.register(role, _bind_reviewer(role))
    mock.register("judge", lambda _req: verdict_json("PASS"))
    mock.register("canon_curator", lambda _req: canon_delta_json())
