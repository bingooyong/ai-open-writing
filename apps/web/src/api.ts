import type { ConceptJudgeState } from "./bible/mapConceptJudge";
import type { OutlineTreeDto } from "./outline/mapOutlineTree";

export type Project = {
  id: number;
  title: string;
  genre: string;
  status: string;
  spark: string;
  brief: string;
  completed_rounds: string[];
  enable_writer_b?: boolean;
  enable_reader_advocate?: boolean;
  bible?: BibleSnapshot;
};

export type PendingRound = {
  round: number;
  kind: string;
  prompt: string;
  artifact: Record<string, unknown>;
};

export type BibleSnapshot = {
  project_id: number;
  title: string;
  completed: string[];
  pending: PendingRound | null;
  brief: Record<string, unknown> | null;
  kernel: Record<string, unknown> | null;
  structure: Record<string, unknown> | null;
  characters: Array<Record<string, unknown>>;
  conflicts: Array<Record<string, unknown>>;
  payoffs: Array<Record<string, unknown>>;
  outlines: Array<Record<string, unknown>>;
  concept_judge: ConceptJudgeState;
  settings: {
    enable_writer_b: boolean;
    enable_reader_advocate: boolean;
  };
};

export type ChapterRow = {
  chapter_key: string;
  title: string;
  status: string;
  order_index: number;
  revision_round: number;
};

export type LoopResult = {
  project_id: number;
  chapter_key: string;
  status: string;
  verdict: string | null;
  revision_round: number;
  stopped_at: string;
  reason: string;
};

export type EvidenceSpan = {
  scene_id: string;
  quote: string;
  note: string;
  found: boolean;
  start: number | null;
  end: number | null;
};

export type ReviewIssueView = {
  issue_id: string;
  claim: string;
  severity: string;
  evidence: EvidenceSpan[];
};

export type ReviewItem = {
  chapter_key: string;
  title: string;
  status: string;
  bucket: "HUMAN_REVIEW" | "IN_PROGRESS" | "CANON_LOCKED";
  verdict: string | null;
  verdict_payload: Record<string, unknown> | null;
  draft_text: string;
  previous_draft_text: string | null;
  diff: string | null;
  issues: ReviewIssueView[];
  draft_id: number | null;
  locked_ranges: string[];
};

export type OutlineEditResult = {
  chapter_key: string;
  outline_version: number;
  status: string;
  title: string;
};

async function parse<T>(responsePromise: Promise<Response>): Promise<T> {
  const response = await responsePromise;
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  listProjects: () => parse<Project[]>(fetch("/projects")),
  createProject: (title: string, spark: string, autoBible: boolean) =>
    parse<Project>(
      fetch("/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, spark, auto_bible: autoBible }),
      }),
    ),
  getBible: (id: number) => parse<BibleSnapshot>(fetch(`/projects/${id}/bible`)),
  patchProject: (
    id: number,
    body: { enable_writer_b?: boolean; enable_reader_advocate?: boolean },
  ) =>
    parse<Project>(
      fetch(`/projects/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    ),
  confirmRound: (id: number, round: number, select = 1) =>
    parse<BibleSnapshot>(
      fetch(`/projects/${id}/bible/rounds/${round}/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ select }),
      }),
    ),
  getGraph: (id: number) => parse<GraphDto>(fetch(`/projects/${id}/graph`)),
  listChapters: (id: number) => parse<ChapterRow[]>(fetch(`/projects/${id}/chapters`)),
  getOutlineTree: (id: number) => parse<OutlineTreeDto>(fetch(`/projects/${id}/outline-tree`)),
  getOutlineYaml: async (id: number, chapterKey: string) => {
    const response = await fetch(`/projects/${id}/chapters/${chapterKey}/outline.yaml`);
    if (!response.ok) {
      throw new Error(`导出章纲失败 HTTP ${response.status}`);
    }
    return response.text();
  },
  editOutline: (id: number, chapterKey: string, yaml: string) =>
    parse<OutlineEditResult>(
      fetch(`/projects/${id}/chapters/${chapterKey}/edit-outline`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml }),
      }),
    ),
  listReview: (id: number) => parse<ReviewItem[]>(fetch(`/projects/${id}/review`)),
  rejectChapter: (id: number, chapterKey: string) =>
    parse<{ chapter_key: string; status: string; stale: string[] }>(
      fetch(`/projects/${id}/chapters/${chapterKey}/reject`, { method: "POST" }),
    ),
  lockRanges: (id: number, chapterKey: string, ranges: string[]) =>
    parse<{ chapter_key: string; locked_ranges: string[] }>(
      fetch(`/projects/${id}/chapters/${chapterKey}/locked-ranges`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ranges }),
      }),
    ),
  writeChapter: (id: number, chapterKey: string) =>
    parse<LoopResult>(
      fetch(`/projects/${id}/chapters/${chapterKey}/write-chapter`, { method: "POST" }),
    ),
  approveChapter: (id: number, chapterKey: string) =>
    parse<LoopResult>(
      fetch(`/projects/${id}/chapters/${chapterKey}/approve`, { method: "POST" }),
    ),
  writeBatch: (id: number, chapters = 3, yes = false, fromChapter?: string) =>
    parse<{ results: LoopResult[] }>(
      fetch(`/projects/${id}/write-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chapters,
          yes,
          from_chapter: fromChapter ?? null,
        }),
      }),
    ),
  planMore: (id: number, body?: { window?: number; chapters?: number; open_volume?: boolean }) =>
    parse<{
      project_id: number;
      volume_id: string;
      unit_id: string;
      chapter_keys: string[];
      opened_new_volume: boolean;
      skipped: string[];
    }>(
      fetch(`/projects/${id}/plan-more`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body ?? { window: 5 }),
      }),
    ),
  resume: (id: number) =>
    parse<{ results: LoopResult[] }>(
      fetch(`/projects/${id}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yes: false }),
      }),
    ),
  exportMarkdown: async (id: number) => {
    const response = await fetch(`/projects/${id}/export?format=md`);
    if (!response.ok) {
      throw new Error(`导出失败 HTTP ${response.status}`);
    }
    return response.text();
  },
};
