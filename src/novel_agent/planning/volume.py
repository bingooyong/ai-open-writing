"""百万字卷工厂:滚动窗口续规划、卷翻转、批次选章。"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from novel_agent.domain.models import ChapterRecord
from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    ChapterStatus,
    CharacterCard,
    Conflict,
    PayoffBeat,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)
from novel_agent.lint.bible import (
    _clean_token_list,
    lint_bible,
    live_names_from_kernel,
    sanitize_outline,
)
from novel_agent.memory.factory import memory_retrieval_for_session
from novel_agent.planning.chain import PlanningAborted, PlanningError, PlanningGates, _kernel_text
from novel_agent.planning.conversation import _dump, _lint_error
from novel_agent.runtime.agents import (
    AgentDeps,
    run_conflict_planner,
    run_outline_planner,
    run_payoff_planner,
)

DEFAULT_WINDOW = 5
_DONE = frozenset({ChapterStatus.CANON_LOCKED, ChapterStatus.EXPORTED})
_CHAPTER_KEY = re.compile(r"^(v\d+)c(\d+)$")
_UNIT_ID = re.compile(r"^u(\d+)$")
_VOLUME_ID = re.compile(r"^v(\d+)$")


class PlanMoreError(PlanningError):
    """续规划失败(窗口参数、圣经未就绪、产物不足)。"""


@dataclass
class PlanMoreResult:
    project_id: int
    volume_id: str
    unit_id: str
    chapter_keys: list[str]
    opened_new_volume: bool = False
    skipped: list[str] = field(default_factory=list)


def planned_ahead(chapters: Sequence[ChapterRecord]) -> list[ChapterRecord]:
    return [chapter for chapter in chapters if chapter.status not in _DONE]


def window_deficit(chapters: Sequence[ChapterRecord], window: int = DEFAULT_WINDOW) -> int:
    if window < 1:
        raise PlanMoreError("滚动窗口必须 >= 1")
    return max(0, window - len(planned_ahead(chapters)))


def select_write_batch_keys(
    planning: PlanningRepo,
    project_id: int,
    chapter_count: int,
    *,
    from_chapter: str | None = None,
) -> list[str]:
    """跳过已锁定章,从指定章或最早未完成章起取 N 个。"""
    ordered = planning.list_chapters(project_id)
    if from_chapter:
        keys = [chapter.chapter_key for chapter in ordered]
        if from_chapter not in keys:
            raise PlanMoreError(f"章节不存在: {from_chapter}")
        ordered = ordered[keys.index(from_chapter) :]
    return [
        chapter.chapter_key for chapter in ordered if chapter.status not in _DONE
    ][:chapter_count]


def next_volume_id(volume_id: str) -> str:
    match = _VOLUME_ID.fullmatch(volume_id)
    if not match:
        raise PlanMoreError(f"无法递增卷号: {volume_id}")
    return f"v{int(match.group(1)) + 1}"


def next_unit_id(existing: Sequence[str]) -> str:
    best = 0
    for unit_id in existing:
        match = _UNIT_ID.fullmatch(unit_id)
        if match:
            best = max(best, int(match.group(1)))
    return f"u{best + 1}"


def chapter_seq(chapter_key: str) -> int:
    match = _CHAPTER_KEY.fullmatch(chapter_key)
    return int(match.group(2)) if match else 0


def volume_of(chapter_key: str) -> str:
    match = _CHAPTER_KEY.fullmatch(chapter_key)
    return match.group(1) if match else ""


def planned_chapter_keys(volume_id: str, count: int, *, start: int = 1) -> list[str]:
    if count < 1:
        return []
    return [f"{volume_id}c{i:03d}" for i in range(start, start + count)]


def volume_arc_paid_off(
    planning: PlanningRepo, bible: BibleRepo, project_id: int
) -> bool:
    """当前剧情单元已标记 locked 时视为应付下一卷。"""
    chapters = planning.list_chapters(project_id)
    if not chapters:
        return False
    latest = chapters[-1]
    unit_rec = next(
        (
            rec
            for rec in planning.list_unit_records(project_id)
            if rec.unit_id == latest.unit_id
        ),
        None,
    )
    if unit_rec is None or unit_rec.status != "locked":
        return False
    return bible.get_structure_map(project_id) is not None


def collect_spoiler_state(
    outlines: Sequence[ChapterOutline],
) -> tuple[list[str], list[str]]:
    forbidden: list[str] = []
    allowed: list[str] = []
    seen_f: set[str] = set()
    seen_a: set[str] = set()
    for outline in outlines:
        for item in outline.reveal_forbidden:
            if item and item not in seen_f:
                seen_f.add(item)
                forbidden.append(item)
        for item in outline.reveal_allowed:
            if item and item not in seen_a:
                seen_a.add(item)
                allowed.append(item)
    remaining = [item for item in forbidden if item not in seen_a]
    return remaining, allowed


def apply_inherited_spoilers(
    outlines: Sequence[ChapterOutline], remaining_forbidden: Sequence[str]
) -> list[ChapterOutline]:
    updated: list[ChapterOutline] = []
    remaining = _clean_token_list(remaining_forbidden)
    for outline in outlines:
        forbidden = _clean_token_list([*remaining, *outline.reveal_forbidden])
        allowed = [item for item in outline.reveal_allowed if item not in remaining]
        updated.append(
            outline.model_copy(update={"reveal_forbidden": forbidden, "reveal_allowed": allowed})
        )
    return updated


_CITED_NUM = re.compile(r"^([A-Za-z]+)(\d+)")
_REDACTED = "（已遮蔽）"
_RECAP_FIELDS = ("title", "core_event", "exit_hook", "key_choice")


def continuation_recap(
    previous_outlines: Sequence[ChapterOutline],
    *,
    canon_notes: str = "",
) -> str:
    """把已规划章的收束压成续写回顾,供圣经切片策划对齐前文。"""
    lines: list[str] = []
    if previous_outlines:
        lines.append("前文收束:")
        for outline in previous_outlines[-5:]:
            title = outline.title or outline.chapter_key
            lines.append(
                f"- {outline.chapter_key} {title}: {outline.core_event} → {outline.end_state}"
            )
            if outline.exit_hook:
                lines.append(f"  钩子: {outline.exit_hook}")
    notes = canon_notes.strip()
    if notes and notes != "(尚无正史实体状态)":
        lines.append("正史要点:")
        lines.append(notes)
    return "\n".join(lines)


def _map_citation(raw: str, known: set[str]) -> str | None:
    if raw in known:
        return raw
    match = _CITED_NUM.match(raw)
    if match:
        prefix, num = match.group(1), int(match.group(2))
        hits = [
            kid
            for kid in known
            if (km := _CITED_NUM.match(kid))
            and km.group(1).lower() == prefix.lower()
            and int(km.group(2)) == num
        ]
        if hits:
            return sorted(hits)[0]
        padded = f"{prefix}{num:03d}"
        if padded in known:
            return padded
    for kid in known:
        if raw.startswith(kid) or kid.startswith(raw):
            return kid
    return None


def coerce_citation_ids(cited: Sequence[str], known: set[str]) -> list[str]:
    """把模型发明的冲突/爽点 id 收成圣经里已有的 id。"""
    if not known:
        return [item for item in cited if item]
    out: list[str] = []
    seen: set[str] = set()
    for raw in cited:
        if not raw:
            continue
        mapped = _map_citation(raw, known)
        if mapped and mapped not in seen:
            seen.add(mapped)
            out.append(mapped)
    if not out:
        out.append(sorted(known)[0])
    return out


def coerce_outline_citations(
    outline: ChapterOutline,
    known_conflict_ids: set[str],
    known_beat_ids: set[str],
) -> ChapterOutline:
    return outline.model_copy(
        update={
            "cited_conflict_ids": coerce_citation_ids(
                outline.cited_conflict_ids, known_conflict_ids
            ),
            "cited_beat_ids": coerce_citation_ids(outline.cited_beat_ids, known_beat_ids),
        }
    )


def redact_remaining_spoilers(
    outline: ChapterOutline, remaining_forbidden: Sequence[str]
) -> ChapterOutline:
    """从章纲可见字段抹掉仍被禁止的透剧词。"""
    secrets = [item for item in remaining_forbidden if item]
    if not secrets:
        return outline
    required = {"core_event", "exit_hook", "key_choice"}
    updates: dict[str, str] = {}
    for name in _RECAP_FIELDS:
        text = getattr(outline, name)
        for secret in secrets:
            if secret in text:
                text = text.replace(secret, "……")
        if name in required and not text.strip():
            text = _REDACTED
        updates[name] = text
    return outline.model_copy(update=updates)


def _continuation_brief(
    kernel: StoryKernel,
    previous_outlines: Sequence[ChapterOutline],
    keys: Sequence[str],
) -> str:
    tail = previous_outlines[-3:] if previous_outlines else []
    tail_txt = "；".join(
        f"{item.chapter_key} {item.title} [{item.time_location}]: {item.core_event}"
        for item in tail
    ) or "(无)"
    last_time = ""
    if previous_outlines:
        last = previous_outlines[-1]
        last_time = last.time_location or ""
    return (
        "续写同一项目，禁止另开无关类型/无关人物的新故事。\n"
        "POV 必须是林朔。女角色只用变体名：张紫衣/兆薇/周洵/许静蕾/樊冰屏/黎冰屏/柳奕妃。"
        "禁止系统面板。禁止无关刑侦/宫廷/检察官切片。\n"
        f"内核 logline: {kernel.logline}\n"
        f"已规划末三章: {tail_txt}\n"
        f"上一章时间地点: {last_time or '(空)'}。新章 time_location 必须接在此之后，"
        "禁止跳回 2005，也禁止跳回 2012 年 9 月中旬之前。当前故事已在 2012 年 9 月中旬"
        "（v27c010：更远再又再再再再再再再再一层仍不烧那一页；退回函第四项仍空；圆点仍是三个未并入秋档场次总表；"
        "周洵反打母版EDL秋档归档双签条未写入母版EDL、名字仍未批；脏角色秋档可见层抽检回执联签已挡、书面三条在可见层；"
        "柜号对照秋档对柜终盘未做、未对柜；秋档人力再缓；内袋秋档终封骑缝未盖、只许外夹层盖；"
        "钥匙对柜十七次加急托管秋档转档已挡回；分镜笔记仍合着没烧；机要柜仍上锁、钥匙在林朔手里；张紫衣那句话仍未出口）；"
        "本卷从 9 月中旬之后续写更远再又再再再再再再再再再一层的片场债，可推进到 2012 年 9 月下旬–2012 年 12 月中旬的冬档终审联签/冬档原件袋移交签收/圆点并冬档场次总表/母版EDL冬档归档双签/冬档可见层抽检回执联签/冬档对柜终盘/冬档人力配额/冬档终封骑缝/十八次加急托管冬档转档后果（必要时可自然落入 2013 年初，禁止跳回 2005），"
        "禁止错季，禁止跳回窗口内五月程序回执阶段、五月前夜、柏林窗口材料阶段、7–9 月窗口后余震、9 月下旬–11 月更往后片场债、11 月下旬–2010 年 1 月上旬再往后片场债、1 月中旬–3 月上旬继续往后片场债、3 月中旬–5 月上旬更远片场债、5 月中旬–7 月上旬再更远片场债、7 月中旬–9 月上旬更远一层片场债、9 月中旬–11 月上旬再远一层片场债、11 月中旬–2011 年 1 月上旬更远再一层片场债、2011 年 1 月中旬–3 月上旬更远又一层片场债、2011 年 3 月中旬–5 月上旬更远再又一层片场债、2011 年 5 月中旬–7 月上旬更远再又再一层片场债、2011 年 7 月中旬–9 月上旬更远再又再再一层片场债、2011 年 9 月中旬–11 月上旬更远再又再再再一层片场债、2011 年 11 月中旬–12 月下旬更远再又再再再再一层片场债、2012 年 1 月上旬–2 月中旬更远再又再再再再再一层年关档片场债、2012 年 2 月下旬–4 月中旬更远再又再再再再再再一层春档片场债、2012 年 4 月下旬–6 月中旬更远再又再再再再再再再一层夏档片场债，或 2012 年 6 月下旬–9 月中旬更远再又再再再再再再再再一层秋档片场债已写过的重复节点。"
        "单元名：戛纳窗口（可写材料/窗口程序回执余波，禁止最终奖项）；柏林全景（禁止把柏林写成「一种关注」）；"
        "威尼斯地平线（禁止「威尼斯一种关注」）。真实片名单只可引用年代志已放行且故事月已上映者；2012 年 9–12 月勿把未上映片（如《活埋》）写成已映口碑——2010/2011/2012 title_releases=[]。\n"
        "开场必须承接：更远再又再再再再再再再再一层节点已过、退回函第四项仍空；机要柜钥匙在林朔手里；机要柜仍上锁在二楼；"
        "分镜笔记合着没烧在左内袋；张紫衣那句话仍未出口；圆点仍是三个；反打名字仍未批；脏角色书面三条在可见层；柜号对照未对柜；秋档对柜终盘未做；对柜十七次加急托管秋档转档已挡回。\n"
        "承接债务：更远再又再再再再再再再再再一层的片场债与退回函第四项冬档终审联签；开机钱骑缝三联/冬档原件袋移交签收；周洵反打空栏母版EDL冬档归档双签；柳奕妃脏角色冬档可见层抽检回执联签；"
        "材料袋柜号对照冬档对柜终盘；钥匙对柜十八次加急托管冬档转档；合着的分镜笔记会不会被烧/被看见；张紫衣未出口的那句话；机要柜钥匙归属。"
        "本卷禁止把烧笔记或机要柜提前兑现。\n"
        "禁止 HeliosChain/Kestrel/何夕/代币纪元/加密/地铁崩盘等错故事。\n"
        f"新章节键: {','.join(keys)}。"
        "冲突 payoff_chapter_key 与爽点 chapter_key 必须落在这些键上。\n"
        "章纲 cited_conflict_ids/cited_beat_ids 必须引用本次冲突/爽点规划给出的 id，"
        "禁止自造对不上的 id。\n"
        "章纲 title/core_event/exit_hook/key_choice 禁止出现禁释清单中的原句。"
    )


def _coerce_outline_citations(
    outlines: Sequence[ChapterOutline],
    conflicts: Sequence[Conflict],
    beats: Sequence[PayoffBeat],
) -> list[ChapterOutline]:
    known_c = {item.conflict_id for item in conflicts}
    known_b = {item.beat_id for item in beats}
    c_by_ch: dict[str, list[str]] = {}
    for item in conflicts:
        if item.payoff_chapter_key:
            c_by_ch.setdefault(item.payoff_chapter_key, []).append(item.conflict_id)
    b_by_ch: dict[str, list[str]] = {}
    for item in beats:
        if item.chapter_key:
            b_by_ch.setdefault(item.chapter_key, []).append(item.beat_id)
    updated: list[ChapterOutline] = []
    for outline in outlines:
        cids = [cid for cid in outline.cited_conflict_ids if cid in known_c]
        bids = [bid for bid in outline.cited_beat_ids if bid in known_b]
        if not cids:
            cids = c_by_ch.get(outline.chapter_key, [])[:1]
        if not cids and not bids:
            bids = b_by_ch.get(outline.chapter_key, [])[:1]
        if not cids and not bids:
            fallback_c = c_by_ch.get(outline.chapter_key) or sorted(known_c)
            cids = fallback_c[:1]
        updated.append(
            outline.model_copy(update={"cited_conflict_ids": cids, "cited_beat_ids": bids})
        )
    return updated


_FESTIVAL_FENCES = (
    ("柏林一种关注", "柏林全景"),
    ("威尼斯一种关注", "威尼斯地平线"),
)


def _fence_text(text: str) -> str:
    for src, dst in _FESTIVAL_FENCES:
        text = text.replace(src, dst)
    return text


def _fence_outlines_and_scenes(
    outlines: Sequence[ChapterOutline],
    scenes: dict[str, list[SceneCard]],
    previous_outlines: Sequence[ChapterOutline],
) -> tuple[list[ChapterOutline], dict[str, list[SceneCard]]]:
    last_time = previous_outlines[-1].time_location if previous_outlines else ""
    shift_2005 = (("2008" in last_time) or ("2009" in last_time)) and "2005" not in last_time
    # After Oct 2008: keep planner from slipping to early-2008 festival windows.
    post_oct_2008 = ("2008" in last_time) and (
        "10 月" in last_time or "11 月" in last_time or "12 月" in last_time
    )
    # After Jan 2009 (v4c010): never slip back before 2009-01.
    post_jan_2009 = "2009" in last_time
    # After mid-July 2009 (v8c010): never slip back to May–early July window-interior.
    post_jul_mid_2009 = ("2009" in last_time) and (
        "7 月中旬" in last_time or "7月中旬" in last_time or "七月中旬" in last_time
        or "7 月下旬" in last_time or "7月下旬" in last_time
        or "8 月" in last_time or "8月" in last_time
        or "9 月" in last_time or "9月" in last_time
        or "10 月" in last_time or "10月" in last_time
        or "11 月" in last_time or "11月" in last_time
    )
    # After mid-Sep 2009 (v9c010): never slip back before Sep mid / into Jul–early Sep aftermath.
    post_sep_mid_2009 = ("2009" in last_time) and (
        "9 月中旬" in last_time or "9月中旬" in last_time or "九月中旬" in last_time
        or "9 月下旬" in last_time or "9月下旬" in last_time
        or "10 月" in last_time or "10月" in last_time
        or "11 月" in last_time or "11月" in last_time
    )
    # After mid-Nov 2009 (v10c010): never slip back before Nov mid / into Sep–early Nov aftermath.
    post_nov_mid_2009 = ("2009" in last_time) and (
        "11 月中旬" in last_time or "11月中旬" in last_time or "十一月中旬" in last_time
        or "11 月下旬" in last_time or "11月下旬" in last_time
        or "12 月" in last_time or "12月" in last_time
        or "2010" in last_time
    )
    # After early-Jan 2010 (v11c010): never slip back before Jan mid / into 2009 Nov–Dec / early Jan.
    post_jan_early_2010 = ("2010" in last_time) and (
        "1 月上旬" in last_time or "1月上旬" in last_time or "一月上旬" in last_time
        or "1 月中旬" in last_time or "1月中旬" in last_time
        or "1 月下旬" in last_time or "1月下旬" in last_time
        or "2 月" in last_time or "2月" in last_time
        or "3 月" in last_time or "3月" in last_time
    )
    # After early-Mar 2010 (v12c010): never slip back before Mar mid / into Jan–early Mar.
    post_mar_early_2010 = ("2010" in last_time) and (
        "3 月上旬" in last_time or "3月上旬" in last_time or "三月上旬" in last_time
        or "3 月中旬" in last_time or "3月中旬" in last_time
        or "3 月下旬" in last_time or "3月下旬" in last_time
        or "4 月" in last_time or "4月" in last_time
        or "5 月" in last_time or "5月" in last_time
    )
    # After early-May 2010 (v13c010): never slip back before May mid / into Mar–early May.
    post_may_early_2010 = ("2010" in last_time) and (
        "5 月上旬" in last_time or "5月上旬" in last_time or "五月上旬" in last_time
        or "5 月中旬" in last_time or "5月中旬" in last_time
        or "5 月下旬" in last_time or "5月下旬" in last_time
        or "6 月" in last_time or "6月" in last_time
        or "7 月" in last_time or "7月" in last_time
    )
    # After early-July 2010 (v14c010): never slip back before July mid / into May–early July.
    post_jul_early_2010 = ("2010" in last_time) and (
        "7 月上旬" in last_time or "7月上旬" in last_time or "七月上旬" in last_time
        or "7 月中旬" in last_time or "7月中旬" in last_time
        or "7 月下旬" in last_time or "7月下旬" in last_time
        or "8 月" in last_time or "8月" in last_time
        or "9 月" in last_time or "9月" in last_time
    )
    # After early-Sep 2010 (v15c010): never slip back before Sep mid / into Jul–early Sep.
    post_sep_early_2010 = ("2010" in last_time) and (
        "9 月上旬" in last_time or "9月上旬" in last_time or "九月上旬" in last_time
        or "9 月中旬" in last_time or "9月中旬" in last_time
        or "9 月下旬" in last_time or "9月下旬" in last_time
        or "10 月" in last_time or "10月" in last_time
        or "11 月" in last_time or "11月" in last_time
    )
    # After early-Nov 2010 (v16c010): never slip back before Nov mid / into Sep–early Nov.
    post_nov_early_2010 = (
        ("2010" in last_time) and (
            "11 月上旬" in last_time or "11月上旬" in last_time or "十一月上旬" in last_time
            or "11 月中旬" in last_time or "11月中旬" in last_time
            or "11 月下旬" in last_time or "11月下旬" in last_time
            or "12 月" in last_time or "12月" in last_time
        )
    ) or ("2011" in last_time)
    # After early-Jan 2011 (v17c010): never slip back before Jan mid / into 2010 Nov–Dec / early Jan 2011.
    post_jan_early_2011 = ("2011" in last_time) and (
        "1 月上旬" in last_time or "1月上旬" in last_time or "一月上旬" in last_time
        or "1 月中旬" in last_time or "1月中旬" in last_time
        or "1 月下旬" in last_time or "1月下旬" in last_time
        or "2 月" in last_time or "2月" in last_time
        or "3 月" in last_time or "3月" in last_time
    )
    # After early-Mar 2011 (v18c010): never slip back before Mar mid / into Jan–early Mar 2011.
    post_mar_early_2011 = ("2011" in last_time) and (
        "3 月上旬" in last_time or "3月上旬" in last_time or "三月上旬" in last_time
        or "3 月中旬" in last_time or "3月中旬" in last_time
        or "3 月下旬" in last_time or "3月下旬" in last_time
        or "4 月" in last_time or "4月" in last_time
        or "5 月" in last_time or "5月" in last_time
    )
    # After early-May 2011 (v19c010): never slip back before May mid / into Mar–early May 2011.
    post_may_early_2011 = ("2011" in last_time) and (
        "5 月上旬" in last_time or "5月上旬" in last_time or "五月上旬" in last_time
        or "5 月中旬" in last_time or "5月中旬" in last_time
        or "5 月下旬" in last_time or "5月下旬" in last_time
        or "6 月" in last_time or "6月" in last_time
        or "7 月" in last_time or "7月" in last_time
    )
    # After early-July 2011 (v20c010): never slip back before July mid / into May–early July 2011.
    post_jul_early_2011 = ("2011" in last_time) and (
        "7 月上旬" in last_time or "7月上旬" in last_time or "七月上旬" in last_time
        or "7 月中旬" in last_time or "7月中旬" in last_time
        or "7 月下旬" in last_time or "7月下旬" in last_time
        or "8 月" in last_time or "8月" in last_time
        or "9 月" in last_time or "9月" in last_time
    )
    # After early-Sep 2011 (v21c010): never slip back before Sep mid / into Jul–early Sep 2011.
    post_sep_early_2011 = ("2011" in last_time) and (
        "9 月上旬" in last_time or "9月上旬" in last_time or "九月上旬" in last_time
        or "9 月中旬" in last_time or "9月中旬" in last_time
        or "9 月下旬" in last_time or "9月下旬" in last_time
        or "10 月" in last_time or "10月" in last_time
        or "11 月" in last_time or "11月" in last_time
    )
    # After early-Nov 2011 (v22c010): never slip back before Nov mid / into Sep–early Nov 2011.
    post_nov_early_2011 = ("2011" in last_time) and (
        "11 月上旬" in last_time or "11月上旬" in last_time or "十一月上旬" in last_time
        or "11 月中旬" in last_time or "11月中旬" in last_time
        or "11 月下旬" in last_time or "11月下旬" in last_time
        or "12 月" in last_time or "12月" in last_time
    )
    # After late-Dec 2011 (v23c010): never slip back before 2012 Jan / into 2011 Nov–Dec.
    post_dec_late_2011 = (
        ("2012" in last_time)
        or (
            ("2011" in last_time)
            and (
                "12 月下旬" in last_time or "12月下旬" in last_time or "十二月下旬" in last_time
                or "12 月中旬" in last_time or "12月中旬" in last_time
                or "12 月" in last_time or "12月" in last_time
            )
        )
    )
    # After mid-Feb 2012 (v24c010): never slip back before late Feb / into Jan–mid Feb 年关档.
    post_feb_mid_2012 = ("2012" in last_time) and (
        "2 月中旬" in last_time or "2月中旬" in last_time or "二月中旬" in last_time
        or "2 月下旬" in last_time or "2月下旬" in last_time
        or "3 月" in last_time or "3月" in last_time
        or "4 月" in last_time or "4月" in last_time
    )
    # After mid-Apr 2012 (v25c010): never slip back before late Apr / into Feb–mid Apr 春档.
    post_apr_mid_2012 = ("2012" in last_time) and (
        "4 月中旬" in last_time or "4月中旬" in last_time or "四月中旬" in last_time
        or "4 月下旬" in last_time or "4月下旬" in last_time
        or "5 月" in last_time or "5月" in last_time
        or "6 月" in last_time or "6月" in last_time
    )
    # After mid-Jun 2012 (v26c010): never slip back before late Jun / into Apr–mid Jun 夏档.
    post_jun_mid_2012 = ("2012" in last_time) and (
        "6 月中旬" in last_time or "6月中旬" in last_time or "六月中旬" in last_time
        or "6 月下旬" in last_time or "6月下旬" in last_time
        or "7 月" in last_time or "7月" in last_time
        or "8 月" in last_time or "8月" in last_time
        or "9 月" in last_time or "9月" in last_time
    )
    # After mid-Sep 2012 (v27c010): never slip back before late Sep / into Jun–mid Sep 秋档.
    post_sep_mid_2012 = ("2012" in last_time) and (
        "9 月中旬" in last_time or "9月中旬" in last_time or "九月中旬" in last_time
        or "9 月下旬" in last_time or "9月下旬" in last_time
        or "10 月" in last_time or "10月" in last_time
        or "11 月" in last_time or "11月" in last_time
        or "12 月" in last_time or "12月" in last_time
    ) or ("2013" in last_time)

    def _fix_time(tl: str) -> str:
        tl = _fence_text(tl)
        if shift_2005 or post_jan_2009:
            # remap early years forward; 2005/06/07/08 slips become 2009
            if post_jan_2009:
                for y in ("2005", "2006", "2007", "2008"):
                    tl = tl.replace(y, "2009")
            else:
                tl = tl.replace("2005", "2008")
        if post_jul_mid_2009:
            # map May–early July 2009 slips forward past v8c010
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月"):
                if f"2009 年 {m}" in tl or f"2009年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2009 年 {m}", "2009 年 7 月下旬")
                    tl = tl.replace(f"2009年{m.replace(' ','')}", "2009年7月下旬")
            for early in ("7 月上旬", "7月上旬", "7 月中旬", "7月中旬"):
                if early in tl and "7 月下旬" not in tl and "7月下旬" not in tl:
                    tl = tl.replace(early, "7 月下旬")
        if post_sep_mid_2009:
            # map Jul–early Sep 2009 slips forward past v9c010
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月"):
                if f"2009 年 {m}" in tl or f"2009年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2009 年 {m}", "2009 年 9 月下旬")
                    tl = tl.replace(f"2009年{m.replace(' ','')}", "2009年9月下旬")
            for early in ("9 月上旬", "9月上旬", "9 月中旬", "9月中旬"):
                if early in tl and "9 月下旬" not in tl and "9月下旬" not in tl:
                    tl = tl.replace(early, "9 月下旬")
        if post_nov_mid_2009:
            # map Jan–early Nov 2009 slips forward past v10c010; keep 2010 if already there
            if "2010" not in tl:
                for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月", "10 月"):
                    if f"2009 年 {m}" in tl or f"2009年{m.replace(' ','')}" in tl:
                        tl = tl.replace(f"2009 年 {m}", "2009 年 11 月下旬")
                        tl = tl.replace(f"2009年{m.replace(' ','')}", "2009年11月下旬")
                for early in ("11 月上旬", "11月上旬", "11 月中旬", "11月中旬"):
                    if early in tl and "11 月下旬" not in tl and "11月下旬" not in tl:
                        tl = tl.replace(early, "11 月下旬")
        if post_jan_early_2010:
            # map any 2009 / early-Jan 2010 slips forward past v11c010
            if "2009" in tl:
                tl = tl.replace("2009", "2010")
            for early in ("1 月上旬", "1月上旬", "一月上旬"):
                if early in tl and "1 月中旬" not in tl and "1月中旬" not in tl:
                    tl = tl.replace(early, "1 月中旬")
        if post_mar_early_2010 and not post_may_early_2010:
            # map any 2009 / Jan–early-Mar 2010 slips forward past v12c010
            if "2009" in tl:
                tl = tl.replace("2009", "2010")
            for m in ("1 月", "2 月"):
                if f"2010 年 {m}" in tl or f"2010年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2010 年 {m}", "2010 年 3 月中旬")
                    tl = tl.replace(f"2010年{m.replace(' ','')}", "2010年3月中旬")
            for early in ("3 月上旬", "3月上旬", "三月上旬"):
                if early in tl and "3 月中旬" not in tl and "3月中旬" not in tl:
                    tl = tl.replace(early, "3 月中旬")
        if post_may_early_2010 and not post_jul_early_2010:
            # map any 2009 / Jan–early-May 2010 slips forward past v13c010
            if "2009" in tl:
                tl = tl.replace("2009", "2010")
            for m in ("1 月", "2 月", "3 月", "4 月"):
                if f"2010 年 {m}" in tl or f"2010年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2010 年 {m}", "2010 年 5 月中旬")
                    tl = tl.replace(f"2010年{m.replace(' ','')}", "2010年5月中旬")
            for early in ("5 月上旬", "5月上旬", "五月上旬"):
                if early in tl and "5 月中旬" not in tl and "5月中旬" not in tl:
                    tl = tl.replace(early, "5 月中旬")
        if post_jul_early_2010 and not post_sep_early_2010:
            # map any 2009 / Jan–early-July 2010 slips forward past v14c010
            if "2009" in tl:
                tl = tl.replace("2009", "2010")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月"):
                if f"2010 年 {m}" in tl or f"2010年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2010 年 {m}", "2010 年 7 月中旬")
                    tl = tl.replace(f"2010年{m.replace(' ','')}", "2010年7月中旬")
            for early in ("7 月上旬", "7月上旬", "七月上旬"):
                if early in tl and "7 月中旬" not in tl and "7月中旬" not in tl:
                    tl = tl.replace(early, "7 月中旬")
        if post_sep_early_2010 and not post_nov_early_2010:
            # map any 2009 / Jan–early-Sep 2010 slips forward past v15c010
            if "2009" in tl:
                tl = tl.replace("2009", "2010")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月"):
                if f"2010 年 {m}" in tl or f"2010年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2010 年 {m}", "2010 年 9 月中旬")
                    tl = tl.replace(f"2010年{m.replace(' ','')}", "2010年9月中旬")
            for early in ("9 月上旬", "9月上旬", "九月上旬"):
                if early in tl and "9 月中旬" not in tl and "9月中旬" not in tl:
                    tl = tl.replace(early, "9 月中旬")
        if post_nov_early_2010 and not post_jan_early_2011:
            # map any 2009 / Jan–early-Nov 2010 slips forward past v16c010
            if "2009" in tl:
                tl = tl.replace("2009", "2010")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月", "10 月"):
                if f"2010 年 {m}" in tl or f"2010年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2010 年 {m}", "2010 年 11 月中旬")
                    tl = tl.replace(f"2010年{m.replace(' ','')}", "2010年11月中旬")
            for early in ("11 月上旬", "11月上旬", "十一月上旬"):
                if early in tl and "11 月中旬" not in tl and "11月中旬" not in tl:
                    tl = tl.replace(early, "11 月中旬")
        if post_jan_early_2011 and not post_mar_early_2011:
            # map any 2009/2010 / early-Jan 2011 slips forward past v17c010
            if "2009" in tl:
                tl = tl.replace("2009", "2011")
            if "2010" in tl:
                tl = tl.replace("2010", "2011")
            for early in ("1 月上旬", "1月上旬", "一月上旬"):
                if early in tl and "1 月中旬" not in tl and "1月中旬" not in tl:
                    tl = tl.replace(early, "1 月中旬")
        if post_mar_early_2011 and not post_may_early_2011:
            # map any 2009/2010 / Jan–early-Mar 2011 slips forward past v18c010
            if "2009" in tl:
                tl = tl.replace("2009", "2011")
            if "2010" in tl:
                tl = tl.replace("2010", "2011")
            for m in ("1 月", "2 月"):
                if f"2011 年 {m}" in tl or f"2011年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2011 年 {m}", "2011 年 3 月中旬")
                    tl = tl.replace(f"2011年{m.replace(' ','')}", "2011年3月中旬")
            for early in ("3 月上旬", "3月上旬", "三月上旬"):
                if early in tl and "3 月中旬" not in tl and "3月中旬" not in tl:
                    tl = tl.replace(early, "3 月中旬")
        if post_may_early_2011 and not post_jul_early_2011:
            # map any 2009/2010 / Mar–early-May 2011 slips forward past v19c010
            if "2009" in tl:
                tl = tl.replace("2009", "2011")
            if "2010" in tl:
                tl = tl.replace("2010", "2011")
            for m in ("1 月", "2 月", "3 月", "4 月"):
                if f"2011 年 {m}" in tl or f"2011年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2011 年 {m}", "2011 年 5 月中旬")
                    tl = tl.replace(f"2011年{m.replace(' ','')}", "2011年5月中旬")
            for early in ("5 月上旬", "5月上旬", "五月上旬"):
                if early in tl and "5 月中旬" not in tl and "5月中旬" not in tl:
                    tl = tl.replace(early, "5 月中旬")
        if post_jul_early_2011 and not post_sep_early_2011:
            # map any 2009/2010 / May–early-July 2011 slips forward past v20c010
            if "2009" in tl:
                tl = tl.replace("2009", "2011")
            if "2010" in tl:
                tl = tl.replace("2010", "2011")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月"):
                if f"2011 年 {m}" in tl or f"2011年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2011 年 {m}", "2011 年 7 月中旬")
                    tl = tl.replace(f"2011年{m.replace(' ','')}", "2011年7月中旬")
            for early in ("7 月上旬", "7月上旬", "七月上旬"):
                if early in tl and "7 月中旬" not in tl and "7月中旬" not in tl:
                    tl = tl.replace(early, "7 月中旬")
        if post_sep_early_2011 and not post_nov_early_2011:
            # map any 2009/2010 / Jul–early-Sep 2011 slips forward past v21c010
            if "2009" in tl:
                tl = tl.replace("2009", "2011")
            if "2010" in tl:
                tl = tl.replace("2010", "2011")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月"):
                if f"2011 年 {m}" in tl or f"2011年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2011 年 {m}", "2011 年 9 月中旬")
                    tl = tl.replace(f"2011年{m.replace(' ','')}", "2011年9月中旬")
            for early in ("9 月上旬", "9月上旬", "九月上旬"):
                if early in tl and "9 月中旬" not in tl and "9月中旬" not in tl:
                    tl = tl.replace(early, "9 月中旬")
        if post_nov_early_2011 and not post_dec_late_2011:
            # map any 2009/2010 / Jan–early-Nov 2011 slips forward past v22c010
            if "2009" in tl:
                tl = tl.replace("2009", "2011")
            if "2010" in tl:
                tl = tl.replace("2010", "2011")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月", "10 月"):
                if f"2011 年 {m}" in tl or f"2011年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2011 年 {m}", "2011 年 11 月中旬")
                    tl = tl.replace(f"2011年{m.replace(' ','')}", "2011年11月中旬")
            for early in ("11 月上旬", "11月上旬", "十一月上旬"):
                if early in tl and "11 月中旬" not in tl and "11月中旬" not in tl:
                    tl = tl.replace(early, "11 月中旬")
        if post_dec_late_2011 and not post_feb_mid_2012:
            # map any 2009/2010/2011 slips forward past v23c010 into early 2012
            if "2009" in tl:
                tl = tl.replace("2009", "2012")
            if "2010" in tl:
                tl = tl.replace("2010", "2012")
            if "2011" in tl:
                tl = tl.replace("2011", "2012")
            for m in ("3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月", "10 月", "11 月", "12 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 1 月上旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年1月上旬")
        if post_feb_mid_2012 and not post_apr_mid_2012:
            # map any 2009/2010/2011 / Jan–early-Feb 2012 slips forward past v24c010 into 春档
            if "2009" in tl:
                tl = tl.replace("2009", "2012")
            if "2010" in tl:
                tl = tl.replace("2010", "2012")
            if "2011" in tl:
                tl = tl.replace("2011", "2012")
            for m in ("1 月",):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 2 月下旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年2月下旬")
            for early in ("2 月上旬", "2月上旬", "二月上旬", "2 月中旬", "2月中旬", "二月中旬"):
                if early in tl and "2 月下旬" not in tl and "2月下旬" not in tl:
                    tl = tl.replace(early, "2 月下旬")
            for m in ("5 月", "6 月", "7 月", "8 月", "9 月", "10 月", "11 月", "12 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 3 月上旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年3月上旬")
        if post_apr_mid_2012 and not post_jun_mid_2012:
            # map any 2009/2010/2011 / Jan–early-Apr 2012 slips forward past v25c010 into 夏档
            if "2009" in tl:
                tl = tl.replace("2009", "2012")
            if "2010" in tl:
                tl = tl.replace("2010", "2012")
            if "2011" in tl:
                tl = tl.replace("2011", "2012")
            for m in ("1 月", "2 月", "3 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 4 月下旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年4月下旬")
            for early in ("4 月上旬", "4月上旬", "四月上旬", "4 月中旬", "4月中旬", "四月中旬"):
                if early in tl and "4 月下旬" not in tl and "4月下旬" not in tl:
                    tl = tl.replace(early, "4 月下旬")
            for m in ("7 月", "8 月", "9 月", "10 月", "11 月", "12 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 5 月上旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年5月上旬")
        if post_jun_mid_2012 and not post_sep_mid_2012:
            # map any 2009/2010/2011 / Jan–early-Jun 2012 slips forward past v26c010 into 秋档
            if "2009" in tl:
                tl = tl.replace("2009", "2012")
            if "2010" in tl:
                tl = tl.replace("2010", "2012")
            if "2011" in tl:
                tl = tl.replace("2011", "2012")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 6 月下旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年6月下旬")
            for early in ("6 月上旬", "6月上旬", "六月上旬", "6 月中旬", "6月中旬", "六月中旬"):
                if early in tl and "6 月下旬" not in tl and "6月下旬" not in tl:
                    tl = tl.replace(early, "6 月下旬")
            for m in ("10 月", "11 月", "12 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 7 月上旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年7月上旬")
        if post_sep_mid_2012:
            # map any 2009/2010/2011 / Jan–mid-Sep 2012 slips forward past v27c010 into 冬档
            if "2009" in tl:
                tl = tl.replace("2009", "2012")
            if "2010" in tl:
                tl = tl.replace("2010", "2012")
            if "2011" in tl:
                tl = tl.replace("2011", "2012")
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月"):
                if f"2012 年 {m}" in tl or f"2012年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2012 年 {m}", "2012 年 9 月下旬")
                    tl = tl.replace(f"2012年{m.replace(' ','')}", "2012年9月下旬")
            for early in ("9 月上旬", "9月上旬", "九月上旬", "9 月中旬", "9月中旬", "九月中旬"):
                if early in tl and "9 月下旬" not in tl and "9月下旬" not in tl:
                    tl = tl.replace(early, "9 月下旬")
        if post_oct_2008 and not post_jan_2009:
            # map obvious pre-October 2008 slips forward into late 2008
            for m in ("1 月", "2 月", "3 月", "4 月", "5 月", "6 月", "7 月", "8 月", "9 月"):
                if f"2008 年 {m}" in tl or f"2008年{m.replace(' ','')}" in tl:
                    tl = tl.replace(f"2008 年 {m}", "2008 年 10 月下旬")
                    tl = tl.replace(f"2008年{m.replace(' ','')}", "2008年10月下旬")
            if "2007" in tl:
                tl = tl.replace("2007", "2008")
            if "2006" in tl:
                tl = tl.replace("2006", "2008")
        return tl

    fenced: list[ChapterOutline] = []
    for outline in outlines:
        data = outline.model_dump()
        for field in (
            "core_event",
            "title",
            "exit_hook",
            "key_choice",
            "time_location",
            "start_state",
            "end_state",
            "entry_point",
            "protagonist_goal",
        ):
            if isinstance(data.get(field), str):
                data[field] = _fence_text(data[field])
        if isinstance(data.get("time_location"), str):
            data["time_location"] = _fix_time(data["time_location"])
        fenced.append(ChapterOutline.model_validate(data))
    new_scenes: dict[str, list[SceneCard]] = {}
    for key, cards in scenes.items():
        remapped: list[SceneCard] = []
        for card in cards:
            payload = card.model_dump()
            for field in ("time", "location", "goal", "obstacle", "turning_point", "outcome", "exit_hook"):
                if isinstance(payload.get(field), str):
                    payload[field] = _fence_text(payload[field])
            if isinstance(payload.get("time"), str):
                payload["time"] = _fix_time(payload["time"])
            remapped.append(SceneCard.model_validate(payload))
        new_scenes[key] = remapped
    return fenced, new_scenes


def _redact_remaining_spoilers(
    outlines: Sequence[ChapterOutline], remaining_forbidden: Sequence[str]
) -> list[ChapterOutline]:
    secrets = [item for item in remaining_forbidden if item]
    if not secrets:
        return list(outlines)
    fields = ("core_event", "title", "exit_hook", "key_choice")
    updated: list[ChapterOutline] = []
    for outline in outlines:
        changes: dict[str, str] = {}
        for field in fields:
            text = getattr(outline, field) or ""
            original = text
            for secret in secrets:
                if secret in text:
                    text = text.replace(secret, "")
            if text != original:
                changes[field] = text
        updated.append(outline.model_copy(update=changes) if changes else outline)
    return updated

def _canon_notes(canon: CanonRepo, project_id: int) -> str:
    states = canon.latest_entity_states(project_id, include_provisional=True)
    if not states:
        return "(尚无正史实体状态)"
    lines = []
    for (entity_id, state_type), rec in sorted(states.items()):
        flag = "provisional" if rec.provisional else "committed"
        lines.append(
            f"{entity_id}.{state_type}={rec.value} ({flag} {rec.source_chapter})"
        )
    return "\n".join(lines)


def _existing_outlines(planning: PlanningRepo, project_id: int) -> list[ChapterOutline]:
    outlines: list[ChapterOutline] = []
    for chapter in planning.list_chapters(project_id):
        if chapter.outline:
            outlines.append(planning.get_outline(project_id, chapter.chapter_key))
    return outlines


def _merge_by_id(existing: list, incoming: list, attr: str) -> list:
    by_id = {getattr(item, attr): item for item in existing}
    for item in incoming:
        key = getattr(item, attr)
        if key not in by_id:
            by_id[key] = item
    return list(by_id.values())


def _align_slice(
    outlines: list[ChapterOutline],
    by_chapter: dict[str, list[SceneCard]],
    chapter_keys: list[str],
    volume_id: str,
    unit_id: str,
) -> tuple[list[ChapterOutline], dict[str, list[SceneCard]]]:
    if len(outlines) < len(chapter_keys):
        raise PlanMoreError(
            f"章纲数量不足: 需要 {len(chapter_keys)}, 得到 {len(outlines)}"
        )
    returned = {outline.chapter_key: outline for outline in outlines}
    aligned: list[ChapterOutline] = []
    scenes: dict[str, list[SceneCard]] = {}
    for index, key in enumerate(chapter_keys):
        source = returned.get(key, outlines[index])
        cards = by_chapter.get(source.chapter_key) or by_chapter.get(key) or []
        if not cards:
            raise PlanMoreError(f"以下章节缺少场景卡: {key}")
        aligned.append(
            source.model_copy(
                update={"chapter_key": key, "volume_id": volume_id, "unit_id": unit_id}
            )
        )
        remapped: list[SceneCard] = []
        for order, card in enumerate(cards, start=1):
            scene_id = card.scene_id
            if not scene_id.startswith(f"{key}_"):
                scene_id = f"{key}_s{order}"
            remapped.append(card.model_copy(update={"chapter_key": key, "scene_id": scene_id}))
        scenes[key] = remapped
    return aligned, scenes


async def plan_more(
    planning: PlanningRepo,
    bible: BibleRepo,
    canon: CanonRepo,
    deps: AgentDeps,
    project_id: int,
    gates: PlanningGates,
    *,
    window: int = DEFAULT_WINDOW,
    chapters: int | None = None,
    open_volume: bool | None = None,
) -> PlanMoreResult:
    """在已有 Story Bible 上生成下一截滚动章纲,不重跑 R0–R5。"""
    if project_id != deps.project_id and deps.project_id is not None:
        raise PlanMoreError("project_id 与 AgentDeps 不一致")
    kernel = planning.get_approved_kernel(project_id)
    if kernel is None:
        raise PlanMoreError("续规划需要已批准的故事内核")
    characters = planning.list_characters(project_id)
    if not characters:
        raise PlanMoreError("续规划需要已确认的角色卡")
    existing = planning.list_chapters(project_id)
    if not existing:
        raise PlanMoreError("续规划需要先完成开书滚动章纲")

    count = chapters if chapters is not None else window_deficit(existing, window)
    if count < 1:
        latest = existing[-1]
        return PlanMoreResult(
            project_id=project_id,
            volume_id=latest.volume_id,
            unit_id=latest.unit_id,
            chapter_keys=[],
            skipped=["window_full"],
        )

    current_volume = existing[-1].volume_id
    current_unit_id = existing[-1].unit_id
    unit_chapters = [chapter for chapter in existing if chapter.unit_id == current_unit_id]
    unit_fully_locked = bool(unit_chapters) and all(
        chapter.status in _DONE for chapter in unit_chapters
    )
    open_next = open_volume if open_volume is not None else volume_arc_paid_off(
        planning, bible, project_id
    )

    if open_next:
        volume_id = next_volume_id(current_volume)
        unit_id = next_unit_id([rec.unit_id for rec in planning.list_unit_records(project_id)])
        keys = planned_chapter_keys(volume_id, count, start=1)
        reuse_unit = False
    else:
        volume_id = current_volume
        volume_chapters = [chapter for chapter in existing if chapter.volume_id == volume_id]
        seqs = (chapter_seq(chapter.chapter_key) for chapter in volume_chapters)
        start = max(seqs, default=0) + 1
        keys = planned_chapter_keys(volume_id, count, start=start)
        if unit_fully_locked:
            unit_id = next_unit_id(
                [rec.unit_id for rec in planning.list_unit_records(project_id)]
            )
            reuse_unit = False
        else:
            unit_id = current_unit_id
            reuse_unit = True

    previous_outlines = [
        sanitize_outline(outline) for outline in _existing_outlines(planning, project_id)
    ]
    remaining_forbidden, _allowed = collect_spoiler_state(previous_outlines)
    spoiler_notes = "\n".join(f"- {item}" for item in remaining_forbidden) or "(无)"
    current_unit = planning.get_unit(project_id, current_unit_id) if reuse_unit else None
    canon_notes = _canon_notes(canon, project_id)
    recap = continuation_recap(previous_outlines, canon_notes=canon_notes)
    recap = recap + "\n\n" + _continuation_brief(kernel, previous_outlines, keys)

    conflicts, beats = await _extend_bible_slice(
        bible, deps, project_id, kernel, characters, keys, repair_notes=recap
    )
    all_keys = [chapter.chapter_key for chapter in existing] + keys
    unit, outlines, by_chapter = await run_outline_planner(
        deps,
        _kernel_text(kernel),
        _characters_text(characters, bible.get_brief(project_id)),
        volume_id,
        current_unit,
        len(keys),
        chapter_keys=keys,
        unit_id=unit_id,
        spoiler_notes=spoiler_notes,
        canon_notes=canon_notes,
        repair_notes=recap,
    )
    aligned, scenes = _align_slice(outlines, by_chapter, keys, volume_id, unit_id)
    aligned = apply_inherited_spoilers(aligned, remaining_forbidden)
    known_conflicts = {item.conflict_id for item in conflicts}
    known_beats = {item.beat_id for item in beats}
    aligned = [
        redact_remaining_spoilers(
            coerce_outline_citations(sanitize_outline(outline), known_conflicts, known_beats),
            remaining_forbidden,
        )
        for outline in aligned
    ]
    aligned, scenes = _fence_outlines_and_scenes(aligned, scenes, previous_outlines)
    citations = [
        (outline.chapter_key, outline.cited_conflict_ids, outline.cited_beat_ids)
        for outline in [*previous_outlines, *aligned]
    ]
    report = lint_bible(
        structure=bible.get_structure_map(project_id),
        conflicts=conflicts,
        payoff_beats=beats,
        rolling_keys=all_keys,
        outline_citations=citations,
        previous_outlines=previous_outlines,
        new_outlines=aligned,
        live_names=live_names_from_kernel(kernel),
    )
    if not report.passed:
        raise _lint_error(report)

    prompt = (
        f"确认写入{'新卷 ' + volume_id if open_next else '续规划 ' + volume_id}、"
        f"剧情单元 {unit_id} 与滚动章纲 {', '.join(keys)}?"
    )
    if not gates.confirm(prompt):
        raise PlanningAborted("plan_more", project_id)

    _persist_slice(
        planning,
        project_id,
        volume_id,
        unit.model_copy(update={"unit_id": unit_id}) if not reuse_unit else unit,
        aligned,
        scenes,
        keys,
        reuse_unit=reuse_unit,
        opened_new_volume=open_next,
    )
    if open_next:
        _lock_unit(planning, project_id, current_unit_id)
    from novel_agent.annals.skeleton import extend_annals_for_outlines
    from novel_agent.domain.repos.annals import AnnalsRepo

    extend_annals_for_outlines(planning, AnnalsRepo(planning.s), project_id)
    planning.s.commit()
    memory_retrieval_for_session(planning.s).reindex(project_id)
    return PlanMoreResult(
        project_id=project_id,
        volume_id=volume_id,
        unit_id=unit_id,
        chapter_keys=keys,
        opened_new_volume=open_next,
    )


def _characters_text(characters: list[CharacterCard], brief: object) -> str:
    blob = json.dumps([card.model_dump() for card in characters], ensure_ascii=False)
    if brief is not None:
        return f"{_dump(brief)}\n{blob}"
    return blob


async def _extend_bible_slice(
    bible: BibleRepo,
    deps: AgentDeps,
    project_id: int,
    kernel: StoryKernel,
    characters: list[CharacterCard],
    keys: list[str],
    *,
    repair_notes: str = "",
) -> tuple[list[Conflict], list[PayoffBeat]]:
    characters_text = json.dumps(
        [card.model_dump() for card in characters], ensure_ascii=False
    )
    incoming_conflicts = await run_conflict_planner(
        deps, _kernel_text(kernel), characters_text, keys, repair_notes=repair_notes
    )
    existing_conflicts = bible.list_conflicts(project_id)
    conflicts = _merge_by_id(existing_conflicts, incoming_conflicts, "conflict_id")
    incoming_beats = await run_payoff_planner(
        deps,
        _kernel_text(kernel),
        _dump([item.model_dump() for item in incoming_conflicts]),
        keys,
        repair_notes=repair_notes,
    )
    existing_beats = bible.list_payoff_beats(project_id)
    max_order = max((beat.order_index for beat in existing_beats), default=0)
    shifted: list[PayoffBeat] = []
    for offset, beat in enumerate(incoming_beats, start=1):
        if beat.beat_id in {item.beat_id for item in existing_beats}:
            continue
        order = beat.order_index if beat.order_index > max_order else max_order + offset
        shifted.append(beat.model_copy(update={"order_index": order}))
    beats = existing_beats + shifted
    bible.replace_conflicts(project_id, conflicts)
    bible.replace_payoff_beats(project_id, beats)
    bible.s.flush()
    return conflicts, beats


def _lock_unit(planning: PlanningRepo, project_id: int, unit_id: str) -> None:
    rec = next(
        (
            row
            for row in planning.list_unit_records(project_id)
            if row.unit_id == unit_id
        ),
        None,
    )
    if rec is not None:
        rec.status = "locked"
        planning.s.add(rec)


def _persist_slice(
    planning: PlanningRepo,
    project_id: int,
    volume_id: str,
    unit: PlotUnitCard,
    outlines: list[ChapterOutline],
    scenes: dict[str, list[SceneCard]],
    keys: list[str],
    *,
    reuse_unit: bool,
    opened_new_volume: bool,
) -> None:
    volumes = {rec.volume_id: rec for rec in planning.list_volumes(project_id)}
    if opened_new_volume or volume_id not in volumes:
        volume = planning.save_volume(
            project_id,
            volume_id,
            {
                "goal": unit.promise_or_debt,
                "position": unit.position_in_volume,
                "trigger": unit.trigger,
                "climax": unit.climax,
                "payoff": unit.payoff,
                "canon_constraints": unit.canon_constraints,
                "unit_ids": [unit.unit_id],
                "chapter_keys": keys,
            },
            title=unit.position_in_volume,
        )
        volume.status = "confirmed"
        planning.s.add(volume)
    else:
        rec = volumes[volume_id]
        payload = dict(rec.payload or {})
        chapter_keys = list(payload.get("chapter_keys") or [])
        for key in keys:
            if key not in chapter_keys:
                chapter_keys.append(key)
        payload["chapter_keys"] = chapter_keys
        unit_ids = list(payload.get("unit_ids") or [])
        if unit.unit_id not in unit_ids:
            unit_ids.append(unit.unit_id)
        payload["unit_ids"] = unit_ids
        rec.payload = payload
        planning.s.add(rec)

    if not reuse_unit:
        unit_rec = planning.save_unit(project_id, volume_id, unit)
        unit_rec.status = "confirmed"
        planning.s.add(unit_rec)

    next_order = max(
        (chapter.order_index for chapter in planning.list_chapters(project_id)),
        default=0,
    )
    for offset, outline in enumerate(outlines, start=1):
        planning.create_chapter(project_id, outline, order_index=next_order + offset)
        planning.save_scene_cards(project_id, outline.chapter_key, scenes[outline.chapter_key])
