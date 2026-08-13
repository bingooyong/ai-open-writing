export const MISSING_EVIDENCE = "暂无可追溯证据";

export type GraphNodeKind = "character" | "faction" | "alias";

export type GraphNodeDto = {
  id: string;
  label: string;
  kind: string;
  alias_of: string | null;
};

export type GraphEdgeDto = {
  source: string;
  target: string;
  label: string;
  state: string;
  evidence: string;
  source_chapter: string;
  provisional: boolean;
  occurrence: number;
};

export type GraphTrackDto = {
  parties: string[];
  beats: Array<{
    chapter_key: string;
    from_state: string;
    to_state: string;
    evidence: string;
  }>;
};

export type GraphDto = {
  project_id: number;
  canon_version: string;
  nodes: GraphNodeDto[];
  edges: GraphEdgeDto[];
  tracks: GraphTrackDto[];
};

export type ChapterRange = {
  from?: string;
  to?: string;
};

export type G6Node = {
  id: string;
  data: { kind: string; label: string; alias_of: string | null };
  style: {
    labelText: string;
    lineDash?: number[];
    fill?: string;
    stroke?: string;
    lineWidth?: number;
  };
};

export type G6Edge = {
  id: string;
  source: string;
  target: string;
  data: { evidence: string; provisional: boolean; source_chapter: string };
  style: {
    labelText: string;
    lineDash?: number[];
    stroke?: string;
  };
};

function asKind(kind: string): GraphNodeKind {
  if (kind === "character" || kind === "faction" || kind === "alias") {
    return kind;
  }
  return "character";
}

function kindPaint(kind: GraphNodeKind): { fill: string; stroke: string } {
  switch (kind) {
    case "character":
      return { fill: "#1a6d63", stroke: "#182231" };
    case "faction":
      return { fill: "#3d4d66", stroke: "#182231" };
    case "alias":
      return { fill: "#8a93a1", stroke: "#6a7586" };
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}

export function chapterInRange(chapterKey: string, range?: ChapterRange): boolean {
  if (!range || (!range.from && !range.to)) {
    return true;
  }
  if (chapterKey === "planning") {
    return true;
  }
  if (range.from && chapterKey < range.from) {
    return false;
  }
  if (range.to && chapterKey > range.to) {
    return false;
  }
  return true;
}

export function labeledEvidence(evidence: string): string {
  const text = evidence.trim();
  return text || MISSING_EVIDENCE;
}

export function toG6Data(
  dto: GraphDto,
  range?: ChapterRange,
): { nodes: G6Node[]; edges: G6Edge[] } {
  const nodes = dto.nodes.map((node) => {
    const kind = asKind(node.kind);
    const paint = kindPaint(kind);
    const dashed = kind === "alias";
    return {
      id: node.id,
      data: { kind: node.kind, label: node.label, alias_of: node.alias_of },
      style: {
        labelText: node.label,
        lineDash: dashed ? [6, 4] : undefined,
        fill: paint.fill,
        stroke: paint.stroke,
        lineWidth: dashed ? 1 : 2,
      },
    };
  });
  const edges = dto.edges
    .filter((edge) => chapterInRange(edge.source_chapter, range))
    .map((edge, index) => ({
      id: `e-${edge.source}-${edge.target}-${index}`,
      source: edge.source,
      target: edge.target,
      data: {
        evidence: labeledEvidence(edge.evidence),
        provisional: edge.provisional,
        source_chapter: edge.source_chapter,
      },
      style: {
        labelText: edge.label || edge.state,
        lineDash: edge.provisional ? [8, 4] : undefined,
        stroke: edge.provisional ? "#b6791a" : "#3d4d66",
      },
    }));
  return { nodes, edges };
}

export function inspectorFor(dto: GraphDto, nodeId: string, range?: ChapterRange) {
  const edges = dto.edges.filter(
    (edge) =>
      (edge.source === nodeId || edge.target === nodeId) &&
      chapterInRange(edge.source_chapter, range),
  );
  const tracks = dto.tracks.filter((track) => track.parties.includes(nodeId));
  return {
    degree: edges.length,
    tracks,
    evidence: edges.map((edge) => labeledEvidence(edge.evidence)),
  };
}
