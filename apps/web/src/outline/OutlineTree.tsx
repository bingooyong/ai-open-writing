import { useEffect, useMemo, useState } from "react";
import {
  findChapter,
  flattenOutlineTree,
  levelMark,
  toOutlineNodes,
  type OutlineTreeDto,
} from "./mapOutlineTree";

type OutlineTreeProps = {
  tree: OutlineTreeDto | null;
  selectedChapterKey: string | null;
  yaml: string;
  busy: boolean;
  onSelectChapter: (chapterKey: string) => void;
  onYamlChange: (value: string) => void;
  onSaveYaml: () => void;
};

export function OutlineTree({
  tree,
  selectedChapterKey,
  yaml,
  busy,
  onSelectChapter,
  onYamlChange,
  onSaveYaml,
}: OutlineTreeProps) {
  const nodes = useMemo(() => (tree ? toOutlineNodes(tree) : []), [tree]);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(["kernel"]));
  useEffect(() => {
    if (!tree) {
      return;
    }
    const ids = new Set<string>(["kernel"]);
    for (const volume of tree.volumes) {
      ids.add(volume.volume_id);
      for (const unit of volume.units) {
        ids.add(unit.unit_id);
      }
    }
    setExpanded(ids);
  }, [tree]);
  const rows = useMemo(() => flattenOutlineTree(nodes, expanded), [nodes, expanded]);
  const chapter = tree && selectedChapterKey ? findChapter(tree, selectedChapterKey) : null;

  function toggle(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  if (!tree) {
    return <p className="muted">选择作品后显示五级大纲。</p>;
  }

  return (
    <div className="outline-desk">
      <div className="tree">
        {rows.map((row) => {
          const active = row.chapterKey === selectedChapterKey;
          return (
            <div
              key={`${row.level}-${row.id}`}
              className={`tree-row${active ? " active" : ""}`}
              style={{ paddingLeft: `${0.35 + row.depth * 0.75}rem` }}
            >
              <button
                className="tree-toggle"
                type="button"
                disabled={row.children.length === 0}
                onClick={() => toggle(row.id)}
              >
                {row.children.length === 0 ? "·" : expanded.has(row.id) ? "▾" : "▸"}
              </button>
              <button
                className="tree-label"
                type="button"
                onClick={() => {
                  if (row.chapterKey) {
                    onSelectChapter(row.chapterKey);
                  } else {
                    toggle(row.id);
                  }
                }}
              >
                <span className="level-mark">{levelMark(row.level)}</span>
                {row.label}
              </button>
            </div>
          );
        })}
      </div>
      <div className="outline-detail">
        {chapter ? (
          <>
            <h3>
              {chapter.chapter_key} · {chapter.title}
            </h3>
            <p className="muted">{chapter.status}</p>
            <dl className="outline-fields">
              <dt>核心事件</dt>
              <dd>{String(chapter.outline.core_event ?? "—")}</dd>
              <dt>POV</dt>
              <dd>{String(chapter.outline.pov ?? "—")}</dd>
              <dt>起止</dt>
              <dd>
                {String(chapter.outline.start_state ?? "—")} →{" "}
                {String(chapter.outline.end_state ?? "—")}
              </dd>
            </dl>
            <h3>场景卡</h3>
            <ul className="scene-cards">
              {chapter.scenes.map((scene) => (
                <li key={scene.scene_id}>
                  <strong>{scene.scene_id}</strong>
                  <div>{scene.goal || "（无目标）"}</div>
                  <div className="muted">{scene.pov}</div>
                </li>
              ))}
            </ul>
            <h3>YAML</h3>
            <textarea
              className="yaml-edit"
              value={yaml}
              rows={12}
              onChange={(event) => onYamlChange(event.target.value)}
              spellCheck={false}
            />
            <button className="btn" disabled={busy || !yaml.trim()} type="button" onClick={onSaveYaml}>
              导入章纲
            </button>
          </>
        ) : (
          <p className="muted">点选章节查看章纲与场景卡。</p>
        )}
      </div>
    </div>
  );
}
