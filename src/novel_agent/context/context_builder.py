"""PRD §12.2 的确定性 ChapterContextPackage 组装。"""

import json

from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import (
    CanonFact,
    ChapterContextPackage,
    ChapterOutline,
    ThreadStatus,
)
from novel_agent.memory.protocol import MemoryRetrieval


class ContextBuilder:
    """只读仓储，将单章写作必需信息按稳定顺序组装为上下文包。"""

    def __init__(
        self,
        planning: PlanningRepo,
        canon: CanonRepo,
        retrieval: MemoryRetrieval | None = None,
    ) -> None:
        self._planning = planning
        self._canon = canon
        self._retrieval = retrieval

    def build(
        self,
        project_id: int,
        chapter_key: str,
        *,
        task_brief: str,
        volume_summary: str,
        previous_ending: str = "",
        earlier_summaries: list[str] | None = None,
        retrieval_facts: list[str] | None = None,
        style_rules: str = "",
        prior_feedback: str = "",
        include_provisional: bool = False,
        max_chars: int | None = None,
    ) -> ChapterContextPackage:
        """构建并在给定字符预算内裁剪最低优先级文本上下文。"""
        project = self._planning.get_project(project_id)
        kernel = self._planning.get_approved_kernel(project_id)
        if kernel is None:
            raise ValueError("无法构建上下文: 缺少已批准故事内核")

        outline = self._planning.get_outline(project_id, chapter_key)
        scene_cards = self._planning.list_scene_cards(project_id, chapter_key)
        if not scene_cards:
            raise ValueError("无法构建上下文: 缺少场景卡")
        unit = self._planning.get_unit(project_id, outline.unit_id)
        if retrieval_facts is None:
            retrieval_facts = self._retrieve_facts(
                project_id, outline, include_provisional=include_provisional
            )

        hard_constraints = [CanonFact(content=f"故事内核: {kernel.reader_promise}")]
        hard_constraints.extend(CanonFact(content=item) for item in kernel.do_not_write)
        hard_constraints.extend(CanonFact(content=item) for item in project.boundaries)
        hard_constraints.extend(CanonFact(content=item) for item in unit.canon_constraints)
        hard_constraints.extend(
            CanonFact(content=f"世界规则 {key}: {project.world_rules[key]}")
            for key in sorted(project.world_rules)
        )

        entity_states = [
            CanonFact(
                content=f"{entity_id}.{state_type}: {record.value}",
                provisional=record.provisional,
                source_chapter=record.source_chapter,
            )
            for (entity_id, state_type), record in sorted(
                self._canon.latest_entity_states(
                    project_id,
                    include_provisional,
                    as_of_chapter_key=chapter_key,
                ).items()
            )
        ]
        package = ChapterContextPackage(
            chapter_key=chapter_key,
            canon_version=self._canon.current_canon_version(project_id),
            task_brief=task_brief,
            outline=outline,
            scene_cards=scene_cards,
            kernel_summary=f"{kernel.logline}\n读者契约: {kernel.reader_promise}",
            volume_summary=volume_summary,
            unit_card=unit,
            hard_constraints=hard_constraints,
            previous_ending=previous_ending,
            earlier_summaries=list(earlier_summaries or []),
            retrieval_facts=list(retrieval_facts or []),
            characters=sorted(
                self._planning.list_characters(project_id),
                key=lambda character: character.character_id,
            ),
            entity_states=entity_states,
            active_threads=[
                ThreadStatus(
                    thread_id=thread.thread_id,
                    summary=thread.setup or thread.planned_payoff or thread.thread_id,
                    status=thread.status,
                )
                for thread in self._canon.list_threads(project_id)
            ],
            style_rules=style_rules,
            boundaries=[*kernel.do_not_write, *project.boundaries],
            prior_feedback=prior_feedback,
        )
        return self._trim(package, max_chars)

    @staticmethod
    def context_size(package: ChapterContextPackage) -> int:
        """稳定的字符预算度量，不依赖模型 tokenizer。"""
        return len(json.dumps(package.model_dump(), ensure_ascii=False, sort_keys=True))

    def required_size(self, package: ChapterContextPackage) -> int:
        """不可裁剪内容的大小，用于调用方在预算不足时明确失败。"""
        return self.context_size(
            package.model_copy(
                update={"previous_ending": "", "earlier_summaries": [], "retrieval_facts": []}
            )
        )

    def _trim(
        self, package: ChapterContextPackage, max_chars: int | None
    ) -> ChapterContextPackage:
        if max_chars is None:
            return package
        if max_chars < self.required_size(package):
            raise ValueError("上下文预算不足以保留硬约束、章纲、场景卡和实体状态")

        # PRD §12.2:先丢低相关检索，再丢更早摘要，最后丢最近原文窗口。
        for field in ("retrieval_facts", "earlier_summaries"):
            items = list(getattr(package, field))
            while items and self.context_size(package) > max_chars:
                items.pop(0)
                package = package.model_copy(update={field: items})
        if self.context_size(package) > max_chars:
            package = package.model_copy(update={"previous_ending": ""})
        return package

    def _retrieve_facts(
        self,
        project_id: int,
        outline: ChapterOutline,
        *,
        include_provisional: bool,
    ) -> list[str]:
        if self._retrieval is None:
            return []
        query_parts = [
            outline.title,
            outline.core_event,
            outline.protagonist_goal,
            *outline.cited_conflict_ids,
            *outline.cited_beat_ids,
        ]
        for character in self._planning.list_characters(project_id):
            query_parts.append(character.name)
            query_parts.append(character.character_id)
        for thread in self._canon.list_threads(project_id):
            query_parts.append(thread.thread_id)
            if thread.setup:
                query_parts.append(thread.setup)
        query = "\n".join(part for part in query_parts if str(part).strip())
        if not query:
            return []
        return [
            fact.text
            for fact in self._retrieval.retrieve(
                project_id, query, include_provisional=include_provisional
            )
        ]
