import { describe, expect, it } from "vitest";
import { flattenOutlineTree, toOutlineNodes, type OutlineTreeDto } from "./mapOutlineTree";

const dto: OutlineTreeDto = {
  project_id: 1,
  kernel: {
    version: 1,
    approved: true,
    logline: "说书人发现故事会成真",
    premise: "如果评书应验",
  },
  volumes: [
    {
      volume_id: "v1",
      title: "卷一",
      status: "confirmed",
      payload: { goal: "立契" },
      units: [
        {
          unit_id: "u1",
          status: "confirmed",
          payload: { promise_or_debt: "评书应验" },
          chapters: [
            {
              chapter_key: "v1c001",
              title: "第1章",
              status: "PLANNED",
              order_index: 1,
              outline: { chapter_key: "v1c001", core_event: "茶楼立契", title: "第1章" },
              scenes: [
                {
                  scene_id: "v1c001_s1",
                  chapter_key: "v1c001",
                  goal: "拍醒木",
                  pov: "苏晚生",
                },
              ],
            },
          ],
        },
      ],
    },
  ],
};

describe("toOutlineNodes", () => {
  it("maps kernel → volume → unit → chapter → scene", () => {
    const nodes = toOutlineNodes(dto);
    expect(nodes).toHaveLength(1);
    const kernel = nodes[0];
    expect(kernel.level).toBe("kernel");
    expect(kernel.label).toContain("说书人发现故事会成真");
    expect(kernel.children).toHaveLength(1);
    const volume = kernel.children[0];
    expect(volume.level).toBe("volume");
    expect(volume.id).toBe("v1");
    const unit = volume.children[0];
    expect(unit.level).toBe("unit");
    expect(unit.id).toBe("u1");
    const chapter = unit.children[0];
    expect(chapter.level).toBe("chapter");
    expect(chapter.chapterKey).toBe("v1c001");
    expect(chapter.children[0]?.level).toBe("scene");
    expect(chapter.children[0]?.id).toBe("v1c001_s1");
  });

  it("flattens visible rows for the tree rail", () => {
    const rows = flattenOutlineTree(toOutlineNodes(dto), new Set(["kernel", "v1", "u1"]));
    expect(rows.map((row) => row.level)).toEqual([
      "kernel",
      "volume",
      "unit",
      "chapter",
    ]);
  });
});
