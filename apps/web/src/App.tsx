import { useCallback, useEffect, useMemo, useState } from "react";
import {
  api,
  type BibleSnapshot,
  type ChapterRow,
  type PendingRound,
  type Project,
} from "./api";
import { RelationshipPanorama } from "./graph/RelationshipPanorama";
import {
  MISSING_EVIDENCE,
  inspectorFor,
  labeledEvidence,
  type ChapterRange,
  type GraphDto,
} from "./graph/mapGraphDto";

function artifactText(pending: PendingRound | null): string {
  if (!pending) {
    return "圣经已完成。";
  }
  return JSON.stringify(pending.artifact, null, 2);
}

export function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [title, setTitle] = useState("说书人传奇");
  const [spark, setSpark] = useState("说书人发现故事会成真");
  const [autoBible, setAutoBible] = useState(true);
  const [bible, setBible] = useState<BibleSnapshot | null>(null);
  const [graph, setGraph] = useState<GraphDto | null>(null);
  const [chapters, setChapters] = useState<ChapterRow[]>([]);
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [rangeFrom, setRangeFrom] = useState("");
  const [rangeTo, setRangeTo] = useState("");
  const [kernelSelect, setKernelSelect] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const range: ChapterRange | undefined = useMemo(() => {
    if (!rangeFrom && !rangeTo) {
      return undefined;
    }
    return { from: rangeFrom || undefined, to: rangeTo || undefined };
  }, [rangeFrom, rangeTo]);

  const loadProjects = useCallback(async () => {
    setProjects(await api.listProjects());
  }, []);

  const loadDesk = useCallback(async (id: number) => {
    const [nextBible, nextGraph, nextChapters] = await Promise.all([
      api.getBible(id),
      api.getGraph(id),
      api.listChapters(id),
    ]);
    setBible(nextBible);
    setGraph(nextGraph);
    setChapters(nextChapters);
  }, []);

  useEffect(() => {
    loadProjects().catch((err: Error) => setError(err.message));
  }, [loadProjects]);

  useEffect(() => {
    if (selectedId == null) {
      return;
    }
    loadDesk(selectedId).catch((err: Error) => setError(err.message));
  }, [selectedId, loadDesk]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const inspector = nodeId && graph ? inspectorFor(graph, nodeId, range) : null;
  const selectedProject = projects.find((item) => item.id === selectedId) ?? null;

  return (
    <div className="app">
      <header className="masthead">
        <div>
          <div className="eyebrow">Local writing desk</div>
          <h1>墨案</h1>
        </div>
        <div className="muted">{selectedProject?.title ?? "未打开作品"}</div>
      </header>
      <div className="desk">
        <aside className="rail">
          <h2>作品</h2>
          {projects.map((project) => (
            <button
              key={project.id}
              className={`project-card${project.id === selectedId ? " active" : ""}`}
              onClick={() => setSelectedId(project.id)}
              type="button"
            >
              <div>{project.title}</div>
              <small>
                #{project.id} · {project.completed_rounds.join(" ") || "未开书"}
              </small>
            </button>
          ))}
          <form
            className="stack"
            onSubmit={(event) => {
              event.preventDefault();
              void run(async () => {
                const created = await api.createProject(title, spark, autoBible);
                await loadProjects();
                setSelectedId(created.id);
                if (created.bible) {
                  setBible(created.bible);
                }
              });
            }}
          >
            <h2>从火花开书</h2>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题" />
            <textarea
              value={spark}
              onChange={(event) => setSpark(event.target.value)}
              rows={3}
              placeholder="一句话火花"
            />
            <label className="muted">
              <input
                type="checkbox"
                checked={autoBible}
                onChange={(event) => setAutoBible(event.target.checked)}
              />{" "}
              自动跑完 R0–R5（等同 CLI --yes）
            </label>
            <button className="btn teal" disabled={busy} type="submit">
              开书
            </button>
          </form>
          {error ? <p className="error">{error}</p> : null}
        </aside>
        <main className="stage">
          <section className="panel">
            <h2>对话 · R0–R5</h2>
            {bible ? (
              <>
                <div className="muted">已确认 {bible.completed.join(" → ") || "（无）"}</div>
                {bible.pending ? (
                  <article className="round-card">
                    <strong>
                      {bible.pending.kind} · {bible.pending.prompt}
                    </strong>
                    <pre>{artifactText(bible.pending)}</pre>
                    <div className="row" style={{ marginTop: "0.6rem" }}>
                      {bible.pending.round === 1 ? (
                        <input
                          type="number"
                          min={1}
                          value={kernelSelect}
                          onChange={(event) => setKernelSelect(Number(event.target.value))}
                          style={{ width: "4rem" }}
                        />
                      ) : null}
                      <button
                        className="btn"
                        disabled={busy}
                        type="button"
                        onClick={() =>
                          void run(async () => {
                            if (selectedId == null || !bible.pending) {
                              return;
                            }
                            const next = await api.confirmRound(
                              selectedId,
                              bible.pending.round,
                              kernelSelect,
                            );
                            setBible(next);
                            await loadDesk(selectedId);
                          })
                        }
                      >
                        确认并进入下一轮
                      </button>
                    </div>
                  </article>
                ) : (
                  <p className="muted">全部轮次已确认。可在下方章节轨开写。</p>
                )}
              </>
            ) : (
              <p className="muted">选择或创建一个作品。</p>
            )}
          </section>
          <section className="panel">
            <h2>关系全景</h2>
            <div className="range">
              <span>章节范围</span>
              <input
                value={rangeFrom}
                placeholder="v1c001"
                onChange={(event) => setRangeFrom(event.target.value)}
              />
              <span>—</span>
              <input
                value={rangeTo}
                placeholder="v1c005"
                onChange={(event) => setRangeTo(event.target.value)}
              />
            </div>
            <RelationshipPanorama
              dto={graph}
              range={range}
              selectedId={nodeId}
              onSelect={setNodeId}
            />
          </section>
        </main>
        <aside className="inspector">
          <h2>人物检视</h2>
          {inspector && nodeId ? (
            <>
              <p>
                <strong>{nodeId}</strong>
                <br />
                <span className="muted">度数 {inspector.degree}</span>
              </p>
              <ul className="tracks">
                {inspector.evidence.map((item, index) => (
                  <li key={`${item}-${index}`}>{item}</li>
                ))}
              </ul>
              <h2>关系轨迹</h2>
              <ul className="tracks">
                {inspector.tracks.map((track) => (
                  <li key={track.parties.join("-")}>
                    {track.parties.join(" · ")}
                    {track.beats.map((beat) => (
                      <div key={beat.chapter_key} className="muted">
                        {beat.chapter_key}: {beat.from_state} → {beat.to_state}
                        <br />
                        {labeledEvidence(beat.evidence)}
                      </div>
                    ))}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted">点选图中人物。无证据时标注「{MISSING_EVIDENCE}」。</p>
          )}
          <h2>全部轨迹</h2>
          <ul className="tracks">
            {(graph?.tracks ?? []).map((track) => (
              <li key={track.parties.join("-")}>{track.parties.join(" · ")}</li>
            ))}
          </ul>
        </aside>
      </div>
      <footer className="chapter-rail">
        {chapters.length === 0 ? <span className="muted">尚无章节</span> : null}
        {chapters.map((chapter) => (
          <div key={chapter.chapter_key} className="slug">
            <div className="key">{chapter.chapter_key}</div>
            <div className="muted">{chapter.status}</div>
            <div className="row">
              <button
                className="btn ghost"
                disabled={busy || selectedId == null}
                type="button"
                onClick={() =>
                  void run(async () => {
                    if (selectedId == null) {
                      return;
                    }
                    await api.writeChapter(selectedId, chapter.chapter_key);
                    await loadDesk(selectedId);
                  })
                }
              >
                开写
              </button>
              <button
                className="btn ghost"
                disabled={busy || selectedId == null || chapter.status !== "HUMAN_REVIEW"}
                type="button"
                onClick={() =>
                  void run(async () => {
                    if (selectedId == null) {
                      return;
                    }
                    await api.approveChapter(selectedId, chapter.chapter_key);
                    await loadDesk(selectedId);
                  })
                }
              >
                批准
              </button>
            </div>
          </div>
        ))}
        {selectedId != null ? (
          <div className="row" style={{ alignItems: "center" }}>
            <button
              className="btn ghost"
              disabled={busy}
              type="button"
              onClick={() =>
                void run(async () => {
                  await api.writeBatch(selectedId, 3, false);
                  await loadDesk(selectedId);
                })
              }
            >
              批次 3 章
            </button>
            <button
              className="btn ghost"
              disabled={busy}
              type="button"
              onClick={() =>
                void run(async () => {
                  await api.resume(selectedId);
                  await loadDesk(selectedId);
                })
              }
            >
              续跑
            </button>
            <button
              className="btn"
              disabled={busy}
              type="button"
              onClick={() =>
                void run(async () => {
                  const text = await api.exportMarkdown(selectedId);
                  const blob = new Blob([text], { type: "text/markdown" });
                  const url = URL.createObjectURL(blob);
                  const link = document.createElement("a");
                  link.href = url;
                  link.download = `project-${selectedId}.md`;
                  link.click();
                  URL.revokeObjectURL(url);
                })
              }
            >
              导出 MD
            </button>
          </div>
        ) : null}
      </footer>
    </div>
  );
}
