"""规划链仓储:项目/内核/角色/卷/单元/章纲/场景卡。"""

from datetime import UTC, datetime

from sqlmodel import Session, select

from novel_agent.domain.models import (
    ChapterRecord,
    CharacterRecord,
    PlotUnitRecord,
    ProjectRecord,
    SceneRecord,
    StoryKernelRecord,
    VolumeRecord,
)
from novel_agent.domain.schemas import (
    ChapterOutline,
    ChapterStatus,
    CharacterCard,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)


class PlanningRepo:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- 项目 ----

    def create_project(
        self,
        title: str,
        genre: str = "",
        boundaries: list[str] | None = None,
        world_rules: dict | None = None,
    ) -> ProjectRecord:
        rec = ProjectRecord(
            title=title,
            genre=genre,
            boundaries=boundaries or [],
            world_rules=world_rules or {},
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_project(self, project_id: int) -> ProjectRecord:
        return self.s.get_one(ProjectRecord, project_id)

    def list_projects(self) -> list[ProjectRecord]:
        return list(self.s.exec(select(ProjectRecord).order_by(ProjectRecord.id)).all())  # type: ignore[arg-type]

    def update_project(
        self,
        project_id: int,
        *,
        title: str | None = None,
        genre: str | None = None,
        spark: str | None = None,
        enable_writer_b: bool | None = None,
        enable_reader_advocate: bool | None = None,
    ) -> ProjectRecord:
        rec = self.get_project(project_id)
        if title is not None:
            rec.title = title
        if genre is not None:
            rec.genre = genre
        if spark is not None:
            rec.spark = spark
        if enable_writer_b is not None or enable_reader_advocate is not None:
            current = rec.settings if isinstance(rec.settings, dict) else {}
            merged = {
                "enable_writer_b": bool(current.get("enable_writer_b", True)),
                "enable_reader_advocate": bool(current.get("enable_reader_advocate", True)),
            }
            if enable_writer_b is not None:
                merged["enable_writer_b"] = enable_writer_b
            if enable_reader_advocate is not None:
                merged["enable_reader_advocate"] = enable_reader_advocate
            rec.settings = merged
        rec.updated_at = datetime.now(UTC)
        self.s.add(rec)
        return rec

    def archive_project(self, project_id: int) -> ProjectRecord:
        rec = self.get_project(project_id)
        rec.status = "archived"
        rec.updated_at = datetime.now(UTC)
        self.s.add(rec)
        return rec

    # ---- 故事内核 ----

    def save_kernel(self, project_id: int, kernel: StoryKernel) -> StoryKernelRecord:
        prev = self.s.exec(
            select(StoryKernelRecord)
            .where(StoryKernelRecord.project_id == project_id)
            .order_by(StoryKernelRecord.version.desc())  # type: ignore[attr-defined]
        ).first()
        rec = StoryKernelRecord(
            project_id=project_id,
            version=(prev.version + 1) if prev else 1,
            payload=kernel.model_dump(),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def approve_kernel(self, project_id: int, version: int) -> None:
        rec = self.s.exec(
            select(StoryKernelRecord).where(
                StoryKernelRecord.project_id == project_id,
                StoryKernelRecord.version == version,
            )
        ).one()
        rec.approved = True
        self.s.add(rec)

    def get_approved_kernel(self, project_id: int) -> StoryKernel | None:
        rec = self.s.exec(
            select(StoryKernelRecord)
            .where(
                StoryKernelRecord.project_id == project_id,
                StoryKernelRecord.approved == True,  # noqa: E712
            )
            .order_by(StoryKernelRecord.version.desc())  # type: ignore[attr-defined]
        ).first()
        return StoryKernel.model_validate(rec.payload) if rec else None

    def list_kernels(self, project_id: int) -> list[StoryKernelRecord]:
        return list(
            self.s.exec(
                select(StoryKernelRecord)
                .where(StoryKernelRecord.project_id == project_id)
                .order_by(StoryKernelRecord.version)  # type: ignore[arg-type]
            ).all()
        )

    def list_volumes(self, project_id: int) -> list[VolumeRecord]:
        return list(
            self.s.exec(
                select(VolumeRecord)
                .where(VolumeRecord.project_id == project_id)
                .order_by(VolumeRecord.volume_id)  # type: ignore[attr-defined]
            ).all()
        )

    def list_unit_records(self, project_id: int) -> list[PlotUnitRecord]:
        return list(
            self.s.exec(
                select(PlotUnitRecord)
                .where(PlotUnitRecord.project_id == project_id)
                .order_by(PlotUnitRecord.unit_id)  # type: ignore[attr-defined]
            ).all()
        )

    def list_units(self, project_id: int) -> list[PlotUnitCard]:
        records = self.list_unit_records(project_id)
        return [PlotUnitCard.model_validate(rec.payload) for rec in records]

    def list_chapters(self, project_id: int) -> list[ChapterRecord]:
        return list(
            self.s.exec(
                select(ChapterRecord)
                .where(ChapterRecord.project_id == project_id)
                .order_by(ChapterRecord.order_index)  # type: ignore[arg-type]
            ).all()
        )

    # ---- 角色 ----

    def upsert_character(self, project_id: int, card: CharacterCard) -> CharacterRecord:
        rec = self.s.exec(
            select(CharacterRecord).where(
                CharacterRecord.project_id == project_id,
                CharacterRecord.character_id == card.character_id,
            )
        ).first()
        if rec:
            rec.payload = card.model_dump()
            rec.name = card.name
            rec.version += 1
        else:
            rec = CharacterRecord(
                project_id=project_id,
                character_id=card.character_id,
                name=card.name,
                payload=card.model_dump(),
            )
        self.s.add(rec)
        self.s.flush()
        return rec

    def list_characters(self, project_id: int) -> list[CharacterCard]:
        recs = self.s.exec(
            select(CharacterRecord).where(CharacterRecord.project_id == project_id)
        ).all()
        return [CharacterCard.model_validate(r.payload) for r in recs]

    def get_characters(self, project_id: int, character_ids: list[str]) -> list[CharacterCard]:
        return [c for c in self.list_characters(project_id) if c.character_id in character_ids]

    # ---- 卷与剧情单元 ----

    def save_volume(
        self, project_id: int, volume_id: str, payload: dict, title: str = ""
    ) -> VolumeRecord:
        rec = VolumeRecord(project_id=project_id, volume_id=volume_id, title=title, payload=payload)
        self.s.add(rec)
        self.s.flush()
        return rec

    def save_unit(self, project_id: int, volume_id: str, unit: PlotUnitCard) -> PlotUnitRecord:
        rec = PlotUnitRecord(
            project_id=project_id,
            unit_id=unit.unit_id,
            volume_id=volume_id,
            payload=unit.model_dump(),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_unit(self, project_id: int, unit_id: str) -> PlotUnitCard:
        rec = self.s.exec(
            select(PlotUnitRecord).where(
                PlotUnitRecord.project_id == project_id, PlotUnitRecord.unit_id == unit_id
            )
        ).one()
        return PlotUnitCard.model_validate(rec.payload)

    # ---- 章 ----

    def create_chapter(
        self, project_id: int, outline: ChapterOutline, order_index: int
    ) -> ChapterRecord:
        rec = ChapterRecord(
            project_id=project_id,
            chapter_key=outline.chapter_key,
            volume_id=outline.volume_id,
            unit_id=outline.unit_id,
            order_index=order_index,
            title=outline.title,
            target_words=outline.target_words,
            outline=outline.model_dump(),
        )
        self.s.add(rec)
        self.s.flush()
        return rec

    def get_chapter(self, project_id: int, chapter_key: str) -> ChapterRecord:
        return self.s.exec(
            select(ChapterRecord).where(
                ChapterRecord.project_id == project_id,
                ChapterRecord.chapter_key == chapter_key,
            )
        ).one()

    def get_outline(self, project_id: int, chapter_key: str) -> ChapterOutline:
        return ChapterOutline.model_validate(self.get_chapter(project_id, chapter_key).outline)

    def update_outline(self, project_id: int, chapter_key: str, outline: ChapterOutline) -> int:
        """M3.3b:导入修订后的章纲,bump outline_version 并重置轮次/状态。"""
        rec = self.get_chapter(project_id, chapter_key)
        rec.outline = outline.model_dump()
        rec.title = outline.title
        rec.outline_version += 1
        rec.revision_round = 0
        rec.status = ChapterStatus.PLANNED
        rec.target_words = outline.target_words
        self.s.add(rec)
        return rec.outline_version

    def set_status(self, project_id: int, chapter_key: str, status: ChapterStatus) -> None:
        """裸状态写入:仅供 workflow.state_machine 调用(转移合法性由其校验)。"""
        rec = self.get_chapter(project_id, chapter_key)
        rec.status = status
        self.s.add(rec)

    def set_built_on_provisional(self, project_id: int, chapter_key: str, flag: bool) -> None:
        rec = self.get_chapter(project_id, chapter_key)
        rec.built_on_provisional = flag
        self.s.add(rec)

    def increment_revision_round(self, project_id: int, chapter_key: str) -> int:
        rec = self.get_chapter(project_id, chapter_key)
        rec.revision_round += 1
        self.s.add(rec)
        return rec.revision_round

    def reset_revision_round(self, project_id: int, chapter_key: str) -> None:
        rec = self.get_chapter(project_id, chapter_key)
        rec.revision_round = 0
        self.s.add(rec)

    def list_chapters_after(self, project_id: int, order_index: int) -> list[ChapterRecord]:
        """D15 级联:某章之后的批次内章节。"""
        return list(
            self.s.exec(
                select(ChapterRecord)
                .where(
                    ChapterRecord.project_id == project_id,
                    ChapterRecord.order_index > order_index,
                )
                .order_by(ChapterRecord.order_index)  # type: ignore[arg-type]
            ).all()
        )

    # ---- 场景卡 ----

    def replace_scene_cards(
        self, project_id: int, chapter_key: str, cards: list[SceneCard]
    ) -> None:
        existing = self.s.exec(
            select(SceneRecord).where(
                SceneRecord.project_id == project_id,
                SceneRecord.chapter_key == chapter_key,
            )
        ).all()
        for rec in existing:
            self.s.delete(rec)
        self.s.flush()
        self.save_scene_cards(project_id, chapter_key, cards)

    def save_scene_cards(
        self, project_id: int, chapter_key: str, cards: list[SceneCard]
    ) -> None:
        for i, card in enumerate(cards):
            rec = self.s.exec(
                select(SceneRecord).where(
                    SceneRecord.project_id == project_id, SceneRecord.scene_id == card.scene_id
                )
            ).first()
            if rec:
                rec.payload = card.model_dump()
                rec.version += 1
                rec.order_index = i
            else:
                rec = SceneRecord(
                    project_id=project_id,
                    chapter_key=chapter_key,
                    scene_id=card.scene_id,
                    order_index=i,
                    payload=card.model_dump(),
                )
            self.s.add(rec)

    def list_scene_cards(self, project_id: int, chapter_key: str) -> list[SceneCard]:
        recs = self.s.exec(
            select(SceneRecord)
            .where(SceneRecord.project_id == project_id, SceneRecord.chapter_key == chapter_key)
            .order_by(SceneRecord.order_index)  # type: ignore[arg-type]
        ).all()
        return [SceneCard.model_validate(r.payload) for r in recs]
