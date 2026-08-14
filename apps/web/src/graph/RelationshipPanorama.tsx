import { useEffect, useRef } from "react";
import { Graph, NodeEvent } from "@antv/g6";
import { toG6Data, type ChapterRange, type GraphDto } from "./mapGraphDto";

type Props = {
  dto: GraphDto | null;
  range?: ChapterRange;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
};

export function RelationshipPanorama({ dto, range, selectedId, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const selectedRef = useRef<string | null>(null);

  useEffect(() => {
    const container = host.current;
    if (!container || !dto) {
      return;
    }
    const mapped = toG6Data(dto, range);
    const graph = new Graph({
      container,
      autoFit: "view",
      padding: 56,
      data: { nodes: mapped.nodes, edges: mapped.edges },
      layout: { type: "force", preventOverlap: true, nodeSize: 72, linkDistance: 148 },
      node: {
        type: "circle",
        style: {
          cursor: "pointer",
          labelPlacement: "center",
          labelFill: "#efe6d6",
          labelFontSize: 12,
          labelFontWeight: 600,
          labelFontFamily: '"Noto Serif SC", "Source Serif 4", serif',
          labelWordWrap: true,
          labelMaxWidth: 46,
        },
        state: {
          selected: {
            stroke: "#d45a45",
            lineWidth: 3,
            shadowColor: "rgba(212, 90, 69, 0.5)",
            shadowBlur: 18,
            size: 60,
          },
        },
      },
      edge: {
        style: {
          endArrow: true,
          lineWidth: 1.6,
          labelAutoRotate: false,
          labelPlacement: "center",
          labelFontSize: 10,
          labelFill: "#efe6d6",
          labelFontFamily: '"IBM Plex Sans", "Noto Sans SC", sans-serif',
          labelBackground: true,
          labelBackgroundFill: "rgba(16, 20, 26, 0.9)",
          labelBackgroundRadius: 3,
          labelPadding: [3, 7],
          labelWordWrap: true,
          labelMaxWidth: 88,
        },
      },
      behaviors: ["drag-canvas", "zoom-canvas", "drag-element"],
    });
    graph.render();
    graph.on(NodeEvent.CLICK, (event) => {
      const target = (event as { target?: { id?: string } }).target;
      onSelect(target?.id ?? null);
    });
    graph.on("canvas:click", () => onSelect(null));
    graphRef.current = graph;
    if (selectedRef.current) {
      void graph.setElementState(selectedRef.current, "selected");
    }
    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, [dto, range, onSelect]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) {
      return;
    }
    const previous = selectedRef.current;
    if (previous && previous !== selectedId) {
      void graph.setElementState(previous, []);
    }
    if (selectedId) {
      void graph.setElementState(selectedId, "selected");
      try {
        void graph.focusElement(selectedId);
      } catch {
        // 节点尚未就绪时忽略
      }
    }
    selectedRef.current = selectedId;
  }, [selectedId]);

  const mapped = dto ? toG6Data(dto, range) : { nodes: [], edges: [] };
  const selectedLabel =
    dto?.nodes.find((node) => node.id === selectedId)?.label ?? selectedId;

  if (!dto) {
    return <div className="panorama empty">尚无关系图。完成 R3 后会出现人物与势力。</div>;
  }
  if (dto.nodes.length === 0) {
    return <div className="panorama empty">空图（R1 后仍无角色，属正常）。</div>;
  }
  return (
    <div className="panorama-shell">
      <div className="panorama-meta">
        力导向 · 当前 {mapped.edges.length} / {dto.edges.length}
      </div>
      <div className="panorama-pick">
        {selectedId ? `已选 · ${selectedLabel}` : "未选择人物"}
      </div>
      <div className="panorama" ref={host} />
      <div className="panorama-tools">
        <span>图谱</span>
        <button type="button" onClick={() => void graphRef.current?.zoomBy(1.2)}>
          放大
        </button>
        <button type="button" onClick={() => void graphRef.current?.zoomBy(0.8)}>
          缩小
        </button>
        <button type="button" onClick={() => void graphRef.current?.fitView()}>
          居中
        </button>
      </div>
      <div className="panorama-hint">点击节点查看档案</div>
    </div>
  );
}
