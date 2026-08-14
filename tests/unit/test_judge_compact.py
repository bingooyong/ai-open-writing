"""Judge 包压缩:丢掉已出现在正文中的长 evidence 引文,保留 claim/id。"""

import json

from novel_agent.runtime.agents import _compact_judge_issues


def test_compact_judge_issues_omits_in_draft_quotes_keeps_claim_id() -> None:
    draft = (
        "茶楼里灯火通明,说书人一拍醒木,满堂皆静。"
        "他临场编出西市失火的新段子,赏钱翻倍,却不知这话次日会成真。"
    )
    long_quote = draft
    issues = [
        {
            "issue_id": "issue_1",
            "claim": "开场把失火写成真实街巷,信息越权",
            "hard_gate": "info_violation",
            "severity": "P0",
            "evidence": [
                {"scene_id": "v1c001_s1", "quote": long_quote, "note": "开场段"},
            ],
            "downweighted": False,
        }
    ]

    compacted = _compact_judge_issues(issues, draft)
    blob = json.dumps(compacted, ensure_ascii=False)

    assert compacted[0]["issue_id"] == "issue_1"
    assert compacted[0]["claim"] == "开场把失火写成真实街巷,信息越权"
    assert compacted[0]["hard_gate"] == "info_violation"
    assert compacted[0]["evidence"][0]["scene_id"] == "v1c001_s1"
    assert long_quote not in blob
    assert draft not in blob


def test_compact_judge_issues_keeps_quotes_absent_from_draft() -> None:
    issues = [
        {
            "issue_id": "issue_2",
            "claim": "引文无法定位",
            "hard_gate": None,
            "evidence": [{"scene_id": "v1c001_s1", "quote": "正文里根本没有这句话"}],
        }
    ]

    compacted = _compact_judge_issues(issues, "茶楼里灯火通明。")

    assert compacted[0]["evidence"][0]["quote"] == "正文里根本没有这句话"
    assert compacted[0]["issue_id"] == "issue_2"
    assert compacted[0]["claim"] == "引文无法定位"
