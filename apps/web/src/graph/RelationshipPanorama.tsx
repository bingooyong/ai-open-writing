import { useEffect, useRef } from "react";
import { Graph, NodeEvent } from "@antv/g6";
import type { ResolvedTheme } from "../theme/theme";
import { graphChrome, toG6Data, type ChapterRange, type GraphDto } from "./mapGraphDto";

type Props = {
  dto: GraphDto | null;
  range?: ChapterRange;
  selectedId: string | null;
  theme: ResolvedTheme;
  onSelect: (id: string | null) => void;
};

export function RelationshipPanorama({ dto, range, selectedId, theme, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const graphRef = useRef<Graph | null>(null);
  const selectedRef = useRef<string | null>(null);

  useEffect(() => {
    const container = host.current;
    if (!container || !dto) {
      return;
    }
    const mapped = toG6Data(dto, range, theme);
    const chrome = graphChrome(theme);
    const graph = new Graph({
      container,
      autoFit: "view",
      padding: 40,
      data: { nodes: mapped.nodes, edges: mapped.edges },
      layout: { type: "force", preventOverlap: true, nodeSize: 28, linkDistance: 110 },
      node: {
        type: "circle",
        style: {
          cursor: "pointer",
          labelPlacement: "bottom",
          labelFill: chrome.labelFill,
          labelFontSize: 11,
          labelFontFamily: '"IBM Plex Sans", "Noto Sans SC", sans-serif',
        },
        state: {
          selected: {
            fill: chrome.selectedFill,
            stroke: chrome.selectedFill,
            lineWidth: 1,
            size: 20,
          },
        },
      },
      edge: {
        style: {
          endArrow: true,
          lineWidth: 1,
          labelAutoRotate: false,
          labelPlacement: "center",
          labelFontSize: 10,
          labelFill: chrome.labelFill,
          labelFontFamily: '"IBM Plex Sans", "Noto Sans SC", sans-serif',
          labelBackground: true,
          labelBackgroundFill: chrome.labelBackgroundFill,
          labelPadding: [1, 4],
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
  }, [dto, range, theme, onSelect]);

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

  const mapped = dto ? toG6Data(dto, range, theme) : { nodes: [], edges: [] };
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
        {mapped.edges.length} / {dto.edges.length}
      </div>
      <div className="panorama-pick">{selectedId ? selectedLabel : ""}</div>
      <div className="panorama" ref={host} />
      <div className="panorama-tools">
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
      <div className="panorama-hint">点击节点查看</div>
    </div>
  );
}
