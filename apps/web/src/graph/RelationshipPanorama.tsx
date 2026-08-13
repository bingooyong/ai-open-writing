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

  useEffect(() => {
    const container = host.current;
    if (!container || !dto) {
      return;
    }
    const mapped = toG6Data(dto, range);
    const graph = new Graph({
      container,
      autoFit: "view",
      data: { nodes: mapped.nodes, edges: mapped.edges },
      layout: { type: "force", preventOverlap: true },
      node: {
        type: "circle",
        style: {
          size: 28,
          labelPlacement: "bottom",
          labelFill: "#182231",
          labelFontSize: 11,
          labelFontFamily: '"IBM Plex Sans", "Noto Sans SC", sans-serif',
        },
      },
      edge: {
        style: {
          endArrow: true,
          labelFontSize: 10,
          labelFill: "#3d4d66",
          labelBackground: true,
          labelBackgroundFill: "#f4f7fa",
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
    return () => {
      graph.destroy();
      graphRef.current = null;
    };
  }, [dto, range, onSelect]);

  useEffect(() => {
    const graph = graphRef.current;
    if (!graph || !selectedId) {
      return;
    }
    try {
      graph.focusElement(selectedId);
    } catch {
      // 节点尚未就绪时忽略
    }
  }, [selectedId]);

  if (!dto) {
    return <div className="panorama empty">尚无关系图。完成 R3 后会出现人物与势力。</div>;
  }
  if (dto.nodes.length === 0) {
    return <div className="panorama empty">空图（R1 后仍无角色，属正常）。</div>;
  }
  return <div className="panorama" ref={host} />;
}
