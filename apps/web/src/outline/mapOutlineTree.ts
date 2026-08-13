export type OutlineLevel = "kernel" | "volume" | "unit" | "chapter" | "scene";

export type OutlineSceneDto = {
  scene_id: string;
  chapter_key: string;
  goal?: string;
  pov?: string;
  [key: string]: unknown;
};

export type OutlineChapterDto = {
  chapter_key: string;
  title: string;
  status: string;
  order_index: number;
  outline: Record<string, unknown>;
  scenes: OutlineSceneDto[];
};

export type OutlineUnitDto = {
  unit_id: string;
  status: string;
  payload: Record<string, unknown>;
  chapters: OutlineChapterDto[];
};

export type OutlineVolumeDto = {
  volume_id: string;
  title: string;
  status: string;
  payload: Record<string, unknown>;
  units: OutlineUnitDto[];
};

export type OutlineKernelDto = {
  version: number;
  approved: boolean;
  logline: string;
  premise: string;
  payload?: Record<string, unknown>;
};

export type OutlineTreeDto = {
  project_id: number;
  kernel: OutlineKernelDto | null;
  volumes: OutlineVolumeDto[];
};

export type OutlineTreeNode = {
  id: string;
  level: OutlineLevel;
  label: string;
  chapterKey?: string;
  children: OutlineTreeNode[];
};

export type OutlineFlatRow = OutlineTreeNode & { depth: number };

function unitLabel(unit: OutlineUnitDto): string {
  const payload = unit.payload ?? {};
  const promise = payload.promise_or_debt;
  if (typeof promise === "string" && promise.trim()) {
    return promise;
  }
  return unit.unit_id;
}

function sceneLabel(scene: OutlineSceneDto): string {
  if (typeof scene.goal === "string" && scene.goal.trim()) {
    return scene.goal;
  }
  return scene.scene_id;
}

export function toOutlineNodes(dto: OutlineTreeDto): OutlineTreeNode[] {
  const volumes = dto.volumes.map((volume) => ({
    id: volume.volume_id,
    level: "volume" as const,
    label: volume.title || volume.volume_id,
    children: volume.units.map((unit) => ({
      id: unit.unit_id,
      level: "unit" as const,
      label: unitLabel(unit),
      children: unit.chapters.map((chapter) => ({
        id: chapter.chapter_key,
        level: "chapter" as const,
        label: `${chapter.chapter_key} ${chapter.title}`.trim(),
        chapterKey: chapter.chapter_key,
        children: chapter.scenes.map((scene) => ({
          id: scene.scene_id,
          level: "scene" as const,
          label: sceneLabel(scene),
          chapterKey: chapter.chapter_key,
          children: [],
        })),
      })),
    })),
  }));
  if (!dto.kernel) {
    return volumes;
  }
  return [
    {
      id: "kernel",
      level: "kernel",
      label: dto.kernel.logline || dto.kernel.premise || "故事内核",
      children: volumes,
    },
  ];
}

export function flattenOutlineTree(
  nodes: OutlineTreeNode[],
  expanded: Set<string>,
  depth = 0,
): OutlineFlatRow[] {
  const rows: OutlineFlatRow[] = [];
  for (const node of nodes) {
    rows.push({ ...node, depth });
    if (expanded.has(node.id) && node.children.length > 0) {
      rows.push(...flattenOutlineTree(node.children, expanded, depth + 1));
    }
  }
  return rows;
}

export function findChapter(
  dto: OutlineTreeDto,
  chapterKey: string,
): OutlineChapterDto | null {
  for (const volume of dto.volumes) {
    for (const unit of volume.units) {
      const hit = unit.chapters.find((chapter) => chapter.chapter_key === chapterKey);
      if (hit) {
        return hit;
      }
    }
  }
  return null;
}

export function levelMark(level: OutlineLevel): string {
  switch (level) {
    case "kernel":
      return "核";
    case "volume":
      return "卷";
    case "unit":
      return "元";
    case "chapter":
      return "章";
    case "scene":
      return "场";
    default: {
      const _never: never = level;
      return _never;
    }
  }
}
