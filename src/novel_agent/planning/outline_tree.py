"""从 PlanningRepo 现有行组装五级大纲树,不另存大纲。"""

from __future__ import annotations

from novel_agent.domain.models import ChapterRecord
from novel_agent.domain.repos import PlanningRepo


def assemble_outline_tree(planning: PlanningRepo, project_id: int) -> dict[str, object]:
    kernels = planning.list_kernels(project_id)
    kernel_rec = next((row for row in reversed(kernels) if row.approved), None)
    if kernel_rec is None and kernels:
        kernel_rec = kernels[-1]
    kernel: dict[str, object] | None = None
    if kernel_rec is not None:
        payload = dict(kernel_rec.payload or {})
        kernel = {
            "version": kernel_rec.version,
            "approved": kernel_rec.approved,
            "logline": payload.get("logline") or "",
            "premise": payload.get("premise") or "",
            "payload": payload,
        }

    units_by_volume: dict[str, list] = {}
    known_units: set[str] = set()
    for rec in planning.list_unit_records(project_id):
        units_by_volume.setdefault(rec.volume_id, []).append(rec)
        known_units.add(rec.unit_id)

    chapters_by_unit: dict[str, list[ChapterRecord]] = {}
    leftover: list[ChapterRecord] = []
    for chapter in planning.list_chapters(project_id):
        if chapter.unit_id in known_units:
            chapters_by_unit.setdefault(chapter.unit_id, []).append(chapter)
        else:
            leftover.append(chapter)

    volumes: list[dict[str, object]] = []
    for volume in planning.list_volumes(project_id):
        unit_nodes: list[dict[str, object]] = []
        for unit in units_by_volume.get(volume.volume_id, []):
            unit_nodes.append(
                {
                    "unit_id": unit.unit_id,
                    "status": unit.status,
                    "payload": unit.payload,
                    "chapters": [
                        _chapter_node(planning, project_id, chapter)
                        for chapter in chapters_by_unit.get(unit.unit_id, [])
                    ],
                }
            )
        volumes.append(
            {
                "volume_id": volume.volume_id,
                "title": volume.title,
                "status": volume.status,
                "payload": volume.payload,
                "units": unit_nodes,
            }
        )
    if leftover:
        volumes.append(
            {
                "volume_id": "_unfiled",
                "title": "未归卷",
                "status": "draft",
                "payload": {},
                "units": [
                    {
                        "unit_id": "_unfiled",
                        "status": "draft",
                        "payload": {},
                        "chapters": [
                            _chapter_node(planning, project_id, chapter) for chapter in leftover
                        ],
                    }
                ],
            }
        )
    return {"project_id": project_id, "kernel": kernel, "volumes": volumes}


def _chapter_node(
    planning: PlanningRepo, project_id: int, chapter: ChapterRecord
) -> dict[str, object]:
    scenes = [
        card.model_dump(mode="json")
        for card in planning.list_scene_cards(project_id, chapter.chapter_key)
    ]
    return {
        "chapter_key": chapter.chapter_key,
        "title": chapter.title,
        "status": chapter.status.value,
        "order_index": chapter.order_index,
        "outline": chapter.outline or {},
        "scenes": scenes,
    }
