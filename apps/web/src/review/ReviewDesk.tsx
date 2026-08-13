import { useMemo, useState } from "react";
import type { ReviewItem } from "../api";
import { highlightSegments } from "./locateQuote";

const BUCKETS = ["HUMAN_REVIEW", "IN_PROGRESS", "CANON_LOCKED"] as const;

const BUCKET_LABEL: Record<(typeof BUCKETS)[number], string> = {
  HUMAN_REVIEW: "待审",
  IN_PROGRESS: "进行中",
  CANON_LOCKED: "已锁定",
};

type ReviewDeskProps = {
  items: ReviewItem[];
  selectedKey: string | null;
  busy: boolean;
  onSelect: (chapterKey: string) => void;
  onApprove: (chapterKey: string) => void;
  onReject: (chapterKey: string) => void;
  onLock: (chapterKey: string, ranges: string[]) => void;
};

export function ReviewDesk({
  items,
  selectedKey,
  busy,
  onSelect,
  onApprove,
  onReject,
  onLock,
}: ReviewDeskProps) {
  const [lockText, setLockText] = useState("");
  const selected = items.find((item) => item.chapter_key === selectedKey) ?? null;
  const quotes = useMemo(
    () =>
      selected
        ? selected.issues.flatMap((issue) =>
            issue.evidence.filter((span) => span.found && span.quote).map((span) => span.quote),
          )
        : [],
    [selected],
  );
  const segments = useMemo(
    () => (selected ? highlightSegments(selected.draft_text, quotes) : []),
    [selected, quotes],
  );

  if (items.length === 0) {
    return <p className="muted">尚无待审、进行中或已锁定的章节。</p>;
  }

  return (
    <div className="review-desk">
      <div className="review-list">
        {BUCKETS.map((bucket) => {
          const rows = items.filter((item) => item.bucket === bucket);
          if (rows.length === 0) {
            return null;
          }
          return (
            <section key={bucket}>
              <h3>{BUCKET_LABEL[bucket]}</h3>
              {rows.map((item) => (
                <button
                  key={item.chapter_key}
                  className={`project-card${item.chapter_key === selectedKey ? " active" : ""}`}
                  type="button"
                  onClick={() => onSelect(item.chapter_key)}
                >
                  <div>{item.chapter_key}</div>
                  <small>
                    {item.status}
                    {item.verdict ? ` · ${item.verdict}` : ""}
                  </small>
                </button>
              ))}
            </section>
          );
        })}
      </div>
      <div className="review-detail">
        {selected ? (
          <>
            <h3>
              {selected.chapter_key} · {selected.title || selected.status}
            </h3>
            <p className="muted">
              {selected.status}
              {selected.verdict ? ` · 裁决 ${selected.verdict}` : " · 尚无裁决"}
            </p>
            {selected.verdict_payload?.reasoning_summary ? (
              <p>{String(selected.verdict_payload.reasoning_summary)}</p>
            ) : null}
            <h3>正文</h3>
            <article className="draft-view">
              {segments.length === 0 ? (
                <span className="muted">（无正文）</span>
              ) : (
                segments.map((segment, index) =>
                  segment.hit ? (
                    <mark key={`${segment.text}-${index}`}>{segment.text}</mark>
                  ) : (
                    <span key={`${segment.text}-${index}`}>{segment.text}</span>
                  ),
                )
              )}
            </article>
            <h3>问题与证据</h3>
            <ul className="issue-list">
              {selected.issues.map((issue) => (
                <li key={issue.issue_id}>
                  <strong>
                    {issue.severity} · {issue.issue_id}
                  </strong>
                  <div>{issue.claim}</div>
                  {issue.evidence.map((span, index) => (
                    <div key={`${issue.issue_id}-${index}`} className="muted">
                      {span.found ? "已定位" : "未在正文中定位"}：{span.quote}
                    </div>
                  ))}
                </li>
              ))}
            </ul>
            {selected.diff ? (
              <>
                <h3>与上一稿差异</h3>
                <pre className="diff-view">{selected.diff}</pre>
              </>
            ) : (
              <p className="muted">仅一稿，没有可对比的上一版本。</p>
            )}
            <div className="row" style={{ marginTop: "0.75rem" }}>
              <button
                className="btn teal"
                disabled={busy || selected.status !== "HUMAN_REVIEW"}
                type="button"
                onClick={() => onApprove(selected.chapter_key)}
              >
                批准
              </button>
              <button
                className="btn ghost"
                disabled={busy || selected.status !== "HUMAN_REVIEW"}
                type="button"
                onClick={() => onReject(selected.chapter_key)}
              >
                退回重规划
              </button>
            </div>
            <div className="row" style={{ marginTop: "0.45rem" }}>
              <input
                value={lockText}
                placeholder="锁定段落"
                onChange={(event) => setLockText(event.target.value)}
              />
              <button
                className="btn ghost"
                disabled={busy || !lockText.trim()}
                type="button"
                onClick={() => {
                  onLock(selected.chapter_key, [lockText.trim()]);
                  setLockText("");
                }}
              >
                写入锁定
              </button>
            </div>
            {selected.locked_ranges.length > 0 ? (
              <p className="muted">已锁定：{selected.locked_ranges.join(" · ")}</p>
            ) : null}
          </>
        ) : (
          <p className="muted">从左侧选择一章查看正文、裁决与证据。</p>
        )}
      </div>
    </div>
  );
}
