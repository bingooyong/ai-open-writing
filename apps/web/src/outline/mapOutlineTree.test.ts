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
    {
      volume_id: "v2",
      title: "卷二",
      status: "draft",
      payload: { goal: "还债" },
      units: [
        {
          unit_id: "u2",
          status: "confirmed",
          payload: { promise_or_debt: "还清故事债" },
          chapters: [
            {
              chapter_key: "v2c001",
              title: "第1章",
              status: "PLANNED",
              order_index: 6,
              outline: { chapter_key: "v2c001", core_event: "新卷开场", title: "第1章" },
              scenes: [
                {
                  scene_id: "v2c001_s1",
                  chapter_key: "v2c001",
                  goal: "立新契",
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
    expect(kernel.children).toHaveLength(2);
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
    const volume2 = kernel.children[1];
    expect(volume2.id).toBe("v2");
    expect(volume2.children[0]?.id).toBe("u2");
    expect(volume2.children[0]?.children[0]?.chapterKey).toBe("v2c001");
  });

  it("flattens visible rows for the tree rail", () => {
    const rows = flattenOutlineTree(toOutlineNodes(dto), new Set(["kernel", "v1", "u1"]));
    expect(rows.map((row) => row.level)).toEqual([
      "kernel",
      "volume",
      "unit",
      "chapter",
      "volume",
    ]);
  });
});
