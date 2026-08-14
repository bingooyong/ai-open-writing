import type { VolumeRunStatus } from "../api";

export type VolumeConsoleAction = "start" | "stop" | "approve" | "resume" | "plan-more" | "open-volume";

export type VolumeConsoleKind =
  | "idle"
  | "running"
  | "stopping"
  | "gate"
  | "budget"
  | "cancelled"
  | "done"
  | "failed";

export type VolumeConsoleView = {
  kind: VolumeConsoleKind;
  headline: string;
  detail: string;
  currentChapter: string;
  approveChapter: string;
  chaptersDone: number;
  chaptersPlanned: number | null;
  progressLabel: string;
  spendLabel: string;
  stopReason: string;
  actions: VolumeConsoleAction[];
};

const STOP_LABEL: Record<string, string> = {
  HUMAN_REVIEW: "待批准",
  NEEDS_REPLAN: "需修订/续规划",
  STALE: "章已作废",
  BUDGET: "预算用尽",
  MAX_CHAPTERS: "已达章数上限",
  COMPLETE: "本卷写完",
  CANCELLED: "已停止",
};

function money(value: number): string {
  return `$${value.toFixed(2)}`;
}

function progressLabel(done: number, planned: number | null): string {
  if (planned == null) {
    return done > 0 ? `${done} 章` : "—";
  }
  return `${done} / ${planned} 章`;
}

function spendLabel(spent: number, budget: number): string {
  if (budget <= 0 && spent <= 0) {
    return "—";
  }
  return `${money(spent)} / ${money(budget)}`;
}

function emptyView(partial: Partial<VolumeConsoleView>): VolumeConsoleView {
  return {
    kind: "idle",
    headline: "空闲",
    detail: "设定预算后开跑。隔夜 mock 请带章数上限。",
    currentChapter: "",
    approveChapter: "",
    chaptersDone: 0,
    chaptersPlanned: null,
    progressLabel: "—",
    spendLabel: "—",
    stopReason: "",
    actions: ["start"],
    ...partial,
  };
}

function gateDetail(reason: string, chapter: string): string {
  switch (reason) {
    case "HUMAN_REVIEW":
      return chapter
        ? `${chapter} 待人工批准。批准或续跑后工厂才会写下一批。`
        : "有章节待人工批准。批准或续跑后工厂才会继续。";
    case "NEEDS_REPLAN":
      return chapter
        ? `${chapter} 需要修订或续规划。可用续规划 / 开下一卷，再续跑。`
        : "需要修订或续规划。可用续规划 / 开下一卷，再续跑。";
    case "STALE":
      return chapter
        ? `${chapter} 因前章退回已作废。续跑会按现章纲重写。`
        : "后续章因前章退回已作废。续跑会按现章纲重写。";
    case "BUDGET":
      return "本次 USD 上限已到。提高预算后再开跑，或直接续跑（仍受原上限约束）。";
    case "CANCELLED":
      return "已按请求在章与章之间停下，当前章不会被强杀。";
    case "MAX_CHAPTERS":
      return "已达本次章数上限。可再开跑，或先续规划 / 开下一卷。";
    case "COMPLETE":
      return "未锁定章已写完。要开下一卷请用开下一卷，或先续规划。";
    default: {
      const _exhaustive: string = reason;
      return _exhaustive ? `已停：${reason}` : "长跑已停。";
    }
  }
}

export function mapVolumeConsole(run: VolumeRunStatus | null): VolumeConsoleView {
  if (run == null || run.status === "idle") {
    return emptyView({ headline: "空闲" });
  }

  const planned = run.max_chapters;
  const base = {
    currentChapter: run.current_chapter,
    approveChapter: "",
    chaptersDone: run.chapters_done,
    chaptersPlanned: planned,
    progressLabel: progressLabel(run.chapters_done, planned),
    spendLabel: spendLabel(run.spent_usd, run.budget_usd),
    stopReason: run.stop_reason,
  };

  if (run.status === "running" && run.cancel_requested) {
    return emptyView({
      ...base,
      kind: "stopping",
      headline: run.current_chapter ? `正在停止 · 写完 ${run.current_chapter} 后歇` : "正在停止",
      detail: "已记下停止请求，当前章写完即停，不会杀进程。",
      actions: [],
    });
  }

  if (run.status === "running") {
    return emptyView({
      ...base,
      kind: "running",
      headline: run.current_chapter ? `长跑中 · 正在写 ${run.current_chapter}` : "长跑中",
      detail: "轮询工厂状态。章前进时会刷新大纲 / 审稿 / 章节轨。",
      actions: ["stop"],
    });
  }

  if (run.status === "failed") {
    return emptyView({
      ...base,
      kind: "failed",
      headline: "长跑失败",
      detail: run.stop_reason ? `失败：${run.stop_reason}` : "长跑失败，可续跑或重新开跑。",
      actions: ["resume", "start"],
    });
  }

  const reason = run.stop_reason;
  const reasonLabel = STOP_LABEL[reason] ?? (reason || "已停");

  if (reason === "BUDGET") {
    return emptyView({
      ...base,
      kind: "budget",
      headline: `已停 · ${reasonLabel}`,
      detail: gateDetail("BUDGET", run.current_chapter),
      actions: ["resume", "start"],
    });
  }

  if (reason === "CANCELLED" || run.status === "cancelled") {
    return emptyView({
      ...base,
      kind: "cancelled",
      headline: `已停 · ${reasonLabel}`,
      detail: gateDetail("CANCELLED", run.current_chapter),
      actions: ["resume", "start"],
    });
  }

  if (reason === "HUMAN_REVIEW") {
    return emptyView({
      ...base,
      kind: "gate",
      headline: run.current_chapter ? `已停 · 待批准 ${run.current_chapter}` : `已停 · ${reasonLabel}`,
      detail: gateDetail("HUMAN_REVIEW", run.current_chapter),
      approveChapter: run.current_chapter,
      actions: ["approve", "resume"],
    });
  }

  if (reason === "NEEDS_REPLAN") {
    return emptyView({
      ...base,
      kind: "gate",
      headline: `已停 · ${reasonLabel}`,
      detail: gateDetail("NEEDS_REPLAN", run.current_chapter),
      actions: ["plan-more", "open-volume", "resume"],
    });
  }

  if (reason === "STALE") {
    return emptyView({
      ...base,
      kind: "gate",
      headline: `已停 · ${reasonLabel}`,
      detail: gateDetail("STALE", run.current_chapter),
      actions: ["resume"],
    });
  }

  if (reason === "COMPLETE" || reason === "MAX_CHAPTERS") {
    return emptyView({
      ...base,
      kind: "done",
      headline: `已停 · ${reasonLabel}`,
      detail: gateDetail(reason, run.current_chapter),
      actions: ["plan-more", "open-volume", "start"],
    });
  }

  return emptyView({
    ...base,
    kind: "done",
    headline: `已停 · ${reasonLabel}`,
    detail: gateDetail(reason, run.current_chapter),
    actions: ["resume", "start"],
  });
}

export function volumeDeskDirty(prev: VolumeRunStatus | null, next: VolumeRunStatus): boolean {
  if (prev == null) {
    return true;
  }
  return (
    prev.status !== next.status ||
    prev.current_chapter !== next.current_chapter ||
    prev.chapters_done !== next.chapters_done ||
    prev.stop_reason !== next.stop_reason
  );
}
