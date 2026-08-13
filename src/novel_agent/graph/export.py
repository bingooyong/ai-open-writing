"""关系图导出:JSON 与 mermaid。"""

from __future__ import annotations

import hashlib
import json
from typing import assert_never

from novel_agent.graph.projector import GraphNodeKind, GraphProjection


def to_json(graph: GraphProjection) -> str:
    return json.dumps(graph.to_dict(), ensure_ascii=False, indent=2)


def to_mermaid(graph: GraphProjection) -> str:
    lines = ["graph LR"]
    for node in graph.nodes:
        kind = GraphNodeKind(node.kind)
        label = node.label.replace('"', "'")
        ident = _ident(node.id)
        if kind is GraphNodeKind.ALIAS:
            lines.append(f'  {ident}["{label}"]')
            if node.alias_of:
                lines.append(f"  {ident} -.-> {_ident(node.alias_of)}")
        elif kind is GraphNodeKind.FACTION:
            lines.append(f"  {ident}(({label}))")
        elif kind is GraphNodeKind.CHARACTER:
            lines.append(f'  {ident}["{label}"]')
        else:
            assert_never(kind)
    for edge in graph.edges:
        src = _ident(edge.source)
        dst = _ident(edge.target)
        label = (edge.label or edge.state).replace("|", "/")
        if edge.provisional:
            lines.append(f"  {src} -.->|{label}| {dst}")
        else:
            lines.append(f"  {src} -->|{label}| {dst}")
    return "\n".join(lines) + "\n"


def _ident(raw: str) -> str:
    if raw and all(ch.isalnum() or ch == "_" for ch in raw) and (
        raw[0].isalpha() or raw[0] == "_"
    ):
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"n_{digest}"
