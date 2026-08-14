import type { VolumeRunStatus } from "../api";
import { mapVolumeConsole, type VolumeConsoleAction } from "./mapVolumeConsole";

const ACTION_LABEL: Record<VolumeConsoleAction, string> = {
  start: "跑一卷",
  stop: "停止",
  approve: "批准",
  resume: "续跑",
  "plan-more": "续规划",
  "open-volume": "开下一卷",
};

type VolumeRunConsoleProps = {
  status: VolumeRunStatus | null;
  budget: string;
  maxChapters: string;
  busy: boolean;
  onBudgetChange: (value: string) => void;
  onMaxChaptersChange: (value: string) => void;
  onStart: () => void;
  onStop: () => void;
  onApprove: (chapterKey: string) => void;
  onResume: () => void;
  onPlanMore: () => void;
  onOpenVolume: () => void;
};

export function VolumeRunConsole({
  status,
  budget,
  maxChapters,
  busy,
  onBudgetChange,
  onMaxChaptersChange,
  onStart,
  onStop,
  onApprove,
  onResume,
  onPlanMore,
  onOpenVolume,
}: VolumeRunConsoleProps) {
  const view = mapVolumeConsole(status);
  const showStartFields = view.actions.includes("start");
  const running = view.kind === "running" || view.kind === "stopping";

  function runAction(action: VolumeConsoleAction) {
    switch (action) {
      case "start":
        onStart();
        return;
      case "stop":
        onStop();
        return;
      case "approve":
        if (view.approveChapter) {
          onApprove(view.approveChapter);
        }
        return;
      case "resume":
        onResume();
        return;
      case "plan-more":
        onPlanMore();
        return;
      case "open-volume":
        onOpenVolume();
        return;
      default: {
        const _never: never = action;
        return _never;
      }
    }
  }

  return (
    <section className={`volume-console kind-${view.kind}`} aria-label="长跑控制台">
      <div className="volume-console-head">
        <h2>长跑控制台</h2>
        <strong>{view.headline}</strong>
      </div>
      <dl className="volume-console-metrics">
        <div>
          <dt>进度</dt>
          <dd>{view.progressLabel}</dd>
        </div>
        <div>
          <dt>花费</dt>
          <dd>{view.spendLabel}</dd>
        </div>
        <div>
          <dt>当前章</dt>
          <dd>{view.currentChapter || "—"}</dd>
        </div>
        <div>
          <dt>原因</dt>
          <dd>{view.stopReason || "—"}</dd>
        </div>
      </dl>
      <p className="muted volume-console-detail">{view.detail}</p>
      <div className="row volume-console-actions">
        {showStartFields ? (
          <>
            <label className="muted">
              $
              <input
                value={budget}
                onChange={(event) => onBudgetChange(event.target.value)}
                style={{ width: "4.5rem" }}
                inputMode="decimal"
                disabled={running}
                aria-label="卷长跑预算 USD"
              />
            </label>
            <label className="muted">
              章
              <input
                value={maxChapters}
                onChange={(event) => onMaxChaptersChange(event.target.value)}
                style={{ width: "3.5rem" }}
                inputMode="numeric"
                disabled={running}
                aria-label="最多章数"
              />
            </label>
          </>
        ) : null}
        {view.actions.map((action) => {
          const label =
            action === "approve" && view.approveChapter
              ? `批准 ${view.approveChapter}`
              : ACTION_LABEL[action];
          const disabled =
            busy ||
            (action === "approve" && !view.approveChapter) ||
            (action === "start" && running);
          return (
            <button
              key={action}
              className={action === "start" || action === "stop" ? "btn teal" : "btn ghost"}
              disabled={disabled}
              type="button"
              onClick={() => runAction(action)}
            >
              {label}
            </button>
          );
        })}
      </div>
    </section>
  );
}
