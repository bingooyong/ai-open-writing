import { describe, expect, it } from "vitest";
import {
  MISSING_EVIDENCE,
  characterInsight,
  graphCensus,
  inspectorFor,
  shortEdgeLabel,
  toG6Data,
  type GraphDto,
} from "./mapGraphDto";

const dto: GraphDto = {
  project_id: 1,
  canon_version: "canon_v1",
  nodes: [
    { id: "ch_su", label: "苏晚生", kind: "character", alias_of: null },
    { id: "ch_huo", label: "霍执事", kind: "character", alias_of: null },
    { id: "faction_书局", label: "书局", kind: "faction", alias_of: null },
    { id: "晚生", label: "晚生", kind: "alias", alias_of: "ch_su" },
  ],
  edges: [
    {
      source: "ch_su",
      target: "ch_huo",
      label: "对手 (茶楼对峙)",
      state: "strained",
      evidence: "",
      source_chapter: "planning",
      provisional: true,
      occurrence: 1,
    },
    {
      source: "ch_su",
      target: "faction_书局",
      label: "隶属",
      state: "bound",
      evidence: "茶楼立契",
      source_chapter: "v1c003",
      provisional: false,
      occurrence: 2,
    },
  ],
  tracks: [
    {
      parties: ["ch_su", "ch_huo"],
      beats: [
        {
          chapter_key: "v1c001",
          from_state: "strangers",
          to_state: "strained",
          evidence: "",
        },
      ],
    },
  ],
};

describe("toG6Data", () => {
  it("maps character/faction/alias nodes and dashes alias plus provisional edges", () => {
    const { nodes, edges } = toG6Data(dto);
    const alias = nodes.find((node) => node.id === "晚生");
    expect(alias?.style.lineDash).toEqual([6, 4]);
    const character = nodes.find((node) => node.id === "ch_su");
    expect(character?.style.lineDash).toBeUndefined();
    const provisional = edges.find((edge) => edge.data.source_chapter === "planning");
    expect(provisional?.style.lineDash).toEqual([8, 4]);
    expect(provisional?.data.evidence).toBe(MISSING_EVIDENCE);
    expect(provisional?.style.labelText).toBe("对手");
    expect(provisional?.data.fullLabel).toBe("对手 (茶楼对峙)");
    expect(edges.every((edge) => edge.style.labelAutoRotate === false)).toBe(true);
  });

  it("filters edges by chapter range but keeps planning-time edges", () => {
    const { edges } = toG6Data(dto, { from: "v1c001", to: "v1c002" });
    expect(edges.map((edge) => edge.data.source_chapter).sort()).toEqual(["planning"]);
  });

  it("keeps committed edges inside the selected chapter window", () => {
    const { edges } = toG6Data(dto, { from: "v1c003", to: "v1c003" });
    expect(edges).toHaveLength(2);
    expect(edges.some((edge) => edge.data.source_chapter === "v1c003")).toBe(true);
  });

  it("uses zinc strokes that follow the resolved theme", () => {
    const dark = toG6Data(dto).edges.find((edge) => !edge.data.provisional);
    const light = toG6Data(dto, undefined, "light").edges.find((edge) => !edge.data.provisional);
    expect(dark?.style.stroke).toBe("#3f3f46");
    expect(light?.style.stroke).toBe("#d4d4d8");
  });
});

describe("inspectorFor", () => {
  it("counts degree from filtered edges and returns relationship tracks", () => {
    const info = inspectorFor(dto, "ch_su", { from: "v1c001", to: "v1c002" });
    expect(info.degree).toBe(1);
    expect(info.tracks).toHaveLength(1);
    expect(info.evidence).toEqual([MISSING_EVIDENCE]);
    expect(info.appearanceChapters).toBe(1);
    expect(info.turningBeats).toBe(1);
    expect(info.edges).toEqual([
      {
        counterpartId: "ch_huo",
        counterpartLabel: "霍执事",
        state: "strained",
        label: "对手 (茶楼对峙)",
        evidence: MISSING_EVIDENCE,
        source_chapter: "planning",
        provisional: true,
      },
    ]);
  });
});

describe("shortEdgeLabel", () => {
  it("keeps the clause before ASCII or fullwidth parentheses", () => {
    expect(shortEdgeLabel("敌对 (茶楼立契)")).toBe("敌对");
    expect(shortEdgeLabel("盟友（旧识）")).toBe("盟友");
    expect(shortEdgeLabel("隶属")).toBe("隶属");
  });
});

describe("graphCensus", () => {
  it("counts non-alias people and range-filtered relations", () => {
    expect(graphCensus(null)).toEqual({ people: 0, relations: 0 });
    expect(graphCensus(dto)).toEqual({ people: 3, relations: 2 });
    expect(graphCensus(dto, { from: "v1c001", to: "v1c002" })).toEqual({
      people: 3,
      relations: 1,
    });
  });
});

describe("characterInsight", () => {
  it("prefers bible identity when the snapshot already has the card", () => {
    const insight = characterInsight(dto.nodes[0], [
      {
        character_id: "ch_su",
        name: "苏晚生",
        identity: "临安城茶楼说书人",
        story_function: "主角",
      },
    ]);
    expect(insight.oneLiner).toBe("苏晚生 · 临安城茶楼说书人 · 主角");
    expect(insight.identity).toBe("临安城茶楼说书人");
  });

  it("falls back to graph node fields when bible has no card", () => {
    const insight = characterInsight(dto.nodes[0], []);
    expect(insight.oneLiner).toBe("苏晚生 · 人物");
    expect(insight.identity).toBe("");
  });
});
