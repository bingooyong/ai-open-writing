"""Stage 2 检索评测:冻结金标 + 离线 runner。

默认 HashEmbedding,走生产 `MemoryRetrieval.retrieve`(Lance 距离 + 词面重叠)。
另报一套词面-only 对照,用来判断 hash 向量有没有超出字面匹配的贡献。
不改正史,不另建检索管线。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session

from novel_agent.domain.db import build_engine, create_all, session_scope
from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.repos.production import ProductionRepo
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
from novel_agent.memory.collect import collect_indexable_facts
from novel_agent.memory.embeddings import EmbeddingProvider, HashEmbedding, lexical_overlap
from novel_agent.memory.factory import index_dir_for_session
from novel_agent.memory.protocol import MemoryFact
from novel_agent.memory.service import LocalMemoryRetrieval
from novel_agent.memory.store import LanceMemoryStore

# HashEmbedding + 生产混合打分,在冻结金标上的文档化下限。
# 实测见 docs/retrieval-eval.md;pytest 锁此下限。默认 CI 不得打付费嵌入。
HASH_MIN_RECALL_AT_1 = 0.40
HASH_MIN_RECALL_AT_3 = 0.70
HASH_MIN_HIT_RATE = 0.85
HASH_MIN_MRR = 0.55

# 字面/近字面问句:hash 混合必须在 Top-3 命中。改检索或金标时先看这组。
HASH_MUST_HIT_AT_3 = (
    "entity-fire-literal",
    "character-su-identity",
    "alias-nickname",
    "relationship-siblings",
    "relationship-threat",
    "scene-teahouse",
    "scene-yamen",
    "conflict-bureau",
    "payoff-cost",
)

_DEFAULT_KS = (1, 3, 8)


@dataclass(frozen=True, slots=True)
class ExpectSpec:
    keywords: tuple[str, ...] = ()
    fact_id_prefixes: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NegativeSpec:
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    id: str
    category: str
    query: str
    expect: ExpectSpec
    negatives: NegativeSpec = NegativeSpec()


@dataclass(frozen=True, slots=True)
class GoldenSet:
    version: int
    description: str
    ks: tuple[int, ...]
    queries: tuple[GoldenQuery, ...]


@dataclass(frozen=True, slots=True)
class HitView:
    fact_id: str
    kind: str
    score: float
    lexical: float
    vector_est: float
    text: str
    relevant: bool
    pollutant: bool


@dataclass(frozen=True, slots=True)
class QueryRow:
    id: str
    category: str
    query: str
    first_relevant_rank: int | None
    recall_at: dict[int, bool]
    pollution_at: dict[int, bool]
    lexical_first_relevant_rank: int | None
    hits: tuple[HitView, ...]


@dataclass(frozen=True, slots=True)
class EvalReport:
    embedder: str
    indexed: int
    n_queries: int
    recall_at: dict[int, float]
    hit_rate: float
    mrr: float
    pollution_at: dict[int, float]
    lexical_recall_at: dict[int, float]
    queries: tuple[QueryRow, ...]


def default_golden_path() -> Path:
    here = Path(__file__).resolve()
    candidates = (
        Path.cwd() / "eval" / "retrieval" / "golden_queries.json",
        here.parents[3] / "eval" / "retrieval" / "golden_queries.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("找不到 eval/retrieval/golden_queries.json")


def load_golden(path: Path) -> GoldenSet:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("金标文件必须是对象")
    queries_raw = raw.get("queries")
    if not isinstance(queries_raw, list) or not queries_raw:
        raise ValueError("金标文件缺少 queries")
    ks_raw = raw.get("ks") or list(_DEFAULT_KS)
    if not isinstance(ks_raw, list) or not ks_raw:
        raise ValueError("ks 必须是正整数列表")
    ks = tuple(int(item) for item in ks_raw)
    queries = tuple(_parse_query(item) for item in queries_raw)
    return GoldenSet(
        version=int(raw.get("version") or 1),
        description=str(raw.get("description") or ""),
        ks=ks,
        queries=queries,
    )


def _parse_query(raw: object) -> GoldenQuery:
    if not isinstance(raw, dict):
        raise ValueError("query 必须是对象")
    query_id = str(raw.get("id") or "").strip()
    query = str(raw.get("query") or "").strip()
    category = str(raw.get("category") or "").strip()
    if not query_id or not query or not category:
        raise ValueError("query 需要 id / category / query")
    expect_raw = raw.get("expect") or {}
    negatives_raw = raw.get("negatives") or {}
    if not isinstance(expect_raw, dict) or not isinstance(negatives_raw, dict):
        raise ValueError(f"{query_id}: expect/negatives 必须是对象")
    expect = ExpectSpec(
        keywords=_str_tuple(expect_raw.get("keywords")),
        fact_id_prefixes=_str_tuple(expect_raw.get("fact_id_prefixes")),
        kinds=_str_tuple(expect_raw.get("kinds")),
    )
    if not expect.keywords and not expect.fact_id_prefixes:
        raise ValueError(f"{query_id}: expect 至少要有 keywords 或 fact_id_prefixes")
    return GoldenQuery(
        id=query_id,
        category=category,
        query=query,
        expect=expect,
        negatives=NegativeSpec(keywords=_str_tuple(negatives_raw.get("keywords"))),
    )


def _str_tuple(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("列表字段必须是数组")
    return tuple(str(item) for item in value if str(item).strip())


def _as_expect(expect: ExpectSpec | Mapping[str, object]) -> ExpectSpec:
    if isinstance(expect, ExpectSpec):
        return expect
    return ExpectSpec(
        keywords=_str_tuple(expect.get("keywords")),
        fact_id_prefixes=_str_tuple(expect.get("fact_id_prefixes")),
        kinds=_str_tuple(expect.get("kinds")),
    )


def _as_negatives(negatives: NegativeSpec | Mapping[str, object]) -> NegativeSpec:
    if isinstance(negatives, NegativeSpec):
        return negatives
    return NegativeSpec(keywords=_str_tuple(negatives.get("keywords")))


def is_relevant(fact: MemoryFact, expect: ExpectSpec | Mapping[str, object]) -> bool:
    spec = _as_expect(expect)
    if spec.keywords and not any(keyword in fact.text for keyword in spec.keywords):
        return False
    if spec.fact_id_prefixes and not any(
        fact.fact_id.startswith(prefix) for prefix in spec.fact_id_prefixes
    ):
        return False
    if spec.kinds and fact.kind.value not in spec.kinds:
        return False
    return bool(spec.keywords or spec.fact_id_prefixes or spec.kinds)


def is_pollutant(
    fact: MemoryFact,
    expect: ExpectSpec | Mapping[str, object],
    negatives: NegativeSpec | Mapping[str, object],
) -> bool:
    if is_relevant(fact, expect):
        return False
    spec = _as_negatives(negatives)
    return any(keyword in fact.text for keyword in spec.keywords)


def first_relevant_rank(
    hits: Sequence[MemoryFact], expect: ExpectSpec | Mapping[str, object]
) -> int | None:
    for index, fact in enumerate(hits, start=1):
        if is_relevant(fact, expect):
            return index
    return None


def seed_golden_project(session: Session) -> int:
    """植入覆盖人物/关系/场景/冲突/爽点/摘要的确定性评测项目。"""
    planning = PlanningRepo(session)
    project = planning.create_project("检索评测金标", boundaries=["评测语料,非正文"])
    assert project.id is not None
    project_id = project.id
    planning.save_kernel(project_id, StoryKernel.model_validate(_KERNEL))
    planning.approve_kernel(project_id, 1)
    for card in _CHARACTERS:
        planning.upsert_character(project_id, CharacterCard.model_validate(card))
    planning.save_volume(project_id, "v1", {"summary": "第一卷:故事成真的开局"})
    planning.save_unit(project_id, "v1", PlotUnitCard.model_validate(_UNIT))
    planning.create_chapter(project_id, ChapterOutline.model_validate(_OUTLINE), order_index=1)
    planning.save_scene_cards(
        project_id,
        "v1c001",
        [SceneCard.model_validate(item) for item in _SCENES],
    )
    bible = BibleRepo(session)
    bible.replace_conflicts(project_id, [Conflict.model_validate(_CONFLICT)])
    bible.replace_payoff_beats(project_id, [PayoffBeat.model_validate(_PAYOFF)])
    canon = CanonRepo(session)
    for entity_id, state_type, value, reason, chapter in _ENTITY_STATES:
        canon.append_entity_state(project_id, entity_id, state_type, value, reason, chapter)
    for party_a, party_b, state, evidence, chapter in _RELATIONSHIPS:
        canon.upsert_relationship(project_id, party_a, party_b, state, evidence, chapter)
    production = ProductionRepo(session)
    production.create_draft(
        project_id,
        "v1c001",
        "candidate_eval",
        "eval-line",
        "评测用正文不进入检索索引。",
        {"chapter_summary": "说书人随口编的西市失火次日成真,衙役上门问罪"},
        "eval",
        1,
    )
    planning.set_status(project_id, "v1c001", ChapterStatus.CANON_LOCKED)
    return project_id


def run_retrieval_eval(
    session: Session,
    golden: Path | GoldenSet,
    *,
    embedder: EmbeddingProvider | None = None,
    ks: tuple[int, ...] | None = None,
    limit: int = 8,
) -> EvalReport:
    payload = golden if isinstance(golden, GoldenSet) else load_golden(golden)
    ranks = ks or payload.ks or _DEFAULT_KS
    used_embedder = embedder or HashEmbedding()
    project_id = seed_golden_project(session)
    retrieval = LocalMemoryRetrieval(
        session,
        LanceMemoryStore(index_dir_for_session(session)),
        used_embedder,
    )
    indexed = retrieval.reindex(project_id)
    catalog = collect_indexable_facts(
        project_id,
        PlanningRepo(session),
        CanonRepo(session),
        BibleRepo(session),
        ProductionRepo(session),
    )
    rows = [
        _score_query(retrieval, project_id, item, catalog, ranks, limit) for item in payload.queries
    ]
    return EvalReport(
        embedder=_embedder_label(used_embedder),
        indexed=indexed,
        n_queries=len(rows),
        recall_at=_mean_flags(rows, ranks, hybrid=True),
        hit_rate=_mean_flag(rows, max(ranks), hybrid=True),
        mrr=_mean_mrr(rows),
        pollution_at=_mean_pollution(rows, ranks),
        lexical_recall_at=_mean_flags(rows, ranks, hybrid=False),
        queries=tuple(rows),
    )


def run_eval_on_temp_db(
    golden: Path,
    work_dir: Path,
    *,
    embedder: EmbeddingProvider | None = None,
) -> EvalReport:
    engine = build_engine(work_dir / "eval.db")
    create_all(engine)
    with session_scope(engine) as session:
        return run_retrieval_eval(session, golden, embedder=embedder)


def format_report(*reports: EvalReport) -> str:
    if not reports:
        raise ValueError("至少需要一份评测报告")
    chunks = [_format_one(report) for report in reports]
    if len(reports) == 2:
        chunks.append(_format_compare(reports[0], reports[1]))
    return "\n".join(chunks).rstrip() + "\n"


def _format_one(report: EvalReport) -> str:
    lines = [
        f"# 检索评测（{report.embedder}）",
        "",
        f"- 索引条数: {report.indexed}",
        f"- 问句数: {report.n_queries}",
        f"- hit_rate(=recall@{max(report.recall_at)}): {report.hit_rate:.3f}",
        f"- MRR: {report.mrr:.3f}",
    ]
    for k in sorted(report.recall_at):
        lines.append(f"- recall@{k}: {report.recall_at[k]:.3f}")
    for k in sorted(report.lexical_recall_at):
        lines.append(f"- lexical-only recall@{k}: {report.lexical_recall_at[k]:.3f}")
    for k in sorted(report.pollution_at):
        lines.append(f"- pollution@{k}（负例进 Top-k）: {report.pollution_at[k]:.3f}")
    lines.extend(["", "## 逐问", ""])
    for row in report.queries:
        rank = row.first_relevant_rank if row.first_relevant_rank is not None else "miss"
        lex = (
            row.lexical_first_relevant_rank
            if row.lexical_first_relevant_rank is not None
            else "miss"
        )
        flags = " ".join(
            f"@{k}={'Y' if row.recall_at[k] else 'N'}" for k in sorted(row.recall_at)
        )
        lines.append(f"### {row.id} ({row.category})")
        lines.append(f"- 问句: {row.query}")
        lines.append(f"- 混合首中: {rank}; 词面首中: {lex}; {flags}")
        for index, hit in enumerate(row.hits, start=1):
            mark = "hit" if hit.relevant else ("neg" if hit.pollutant else "   ")
            preview = hit.text.replace("\n", " ")[:80]
            lines.append(
                f"  {index}. [{mark}] {hit.fact_id} kind={hit.kind} "
                f"hybrid={hit.score:.3f} lex={hit.lexical:.3f} vec={hit.vector_est:.3f}"
            )
            lines.append(f"     {preview}")
        lines.append("")
    return "\n".join(lines)


def _format_compare(left: EvalReport, right: EvalReport) -> str:
    lines = [
        "# 对照",
        "",
        f"| 指标 | {left.embedder} | {right.embedder} |",
        "|---|---:|---:|",
        f"| hit_rate | {left.hit_rate:.3f} | {right.hit_rate:.3f} |",
        f"| MRR | {left.mrr:.3f} | {right.mrr:.3f} |",
    ]
    for k in sorted(set(left.recall_at) | set(right.recall_at)):
        lines.append(
            f"| recall@{k} | {left.recall_at.get(k, 0.0):.3f} | {right.recall_at.get(k, 0.0):.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


def _score_query(
    retrieval: LocalMemoryRetrieval,
    project_id: int,
    item: GoldenQuery,
    catalog: Sequence[MemoryFact],
    ks: tuple[int, ...],
    limit: int,
) -> QueryRow:
    hits = retrieval.retrieve(project_id, item.query, limit=limit)
    views = tuple(_view(hit, item) for hit in hits)
    rank = first_relevant_rank(hits, item.expect)
    lexical_rank = first_relevant_rank(_lexical_rank(catalog, item.query, limit), item.expect)
    return QueryRow(
        id=item.id,
        category=item.category,
        query=item.query,
        first_relevant_rank=rank,
        recall_at={k: rank is not None and rank <= k for k in ks},
        pollution_at={
            k: any(view.pollutant for view in views[:k]) for k in ks
        },
        lexical_first_relevant_rank=lexical_rank,
        hits=views,
    )


def _view(fact: MemoryFact, item: GoldenQuery) -> HitView:
    lexical = lexical_overlap(item.query, fact.text)
    return HitView(
        fact_id=fact.fact_id,
        kind=fact.kind.value,
        score=fact.score,
        lexical=lexical,
        vector_est=fact.score - lexical,
        text=fact.text,
        relevant=is_relevant(fact, item.expect),
        pollutant=is_pollutant(fact, item.expect, item.negatives),
    )


def _lexical_rank(catalog: Sequence[MemoryFact], query: str, limit: int) -> list[MemoryFact]:
    scored = [(lexical_overlap(query, fact.text), fact) for fact in catalog if not fact.provisional]
    scored.sort(key=lambda item: (-item[0], item[1].fact_id))
    return [fact for _, fact in scored[:limit]]


def _mean_flag(rows: Sequence[QueryRow], k: int, *, hybrid: bool) -> float:
    if not rows:
        return 0.0
    if hybrid:
        hits = sum(1 for row in rows if row.recall_at.get(k))
    else:
        hits = sum(
            1
            for row in rows
            if row.lexical_first_relevant_rank is not None and row.lexical_first_relevant_rank <= k
        )
    return hits / len(rows)


def _mean_flags(rows: Sequence[QueryRow], ks: tuple[int, ...], *, hybrid: bool) -> dict[int, float]:
    return {k: _mean_flag(rows, k, hybrid=hybrid) for k in ks}


def _mean_pollution(rows: Sequence[QueryRow], ks: tuple[int, ...]) -> dict[int, float]:
    if not rows:
        return {k: 0.0 for k in ks}
    return {k: sum(1 for row in rows if row.pollution_at.get(k)) / len(rows) for k in ks}


def _mean_mrr(rows: Sequence[QueryRow]) -> float:
    if not rows:
        return 0.0
    total = 0.0
    for row in rows:
        total += (1.0 / row.first_relevant_rank) if row.first_relevant_rank else 0.0
    return total / len(rows)


def _embedder_label(embedder: EmbeddingProvider) -> str:
    name = type(embedder).__name__
    if name == "HashEmbedding":
        return "hash"
    if name == "OpenAICompatEmbedding":
        return "openai_compat"
    return name


def _character(
    character_id: str,
    name: str,
    identity: str,
    story_function: str,
    *,
    goal: str,
    need: str,
    motivation: str,
    fear: str,
    start: str,
    end: str,
) -> dict[str, str]:
    return {
        "character_id": character_id,
        "name": name,
        "identity": identity,
        "story_function": story_function,
        "external_goal": goal,
        "internal_need": need,
        "motivation": motivation,
        "fear": fear,
        "start_state": start,
        "end_state": end,
    }


_KERNEL = dict(
    premise="如果一个说书人发现自己讲的故事会成真",
    logline="落魄说书人为救妹妹,用会成真的故事对抗操纵命运的书局",
    theme_question="讲故事的人有没有权力改写别人的命运",
    dramatic_question="他能否在不牺牲无辜者的前提下救回妹妹",
    value_shift="从逃避责任到承担叙述的代价",
    ending_proof="他烧掉能成真的书,用凡人方式完成救赎",
    reader_promise="每卷一个成真故事引发的连锁危机与反转",
)

_CHARACTERS = (
    _character(
        "ch_su",
        "苏晚生",
        "临安城茶楼说书人",
        "主角",
        goal="赎回被书局扣押的妹妹",
        need="承认自己无法置身故事之外",
        motivation="妹妹是他唯一亲人",
        fear="自己的话害死无辜者",
        start="只求糊口、回避是非",
        end="接受叙述者的责任",
    ),
    _character(
        "ch_mei",
        "苏棠",
        "被扣在纸坊的质人",
        "亲人",
        goal="活着离开书局纸坊",
        need="不再被当成筹码",
        motivation="相信哥哥会来",
        fear="被写成故事里的祭品",
        start="茶楼后厨帮工",
        end="重获自由但仍怕评书",
    ),
    _character(
        "ch_clerk",
        "沈衡",
        "书局执事",
        "对手",
        goal="收编能改命的说书人",
        need="证明书局能定价命运",
        motivation="完成东家的配额",
        fear="漏掉一个会改命的人",
        start="冷脸收账",
        end="被自己的契约反噬",
    ),
)

_UNIT = dict(
    unit_id="u1",
    position_in_volume="第一卷开局单元(1-5章)",
    promise_or_debt="兑现'故事成真'的核心设定展示",
    trigger="随口编的失火故事次日成真",
    protagonist_goal="查明故事为何成真并撇清嫌疑",
    opposition="书局执事以纵火案胁迫他签约",
    escalation_beats=["成真范围扩大", "官府介入", "妹妹被扣为质"],
    midpoint_change="发现书局早知他的能力",
    irreversible_choice="签下卖身契换妹妹平安",
    climax="第一次主动讲述一个救人的故事",
    payoff="能力规则首次明确:代价由讲述者承担",
)

_OUTLINE = dict(
    chapter_key="v1c001",
    volume_id="v1",
    unit_id="u1",
    core_event="说书人随口编的故事一夜成真",
    pov="苏晚生",
    time_location="临安城,春夜茶楼",
    protagonist_goal="讲完今晚的书换到赏钱",
    key_choice="为博彩头临场编造失火桥段",
    start_state="穷困但平静",
    end_state="被卷入失火案,平静破碎",
    emotion_shift="轻快→惊惧",
    entry_point="茶楼满座,他抛出新故事",
    exit_hook="衙役上门:昨夜西市果然失火",
    target_words=3000,
)

_SCENES = (
    dict(
        scene_id="v1c001_s1",
        chapter_key="v1c001",
        pov="苏晚生",
        time="春夜",
        location="临安茶楼",
        entry_state="听众渐散,赏钱寥寥",
        goal="用新桥段留住客人",
        obstacle="老听客嫌故事陈旧起哄",
        stakes="今晚赏钱与说书名声",
        turning_point="他临场编出西市失火的新段子",
        choice="不顾忌讳把火写到真实街巷",
        outcome="满堂彩,赏钱翻倍",
        emotional_shift="窘迫→得意",
        word_budget=1200,
    ),
    dict(
        scene_id="v1c001_s2",
        chapter_key="v1c001",
        pov="苏晚生",
        time="次日清晨",
        location="茶楼门口",
        entry_state="还在回味满堂彩",
        goal="把昨夜的段子再讲一遍换钱",
        obstacle="衙役堵住门口不让开张",
        stakes="纵火嫌疑与茶楼招牌",
        turning_point="衙役上门宣布昨夜西市果然失火",
        choice="承认段子是自己编的",
        outcome="被带去问话,平静碎掉",
        emotional_shift="得意→惊惧",
        word_budget=1000,
    ),
)

_CONFLICT = dict(
    conflict_id="cf_bureau",
    kind="interest",
    parties=["ch_su", "ch_clerk"],
    stake="苏晚生与书局争夺故事成真的解释权,赌注是妹妹自由与全城安危",
    temperature="rising",
    must_affect="both",
    payoff_chapter_key="v1c005",
)

_PAYOFF = dict(
    beat_id="pf_cost",
    scale="small",
    kind="reveal",
    pressure_before="被当众点名纵火",
    hit="能力规则首次明确:代价由讲述者承担",
    chapter_key="v1c001",
    unit_id="u1",
    order_index=1,
)

_ENTITY_STATES: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "ch_su",
        "identity",
        "苏晚生,临安城茶楼说书人,外号晚生说书",
        "开局身份",
        "v1c001",
    ),
    (
        "ch_su",
        "fact",
        "西市火灾由说书人昨夜随口编造的桥段成真",
        "开局植入",
        "v1c001",
    ),
    ("ch_su", "status", "被卷入西市火灾案", "正史提交", "v1c001"),
    (
        "ch_mei",
        "identity",
        "苏棠,苏晚生的妹妹,被书局扣在纸坊作质",
        "人质线",
        "v1c001",
    ),
    (
        "ch_clerk",
        "identity",
        "书局执事沈衡,专收能改命的说书人",
        "对手登场",
        "v1c001",
    ),
    (
        "ch_unrelated",
        "fact",
        "北境商队走失三头骆驼与本书无关",
        "闲笔",
        "v9c099",
    ),
)

_RELATIONSHIPS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ch_su", "ch_mei", "兄妹相依,苏棠是他唯一亲人", "开局关系", "v1c001"),
    ("ch_su", "ch_clerk", "沈衡以西市纵火案胁迫苏晚生签约卖身", "开局施压", "v1c001"),
)
