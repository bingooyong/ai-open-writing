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
    size: number;
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
  data: { evidence: string; provisional: boolean; source_chapter: string; fullLabel: string };
  style: {
    labelText: string;
    labelAutoRotate: false;
    lineDash?: number[];
    stroke?: string;
  };
};

export type InspectorEdge = {
  counterpartId: string;
  counterpartLabel: string;
  state: string;
  label: string;
  evidence: string;
  source_chapter: string;
  provisional: boolean;
};

export type CharacterInsight = {
  name: string;
  identity: string;
  storyFunction: string;
  kind: GraphNodeKind;
  oneLiner: string;
};

function asKind(kind: string): GraphNodeKind {
  if (kind === "character" || kind === "faction" || kind === "alias") {
    return kind;
  }
  return "character";
}

function kindPaint(kind: GraphNodeKind): { fill: string; stroke: string; size: number } {
  switch (kind) {
    case "character":
      return { fill: "#d4d4d8", stroke: "#d4d4d8", size: 18 };
    case "faction":
      return { fill: "#71717a", stroke: "#71717a", size: 16 };
    case "alias":
      return { fill: "#52525b", stroke: "#71717a", size: 14 };
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

export function shortEdgeLabel(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) {
    return trimmed;
  }
  const cut = trimmed.search(/[（(]/);
  const head = (cut >= 0 ? trimmed.slice(0, cut) : trimmed).trim();
  return head || trimmed;
}

export function graphCensus(dto: GraphDto | null, range?: ChapterRange): {
  people: number;
  relations: number;
} {
  if (!dto) {
    return { people: 0, relations: 0 };
  }
  const { nodes, edges } = toG6Data(dto, range);
  return {
    people: nodes.filter((node) => node.data.kind !== "alias").length,
    relations: edges.length,
  };
}

export function characterInsight(
  node: GraphNodeDto | undefined,
  characters: Array<Record<string, unknown>> | undefined,
): CharacterInsight {
  const kind = asKind(node?.kind ?? "character");
  const card = characters?.find(
    (item) => item.character_id === node?.id || item.name === node?.label,
  );
  const name =
    (typeof card?.name === "string" && card.name) || node?.label || node?.id || "未名";
  const identity = typeof card?.identity === "string" ? card.identity.trim() : "";
  const storyFunction =
    typeof card?.story_function === "string" ? card.story_function.trim() : "";
  const kindLabel = kind === "faction" ? "势力" : kind === "alias" ? "异名" : "人物";
  const parts = [name, identity, storyFunction || kindLabel].filter(Boolean);
  return { name, identity, storyFunction, kind, oneLiner: parts.join(" · ") };
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
        size: paint.size,
        lineDash: dashed ? [6, 4] : undefined,
        fill: paint.fill,
        stroke: paint.stroke,
        lineWidth: 1,
      },
    };
  });
  const edges = dto.edges
    .filter((edge) => chapterInRange(edge.source_chapter, range))
    .map((edge, index) => {
      const fullLabel = edge.label || edge.state;
      return {
        id: `e-${edge.source}-${edge.target}-${index}`,
        source: edge.source,
        target: edge.target,
        data: {
          evidence: labeledEvidence(edge.evidence),
          provisional: edge.provisional,
          source_chapter: edge.source_chapter,
          fullLabel,
        },
        style: {
          labelText: shortEdgeLabel(fullLabel),
          labelAutoRotate: false as const,
          lineDash: edge.provisional ? [8, 4] : undefined,
          stroke: edge.provisional ? "#71717a" : "#3f3f46",
        },
      };
    });
  return { nodes, edges };
}

export type InspectorView = ReturnType<typeof inspectorFor>;

export function inspectorFor(dto: GraphDto, nodeId: string, range?: ChapterRange) {
  const node = dto.nodes.find((item) => item.id === nodeId);
  const edges = dto.edges.filter(
    (edge) =>
      (edge.source === nodeId || edge.target === nodeId) &&
      chapterInRange(edge.source_chapter, range),
  );
  const tracks = dto.tracks.filter((track) => track.parties.includes(nodeId));
  const chapters = new Set(edges.map((edge) => edge.source_chapter));
  return {
    node,
    degree: edges.length,
    appearanceChapters: chapters.size,
    turningBeats: tracks.reduce((count, track) => count + track.beats.length, 0),
    tracks,
    evidence: edges.map((edge) => labeledEvidence(edge.evidence)),
    edges: edges.map((edge): InspectorEdge => {
      const counterpartId = edge.source === nodeId ? edge.target : edge.source;
      return {
        counterpartId,
        counterpartLabel: dto.nodes.find((item) => item.id === counterpartId)?.label ?? counterpartId,
        state: edge.state,
        label: edge.label || edge.state,
        evidence: labeledEvidence(edge.evidence),
        source_chapter: edge.source_chapter,
        provisional: edge.provisional,
      };
    }),
  };
}
