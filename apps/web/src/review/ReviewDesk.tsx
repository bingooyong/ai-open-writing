import { useMemo, useState } from "react";
import type { ReviewItem } from "../api";
import { highlightSegments } from "./locateQuote";
import {
  READER_FONT_SIZES,
  READER_LINE_HEIGHTS,
  READER_MEASURES,
  READER_PARAGRAPH_GAPS,
  readerFontFamily,
} from "./readerSettings";
import { splitParagraphs } from "./readerText";
import { useReaderSettings } from "./useReaderSettings";

const STATUS_LABEL: Record<string, string> = {
  HUMAN_REVIEW: "待审",
  CANON_LOCKED: "已锁定",
  EXPORTED: "已锁定",
  JUDGING: "裁决中",
  NEEDS_REPLAN: "待重规划",
  NEEDS_REVISION: "待修订",
  DRAFTING: "起草中",
  ADVERSARIAL_REVIEW: "评审中",
  APPROVED: "已批准",
  STALE: "已作废",
  PLANNED: "已规划",
  IN_PROGRESS: "进行中",
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

function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

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
  const { settings, setSettings } = useReaderSettings();
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
  const paragraphs = useMemo(
    () => (selected ? splitParagraphs(selected.draft_text) : []),
    [selected],
  );
  const canGate = selected?.status === "HUMAN_REVIEW";

  if (items.length === 0) {
    return <p className="muted">尚无可读草稿。有正文的章节会出现在这里。</p>;
  }

  return (
    <div className="review-desk">
      <nav className="review-toc" aria-label="章节目录">
        {items.map((item) => (
          <button
            key={item.chapter_key}
            className={`toc-row${item.chapter_key === selectedKey ? " active" : ""}`}
            type="button"
            onClick={() => onSelect(item.chapter_key)}
          >
            <span className="toc-title">{item.heading || item.title || item.chapter_key}</span>
            <span className="toc-status">{statusLabel(item.status)}</span>
          </button>
        ))}
      </nav>
      <div className="review-page">
        <div className="reader-chrome">
          <label>
            字号
            <select
              aria-label="字号"
              value={settings.fontSize}
              onChange={(event) => setSettings({ fontSize: Number(event.target.value) })}
            >
              {READER_FONT_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <label>
            行距
            <select
              aria-label="行距"
              value={settings.lineHeight}
              onChange={(event) => setSettings({ lineHeight: Number(event.target.value) })}
            >
              {READER_LINE_HEIGHTS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            段距
            <select
              aria-label="段距"
              value={settings.paragraphGap}
              onChange={(event) => setSettings({ paragraphGap: Number(event.target.value) })}
            >
              {READER_PARAGRAPH_GAPS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            栏宽
            <select
              aria-label="栏宽"
              value={settings.measure}
              onChange={(event) => setSettings({ measure: Number(event.target.value) })}
            >
              {READER_MEASURES.map((value) => (
                <option key={value} value={value}>
                  {value}em
                </option>
              ))}
            </select>
          </label>
          <label>
            字体
            <select
              aria-label="字体"
              value={settings.font}
              onChange={(event) =>
                setSettings({ font: event.target.value as typeof settings.font })
              }
            >
              <option value="ui">界面</option>
              <option value="song">宋体</option>
              <option value="hei">黑体</option>
            </select>
          </label>
        </div>
        {selected ? (
          <article
            className="reader-article"
            style={{
              fontSize: `${settings.fontSize}px`,
              lineHeight: settings.lineHeight,
              maxWidth: `${settings.measure}em`,
              fontFamily: readerFontFamily(settings.font),
            }}
          >
            <header className="reader-header">
              <h3>{selected.heading || selected.title || selected.chapter_key}</h3>
              <p className="muted">
                {selected.chapter_key} · {statusLabel(selected.status)}
                {selected.verdict ? ` · ${selected.verdict}` : ""}
              </p>
            </header>
            {paragraphs.length === 0 ? (
              <p className="muted">（无正文）</p>
            ) : (
              paragraphs.map((paragraph, index) => (
                <p key={`${index}-${paragraph.slice(0, 12)}`} style={{ marginBottom: `${settings.paragraphGap}em` }}>
                  {highlightSegments(paragraph, quotes).map((segment, segmentIndex) =>
                    segment.hit ? (
                      <mark key={`${segment.text}-${segmentIndex}`}>{segment.text}</mark>
                    ) : (
                      <span key={`${segment.text}-${segmentIndex}`}>{segment.text}</span>
                    ),
                  )}
                </p>
              ))
            )}
          </article>
        ) : (
          <p className="muted reader-empty">从左侧选一章阅读。</p>
        )}
      </div>
      <aside className="review-notes">
        {selected ? (
          <>
            <h2>裁决</h2>
            <p className="muted">
              {selected.verdict ? selected.verdict : "尚无裁决"}
            </p>
            {selected.verdict_payload?.reasoning_summary ? (
              <p>{String(selected.verdict_payload.reasoning_summary)}</p>
            ) : null}
            <h2>问题与证据</h2>
            {selected.issues.length === 0 ? (
              <p className="muted">没有列出的问题。</p>
            ) : (
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
            )}
            {selected.diff ? (
              <>
                <h2>与上一稿</h2>
                <pre className="diff-view">{selected.diff}</pre>
              </>
            ) : (
              <p className="muted">仅一稿。</p>
            )}
            <div className="row" style={{ marginTop: "0.6rem" }}>
              <button
                className="btn teal"
                disabled={busy || !canGate}
                type="button"
                onClick={() => onApprove(selected.chapter_key)}
              >
                批准
              </button>
              <button
                className="btn ghost"
                disabled={busy || !canGate}
                type="button"
                onClick={() => onReject(selected.chapter_key)}
              >
                退回重规划
              </button>
            </div>
            <div className="row" style={{ marginTop: "0.4rem" }}>
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
          <p className="muted">选章后查看问题与裁决。</p>
        )}
      </aside>
    </div>
  );
}
