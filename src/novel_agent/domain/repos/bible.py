"""Story Bible 仓储:简报、结构图、冲突、爽点、异名与轮次完成检测。"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlmodel import Session, select

from novel_agent.domain.models import (
    ChapterRecord,
    CharacterRecord,
    ConflictRecord,
    IdentityAliasRecord,
    PayoffBeatRecord,
    ProjectRecord,
    StoryKernelRecord,
    StructureMapRecord,
)
from novel_agent.domain.schemas import (
    Conflict,
    IdentityAlias,
    PayoffBeat,
    StoryBrief,
    StructureMap,
)


class BibleRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    def save_brief(self, project_id: int, brief: StoryBrief) -> None:
        project = self.s.get_one(ProjectRecord, project_id)
        project.spark = brief.spark
        project.brief = json.dumps(brief.model_dump(), ensure_ascii=False)
        self.s.add(project)

    def get_brief(self, project_id: int) -> StoryBrief | None:
        project = self.s.get_one(ProjectRecord, project_id)
        raw = (project.brief or "").strip()
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        try:
            return StoryBrief.model_validate(payload)
        except ValidationError:
            return None

    def save_structure_map(self, project_id: int, structure: StructureMap) -> StructureMapRecord:
        prev = self.s.exec(
            select(StructureMapRecord)
            .where(StructureMapRecord.project_id == project_id)
            .order_by(StructureMapRecord.version.desc())  # type: ignore[attr-defined]
        ).first()
        rec = StructureMapRecord(
            project_id=project_id,
            version=(prev.version + 1) if prev else 1,
            payload=structure.model_dump(),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_structure_map(self, project_id: int) -> StructureMap | None:
        rec = self.s.exec(
            select(StructureMapRecord)
            .where(StructureMapRecord.project_id == project_id)
            .order_by(StructureMapRecord.version.desc())  # type: ignore[attr-defined]
        ).first()
        return StructureMap.model_validate(rec.payload) if rec else None

    def replace_conflicts(self, project_id: int, conflicts: list[Conflict]) -> None:
        existing = self.s.exec(
            select(ConflictRecord).where(ConflictRecord.project_id == project_id)
        ).all()
        for rec in existing:
            self.s.delete(rec)
        for conflict in conflicts:
            self.s.add(
                ConflictRecord(
                    project_id=project_id,
                    conflict_id=conflict.conflict_id,
                    payload=conflict.model_dump(),
                )
            )
        self.s.flush()

    def list_conflicts(self, project_id: int) -> list[Conflict]:
        recs = self.s.exec(
            select(ConflictRecord)
            .where(ConflictRecord.project_id == project_id)
            .order_by(ConflictRecord.conflict_id)  # type: ignore[attr-defined]
        ).all()
        return [Conflict.model_validate(rec.payload) for rec in recs]

    def replace_payoff_beats(self, project_id: int, beats: list[PayoffBeat]) -> None:
        existing = self.s.exec(
            select(PayoffBeatRecord).where(PayoffBeatRecord.project_id == project_id)
        ).all()
        for rec in existing:
            self.s.delete(rec)
        for beat in beats:
            self.s.add(
                PayoffBeatRecord(
                    project_id=project_id,
                    beat_id=beat.beat_id,
                    order_index=beat.order_index,
                    payload=beat.model_dump(),
                )
            )
        self.s.flush()

    def list_payoff_beats(self, project_id: int) -> list[PayoffBeat]:
        recs = self.s.exec(
            select(PayoffBeatRecord)
            .where(PayoffBeatRecord.project_id == project_id)
            .order_by(PayoffBeatRecord.order_index, PayoffBeatRecord.beat_id)  # type: ignore[arg-type]
        ).all()
        return [PayoffBeat.model_validate(rec.payload) for rec in recs]

    def list_aliases(self, project_id: int) -> list[IdentityAlias]:
        recs = self.s.exec(
            select(IdentityAliasRecord)
            .where(IdentityAliasRecord.project_id == project_id)
            .order_by(IdentityAliasRecord.alias)  # type: ignore[attr-defined]
        ).all()
        return [
            IdentityAlias(canonical_character_id=rec.canonical_character_id, alias=rec.alias)
            for rec in recs
        ]

    def upsert_alias(self, project_id: int, alias: IdentityAlias) -> IdentityAliasRecord:
        if alias.alias == alias.canonical_character_id:
            raise ValueError("alias must not equal canonical_character_id")
        graph = {item.alias: item.canonical_character_id for item in self.list_aliases(project_id)}
        graph[alias.alias] = alias.canonical_character_id
        seen: set[str] = set()
        node = alias.alias
        while node in graph:
            if node in seen:
                raise ValueError("alias cycle")
            seen.add(node)
            node = graph[node]
        rec = self.s.exec(
            select(IdentityAliasRecord).where(
                IdentityAliasRecord.project_id == project_id,
                IdentityAliasRecord.alias == alias.alias,
            )
        ).first()
        if rec:
            rec.canonical_character_id = alias.canonical_character_id
        else:
            rec = IdentityAliasRecord(
                project_id=project_id,
                canonical_character_id=alias.canonical_character_id,
                alias=alias.alias,
            )
        self.s.add(rec)
        self.s.flush()
        return rec

    def delete_alias(self, project_id: int, alias: str) -> None:
        rec = self.s.exec(
            select(IdentityAliasRecord).where(
                IdentityAliasRecord.project_id == project_id,
                IdentityAliasRecord.alias == alias,
            )
        ).first()
        if rec is not None:
            self.s.delete(rec)

    def round_complete(self, project_id: int) -> set[str]:
        done: set[str] = set()
        if self.get_brief(project_id) is not None:
            done.add("R0")
        approved = self.s.exec(
            select(StoryKernelRecord).where(
                StoryKernelRecord.project_id == project_id,
                StoryKernelRecord.approved == True,  # noqa: E712
            )
        ).first()
        if approved is not None:
            done.add("R1")
        if self.get_structure_map(project_id) is not None:
            done.add("R2")
        has_character = self.s.exec(
            select(CharacterRecord).where(CharacterRecord.project_id == project_id)
        ).first()
        if has_character is not None:
            done.add("R3")
        if self.list_conflicts(project_id) and self.list_payoff_beats(project_id):
            done.add("R4")
        has_chapter = self.s.exec(
            select(ChapterRecord).where(ChapterRecord.project_id == project_id)
        ).first()
        if has_chapter is not None:
            done.add("R5")
        return done
