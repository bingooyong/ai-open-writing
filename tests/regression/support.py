"""Load Spec §8 regression samples and drive them through the existing chapter loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from sqlmodel import Session

from novel_agent.config import Settings
from novel_agent.domain.db import build_engine, create_all
from novel_agent.domain.repos import CanonRepo, PlanningRepo
from novel_agent.domain.schemas import (
    ChapterOutline,
    CharacterCard,
    PlotUnitCard,
    SceneCard,
    StoryKernel,
)
from novel_agent.gateway import MockProvider, ModelGateway
from novel_agent.gateway.base import ModelRequest
from novel_agent.production.loop import ChapterLoopGates, run_chapter_loop
from novel_agent.production.mock_fixtures import (
    canon_delta_json,
    register_chapter_loop_defaults,
    two_part_text,
)
from novel_agent.runtime.agents import AgentDeps

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
REVIEWER_ROLES = ("red_team", "plot", "character", "continuity", "prose", "reader_advocate")


def list_sample_dirs() -> list[Path]:
    return sorted(path for path in SAMPLES_DIR.iterdir() if (path / "sample.yaml").is_file())


def load_sample(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "id" not in data:
        raise ValueError(f"invalid regression sample: {path}")
    return data


def _empty_report(role: str) -> str:
    return json.dumps(
        {
            "reviewer_role": role,
            "candidate_id": "candidate_1",
            "issues": [],
            "overall_note": "无额外问题",
        },
        ensure_ascii=False,
    )


def _quote_scene_id(sample: dict[str, Any]) -> str:
    quote = str(sample.get("quote") or "")
    for scene in sample["draft_scenes"]:
        if quote and quote in scene["content"]:
            return str(scene["scene_id"])
    return str(sample["draft_scenes"][0]["scene_id"])


def _issue_report(sample: dict[str, Any], role: str) -> str:
    evidenceless = bool(sample.get("evidenceless"))
    quote = str(sample.get("quote") or "")
    scene_id = _quote_scene_id(sample)
    evidence: list[dict[str, str]] = []
    if not evidenceless and quote:
        evidence = [{"scene_id": scene_id, "quote": quote}]
    issue = {
        "issue_id": f"{role}_raw1",
        "reviewer_role": role,
        "claim": f"植入缺陷 {sample['implant']}",
        "evidence": evidence,
        "violated_rule": str(sample.get("hard_gate") or "软问题"),
        "severity": "P0" if sample.get("hard_gate") else "P2",
        "failure_consequence": "若误放行会破坏正史或信息边界",
        "recommended_rollback_level": sample.get("rollback_target") or "prose",
        "confidence": 0.9,
    }
    if sample.get("hard_gate"):
        issue["hard_gate"] = sample["hard_gate"]
    return json.dumps(
        {
            "reviewer_role": role,
            "candidate_id": "candidate_1",
            "issues": [issue],
            "overall_note": sample["title"],
        },
        ensure_ascii=False,
    )


def _sample_verdict(sample: dict[str, Any]) -> str:
    verdict = str(sample.get("judge_verdict") or "PASS")
    blocker = str(sample.get("blocker_role") or "continuity")
    payload: dict[str, Any] = {
        "verdict": verdict,
        "selected_candidate": "candidate_1",
        "hard_gate_failures": (
            [sample["hard_gate"]] if sample.get("hard_gate") and verdict != "PASS" else []
        ),
        "rulings": [
            {
                "issue_id": f"{blocker}_1",
                "accepted": verdict != "PASS",
                "reason": "植入项有正文证据" if verdict != "PASS" else "软问题不阻断",
            }
        ],
        "reasoning_summary": f"regression {sample['id']} {verdict}",
    }
    if verdict == "REVISE_LOCAL":
        payload["revision_scope"] = [sample["draft_scenes"][0]["scene_id"]]
    if verdict in {"REPLAN_SCENE", "REPLAN_CHAPTER"}:
        payload["rollback_target"] = sample.get("rollback_target") or "scene_card"
    return json.dumps(payload, ensure_ascii=False)


def _pad_sample_prose(text: str) -> str:
    filler = "街面的更鼓远远响了一声，茶客把碗放下，谁也没再追问下一句。"
    compact = "".join(text.split())
    while len(compact) < 800:
        text = text + filler
        compact = "".join(text.split())
    return text


def register_sample_mocks(mock: MockProvider, sample: dict[str, Any]) -> None:
    """Writer returns the implanted draft; reviewers/Judge follow the sample expect."""
    register_chapter_loop_defaults(mock)
    scenes = sample["draft_scenes"]
    scene_1 = _pad_sample_prose(scenes[0]["content"])
    scene_2 = _pad_sample_prose(scenes[1]["content"] if len(scenes) > 1 else scenes[0]["content"])
    mock.register(
        "writer_a",
        lambda req: two_part_text(req, scene_1, scene_2, sample["chapter_summary"]),
    )
    mock.register(
        "writer_b",
        lambda req: two_part_text(req, scene_1, scene_2, sample["chapter_summary"]),
    )
    if sample["expect"]["lint_blocks"]:
        return

    blocker = str(sample.get("blocker_role") or "continuity")
    report_blocker = sample["expect"]["judge_blocks"] or bool(sample.get("evidenceless"))
    for role in REVIEWER_ROLES:
        if role == blocker and (report_blocker or sample.get("quote")):
            payload = _issue_report(sample, role)
        else:
            payload = _empty_report(role)
        mock.register(role, lambda _req, text=payload: text)

    mock.register("judge", lambda _req: _sample_verdict(sample))
    mock.register("canon_curator", lambda _req: canon_delta_json())


def seed_sample_project(session: Session, sample: dict[str, Any]) -> int:
    planning = PlanningRepo(session)
    project = planning.create_project(
        f"回归 {sample['id']}",
        genre="奇幻",
        boundaries=["禁无代价全能"],
    )
    assert project.id is not None
    kernel = StoryKernel.model_validate(sample["kernel"])
    rec = planning.save_kernel(project.id, kernel)
    planning.approve_kernel(project.id, rec.version)
    for raw in sample["characters"]:
        planning.upsert_character(project.id, CharacterCard.model_validate(raw))
    unit = PlotUnitCard.model_validate(sample["unit"])
    planning.save_volume(project.id, "v1", {"goal": "开局"}, title="第一卷")
    planning.save_unit(project.id, "v1", unit)
    outline = ChapterOutline.model_validate(sample["outline"])
    planning.create_chapter(project.id, outline, order_index=1)
    planning.save_scene_cards(
        project.id,
        outline.chapter_key,
        [SceneCard.model_validate(item) for item in sample["scenes"]],
    )
    canon = CanonRepo(session)
    for fact in sample.get("canon") or []:
        canon.append_entity_state(
            project.id,
            fact["entity_id"],
            fact["state_type"],
            fact["value"],
            fact["reason"],
            fact["source_chapter"],
        )
    session.commit()
    return project.id


async def run_sample(tmp_path: Path, sample: dict[str, Any]):
    engine = build_engine(tmp_path / f"{sample['id'].lower()}.db")
    create_all(engine)
    session = Session(engine)
    project_id = seed_sample_project(session, sample)
    mock = MockProvider()
    register_sample_mocks(mock, sample)
    settings = Settings(_env_file=None)
    deps = AgentDeps(
        gateway=ModelGateway(settings, session, {"mock": mock}),
        project_id=project_id,
    )
    result = await run_chapter_loop(
        session,
        deps,
        project_id,
        sample["outline"]["chapter_key"],
        gates=ChapterLoopGates.auto(),
        settings=settings,
    )
    session.commit()
    return session, deps, mock, result


def reviewer_roles_called(mock: MockProvider) -> set[str]:
    return {role for role, _req in mock.calls if role in REVIEWER_ROLES}


def judge_requests(mock: MockProvider) -> list[ModelRequest]:
    return [req for role, req in mock.calls if role == "judge"]
