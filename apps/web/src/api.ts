import type { GraphDto } from "./graph/mapGraphDto";

export type Project = {
  id: number;
  title: string;
  genre: string;
  status: string;
  spark: string;
  brief: string;
  completed_rounds: string[];
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
  writeChapter: (id: number, chapterKey: string) =>
    parse<LoopResult>(
      fetch(`/projects/${id}/chapters/${chapterKey}/write-chapter`, { method: "POST" }),
    ),
  approveChapter: (id: number, chapterKey: string) =>
    parse<LoopResult>(
      fetch(`/projects/${id}/chapters/${chapterKey}/approve`, { method: "POST" }),
    ),
  writeBatch: (id: number, chapters = 3, yes = false) =>
    parse<{ results: LoopResult[] }>(
      fetch(`/projects/${id}/write-batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chapters, yes }),
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
