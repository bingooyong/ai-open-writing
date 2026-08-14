import { describe, expect, it } from "vitest";
import type { VolumeRunStatus } from "../api";
import { mapVolumeConsole, volumeDeskDirty } from "./mapVolumeConsole";

function status(partial: Partial<VolumeRunStatus> = {}): VolumeRunStatus {
  return {
    project_id: 1,
    run_id: 1,
    status: "idle",
    chapters_done: 0,
    chapter_keys: [],
    spent_usd: 0,
    budget_usd: 0,
    stop_reason: "",
    current_chapter: "",
    max_chapters: null,
    cancel_requested: false,
    ...partial,
  };
}

describe("mapVolumeConsole", () => {
  it("idle: only start", () => {
    const view = mapVolumeConsole(null);
    expect(view.kind).toBe("idle");
    expect(view.actions).toEqual(["start"]);
    expect(view.headline).toContain("空闲");
    expect(view.progressLabel).toBe("—");
  });

  it("running: current chapter, spend vs budget, stop", () => {
    const view = mapVolumeConsole(
      status({
        status: "running",
        current_chapter: "v1c003",
        chapters_done: 2,
        max_chapters: 8,
        spent_usd: 0.12,
        budget_usd: 1,
      }),
    );
    expect(view.kind).toBe("running");
    expect(view.currentChapter).toBe("v1c003");
    expect(view.headline).toContain("v1c003");
    expect(view.progressLabel).toBe("2 / 8 章");
    expect(view.spendLabel).toBe("$0.12 / $1.00");
    expect(view.actions).toEqual(["stop"]);
  });

  it("stopping: cancel requested while still running", () => {
    const view = mapVolumeConsole(
      status({
        status: "running",
        cancel_requested: true,
        current_chapter: "v1c003",
        chapters_done: 2,
        max_chapters: 8,
      }),
    );
    expect(view.kind).toBe("stopping");
    expect(view.headline).toContain("正在停止");
    expect(view.actions).toEqual([]);
  });

  it("HUMAN_REVIEW: approve current chapter and resume", () => {
    const view = mapVolumeConsole(
      status({
        status: "paused",
        stop_reason: "HUMAN_REVIEW",
        current_chapter: "v1c002",
        chapters_done: 1,
        max_chapters: 8,
        budget_usd: 1,
      }),
    );
    expect(view.kind).toBe("gate");
    expect(view.actions).toEqual(["approve", "resume"]);
    expect(view.approveChapter).toBe("v1c002");
    expect(view.detail).toMatch(/批准|审阅/);
    expect(view.headline).not.toBe("已停");
  });

  it("NEEDS_REPLAN: plan-more, open-volume, resume", () => {
    const view = mapVolumeConsole(
      status({
        status: "paused",
        stop_reason: "NEEDS_REPLAN",
        current_chapter: "v1c004",
      }),
    );
    expect(view.kind).toBe("gate");
    expect(view.actions).toEqual(["plan-more", "open-volume", "resume"]);
    expect(view.detail).toMatch(/规划|修订/);
  });

  it("STALE: resume to rewrite", () => {
    const view = mapVolumeConsole(
      status({
        status: "paused",
        stop_reason: "STALE",
        current_chapter: "v1c003",
      }),
    );
    expect(view.kind).toBe("gate");
    expect(view.actions).toEqual(["resume"]);
    expect(view.detail).toMatch(/作废|过期|STALE/);
  });

  it("BUDGET: say so and offer resume plus a new start", () => {
    const view = mapVolumeConsole(
      status({
        status: "paused",
        stop_reason: "BUDGET",
        spent_usd: 1.5,
        budget_usd: 1,
        chapters_done: 1,
        max_chapters: 8,
      }),
    );
    expect(view.kind).toBe("budget");
    expect(view.actions).toEqual(["resume", "start"]);
    expect(view.spendLabel).toBe("$1.50 / $1.00");
    expect(view.detail).toMatch(/预算/);
    expect(view.headline).toContain("预算");
  });

  it("CANCELLED: resume or start again", () => {
    const view = mapVolumeConsole(
      status({
        status: "cancelled",
        stop_reason: "CANCELLED",
        chapters_done: 1,
        current_chapter: "v1c002",
      }),
    );
    expect(view.kind).toBe("cancelled");
    expect(view.actions).toEqual(["resume", "start"]);
    expect(view.detail).toMatch(/停止|取消/);
  });

  it("COMPLETE: plan-more / open-volume instead of a dead stop", () => {
    const view = mapVolumeConsole(
      status({
        status: "succeeded",
        stop_reason: "COMPLETE",
        chapters_done: 8,
        max_chapters: 8,
      }),
    );
    expect(view.kind).toBe("done");
    expect(view.actions).toEqual(["plan-more", "open-volume", "start"]);
  });
});

describe("volumeDeskDirty", () => {
  it("refreshes the desk when chapter or status changes mid-run", () => {
    const prev = status({
      status: "running",
      current_chapter: "v1c001",
      chapters_done: 0,
    });
    expect(volumeDeskDirty(null, prev)).toBe(true);
    expect(volumeDeskDirty(prev, prev)).toBe(false);
    expect(
      volumeDeskDirty(prev, status({ status: "running", current_chapter: "v1c002", chapters_done: 1 })),
    ).toBe(true);
    expect(
      volumeDeskDirty(prev, status({ status: "paused", stop_reason: "HUMAN_REVIEW", current_chapter: "v1c001" })),
    ).toBe(true);
  });
});
