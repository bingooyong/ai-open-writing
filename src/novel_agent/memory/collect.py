"""从 SQLite 真源收集可索引事实。不读 .env,不收录密钥或正文全文。"""

from __future__ import annotations

from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.repos.production import ProductionRepo
from novel_agent.domain.schemas import ChapterOutline, ChapterStatus
from novel_agent.memory.protocol import FactKind, MemoryFact

_LOCKED = frozenset(
    {ChapterStatus.CANON_LOCKED, ChapterStatus.APPROVED, ChapterStatus.EXPORTED}
)


def collect_indexable_facts(
    project_id: int,
    planning: PlanningRepo,
    canon: CanonRepo,
    bible: BibleRepo,
    production: ProductionRepo,
) -> list[MemoryFact]:
    """收集已提交事实,并附带标记好的提案态副本(检索时再过滤)。"""
    facts: list[MemoryFact] = []
    facts.extend(_chapter_summaries(project_id, planning, production))
    facts.extend(_entity_facts(project_id, canon))
    facts.extend(_relationship_facts(project_id, canon))
    facts.extend(_scene_facts(project_id, planning))
    facts.extend(_payoff_facts(project_id, bible))
    facts.extend(_conflict_facts(project_id, bible))
    facts.sort(key=lambda fact: fact.fact_id)
    return facts


def _chapter_summaries(
    project_id: int, planning: PlanningRepo, production: ProductionRepo
) -> list[MemoryFact]:
    facts: list[MemoryFact] = []
    for chapter in planning.list_chapters(project_id):
        outline = ChapterOutline.model_validate(chapter.outline)
        core = outline.core_event.strip()
        if core:
            facts.append(
                MemoryFact(
                    fact_id=f"summary:outline:{chapter.chapter_key}",
                    text=f"章纲 {chapter.chapter_key}: {core}",
                    kind=FactKind.SUMMARY,
                    source=chapter.chapter_key,
                )
            )
        draft = production.latest_chapter_draft(project_id, chapter.chapter_key)
        summary = ""
        if draft is not None:
            raw = (draft.meta or {}).get("chapter_summary")
            if isinstance(raw, str):
                summary = raw.strip()
        if summary:
            facts.append(
                MemoryFact(
                    fact_id=f"summary:draft:{chapter.chapter_key}",
                    text=f"章摘要 {chapter.chapter_key}: {summary}",
                    kind=FactKind.SUMMARY,
                    source=chapter.chapter_key,
                    provisional=chapter.status not in _LOCKED,
                )
            )
    return facts


def _entity_facts(project_id: int, canon: CanonRepo) -> list[MemoryFact]:
    facts: list[MemoryFact] = []
    committed = canon.latest_entity_states(project_id, include_provisional=False)
    latest = canon.latest_entity_states(project_id, include_provisional=True)
    for (entity_id, state_type), record in sorted(committed.items()):
        value = record.value.strip()
        if not value:
            continue
        reason = f"（{record.reason}）" if record.reason else ""
        facts.append(
            MemoryFact(
                fact_id=f"entity:{entity_id}:{state_type}",
                text=f"{entity_id}.{state_type}: {value}{reason}",
                kind=FactKind.ENTITY,
                source=record.source_chapter,
            )
        )
    for (entity_id, state_type), record in sorted(latest.items()):
        if not record.provisional:
            continue
        value = record.value.strip()
        if not value:
            continue
        reason = f"（{record.reason}）" if record.reason else ""
        facts.append(
            MemoryFact(
                fact_id=f"entity:{entity_id}:{state_type}:provisional",
                text=f"{entity_id}.{state_type}: {value}{reason}",
                kind=FactKind.ENTITY,
                source=record.source_chapter,
                provisional=True,
            )
        )
    return facts


def _relationship_facts(project_id: int, canon: CanonRepo) -> list[MemoryFact]:
    facts: list[MemoryFact] = []
    for rel in canon.list_relationships(project_id):
        state = rel.state.strip()
        if not state:
            continue
        evidence = f"（{rel.evidence}）" if rel.evidence else ""
        suffix = ":provisional" if rel.provisional else ""
        facts.append(
            MemoryFact(
                fact_id=f"relationship:{rel.party_a}:{rel.party_b}{suffix}",
                text=f"关系 {rel.party_a}/{rel.party_b}: {state}{evidence}",
                kind=FactKind.RELATIONSHIP,
                source=rel.source_chapter,
                provisional=rel.provisional,
            )
        )
    return facts


def _scene_facts(project_id: int, planning: PlanningRepo) -> list[MemoryFact]:
    facts: list[MemoryFact] = []
    for chapter in planning.list_chapters(project_id):
        for card in planning.list_scene_cards(project_id, chapter.chapter_key):
            line = f"{card.goal} → {card.turning_point} → {card.outcome}".strip()
            if not line.strip(" →"):
                continue
            facts.append(
                MemoryFact(
                    fact_id=f"scene:{card.scene_id}",
                    text=f"场景 {card.scene_id}: {line}",
                    kind=FactKind.SCENE,
                    source=card.chapter_key,
                )
            )
    return facts


def _payoff_facts(project_id: int, bible: BibleRepo) -> list[MemoryFact]:
    facts: list[MemoryFact] = []
    for beat in bible.list_payoff_beats(project_id):
        hit = beat.hit.strip()
        if not hit:
            continue
        facts.append(
            MemoryFact(
                fact_id=f"payoff:{beat.beat_id}",
                text=f"爽点 {beat.beat_id}: {hit}",
                kind=FactKind.PAYOFF,
                source=beat.chapter_key or beat.unit_id,
            )
        )
    return facts


def _conflict_facts(project_id: int, bible: BibleRepo) -> list[MemoryFact]:
    facts: list[MemoryFact] = []
    for conflict in bible.list_conflicts(project_id):
        stake = conflict.stake.strip()
        if not stake:
            continue
        facts.append(
            MemoryFact(
                fact_id=f"conflict:{conflict.conflict_id}",
                text=f"冲突 {conflict.conflict_id}: {stake}",
                kind=FactKind.CONFLICT,
                source=conflict.payoff_chapter_key or conflict.conflict_id,
            )
        )
    return facts
