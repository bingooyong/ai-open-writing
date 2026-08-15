"""Judge 入包压缩:丢掉重复 evidence 引文,保留 id/claim/gates/scene_ids。"""


def compact_judge_issues(
    issues: list[dict],
    draft_text: str,
    *,
    drop_all_quotes: bool = False,
) -> list[dict]:
    """保留 issue id / claim / hard_gate / scene_ids,压缩或丢掉重复 evidence 引文。"""
    compacted: list[dict] = []
    for issue in issues:
        item = dict(issue)
        evidence_out: list[object] = []
        scene_ids: list[str] = []
        for ev in item.get("evidence") or []:
            if not isinstance(ev, dict):
                evidence_out.append(ev)
                continue
            ev_copy = dict(ev)
            sid = str(ev_copy.get("scene_id") or "")
            if sid and sid not in scene_ids:
                scene_ids.append(sid)
            quote = ev_copy.get("quote") or ""
            if drop_all_quotes or (quote and quote in draft_text):
                ev_copy["quote"] = "见正文"
            evidence_out.append(ev_copy)
        item["evidence"] = evidence_out
        if scene_ids:
            item["scene_ids"] = scene_ids
        compacted.append(item)
    return compacted
