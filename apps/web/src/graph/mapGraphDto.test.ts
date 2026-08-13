import { describe, expect, it } from "vitest";
import {
  MISSING_EVIDENCE,
  inspectorFor,
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
      label: "对手",
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
});

describe("inspectorFor", () => {
  it("counts degree from filtered edges and returns relationship tracks", () => {
    const info = inspectorFor(dto, "ch_su", { from: "v1c001", to: "v1c002" });
    expect(info.degree).toBe(1);
    expect(info.tracks).toHaveLength(1);
    expect(info.evidence).toEqual([MISSING_EVIDENCE]);
  });
});
