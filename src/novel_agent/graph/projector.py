"""Canon → 关系图投影。不调用 LLM;图是 relationship_state 的视图。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from novel_agent.domain.repos.bible import BibleRepo
from novel_agent.domain.repos.canon import CanonRepo
from novel_agent.domain.repos.planning import PlanningRepo
from novel_agent.domain.schemas import CanonDelta

MISSING_EVIDENCE = "暂无可追溯证据"
_FACTION_MARKERS = ("书局", "门派", "门", "派", "教", "帮", "阁", "楼", "坊", "营")


class GraphNodeKind(StrEnum):
    CHARACTER = "character"
    FACTION = "faction"
    ALIAS = "alias"


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str
    alias_of: str | None = None


@dataclass
class GraphEdge:
    source: str
    target: str
    label: str
    state: str
    evidence: str
    source_chapter: str
    provisional: bool
    occurrence: int = 1


@dataclass
class GraphTrackBeat:
    chapter_key: str
    from_state: str
    to_state: str
    evidence: str


@dataclass
class GraphTrack:
    parties: list[str]
    beats: list[GraphTrackBeat] = field(default_factory=list)


@dataclass
class GraphProjection:
    project_id: int
    canon_version: str
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    tracks: list[GraphTrack] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def faction_label(text: str) -> str | None:
    for marker in _FACTION_MARKERS:
        idx = text.find(marker)
        if idx >= 0:
            return text[idx : idx + len(marker)]
    return None


def _pair_key(a: str, b: str) -> tuple[str, str]:
    ordered = sorted((a, b))
    return ordered[0], ordered[1]


def project_graph(
    project_id: int,
    planning: PlanningRepo,
    bible: BibleRepo,
    canon: CanonRepo,
) -> GraphProjection:
    """从角色 / 异名 / relationship_state / CanonDelta 投影图 DTO。"""
    alias_to_canonical = {
        item.alias: item.canonical_character_id for item in bible.list_aliases(project_id)
    }

    def resolve(party: str) -> str:
        return alias_to_canonical.get(party, party)

    nodes: dict[str, GraphNode] = {}
    factions: set[str] = set()

    for card in planning.list_characters(project_id):
        nodes[card.character_id] = GraphNode(
            id=card.character_id, label=card.name, kind=GraphNodeKind.CHARACTER.value
        )
        label = faction_label(card.identity)
        if label:
            factions.add(label)

    for rec in canon.latest_entity_states(project_id, include_provisional=True).values():
        label = faction_label(rec.value)
        if label:
            factions.add(label)

    for label in sorted(factions):
        node_id = f"faction_{label}"
        nodes[node_id] = GraphNode(id=node_id, label=label, kind=GraphNodeKind.FACTION.value)

    for alias, canonical in alias_to_canonical.items():
        nodes[alias] = GraphNode(
            id=alias,
            label=alias,
            kind=GraphNodeKind.ALIAS.value,
            alias_of=canonical,
        )

    occurrence: dict[tuple[str, str], int] = {}
    tracks: dict[tuple[str, str], GraphTrack] = {}
    for delta_rec in canon.list_deltas(project_id):
        delta = CanonDelta.model_validate(delta_rec.payload)
        for change in delta.relationship_changes:
            a, b = _pair_key(resolve(change.parties[0]), resolve(change.parties[1]))
            occurrence[(a, b)] = occurrence.get((a, b), 0) + 1
            track = tracks.setdefault((a, b), GraphTrack(parties=[a, b]))
            evidence = change.evidence.strip() or MISSING_EVIDENCE
            track.beats.append(
                GraphTrackBeat(
                    chapter_key=delta.chapter_key,
                    from_state=change.from_state,
                    to_state=change.to_state,
                    evidence=evidence,
                )
            )

    edges: dict[tuple[str, str], GraphEdge] = {}
    for rel in canon.list_relationships(project_id):
        a, b = _pair_key(resolve(rel.party_a), resolve(rel.party_b))
        evidence = rel.evidence.strip() or MISSING_EVIDENCE
        key = (a, b)
        existing = edges.get(key)
        if existing is None:
            edges[key] = GraphEdge(
                source=a,
                target=b,
                label=rel.state,
                state=rel.state,
                evidence=evidence,
                source_chapter=rel.source_chapter,
                provisional=rel.provisional,
                occurrence=max(1, occurrence.get(key, 0)),
            )
        else:
            existing.occurrence += 1
            if rel.provisional:
                existing.provisional = True
            if existing.label != rel.state:
                existing.label = f"{existing.label}/{rel.state}"

    return GraphProjection(
        project_id=project_id,
        canon_version=canon.current_canon_version(project_id),
        nodes=sorted(nodes.values(), key=lambda node: (node.kind, node.id)),
        edges=sorted(edges.values(), key=lambda edge: (edge.source, edge.target)),
        tracks=sorted(tracks.values(), key=lambda track: track.parties),
    )
