export const EXPORT_CHANNELS = ["generic", "qidian", "fanqie", "epub"] as const;
export const EXPORT_FORMATS = ["txt", "md", "epub"] as const;

export type ExportChannel = (typeof EXPORT_CHANNELS)[number];
export type ExportFormat = (typeof EXPORT_FORMATS)[number];

export function channelLabel(channel: ExportChannel): string {
  switch (channel) {
    case "generic":
      return "generic";
    case "qidian":
      return "起点";
    case "fanqie":
      return "番茄";
    case "epub":
      return "EPUB";
    default: {
      const exhaustive: never = channel;
      return exhaustive;
    }
  }
}

export function resolveExportSelection(
  channel: ExportChannel,
  format: ExportFormat,
): { channel: ExportChannel; format: ExportFormat } {
  if (format === "epub" || channel === "epub") {
    return { channel: "epub", format: "epub" };
  }
  return { channel, format };
}

export function exportDownloadName(
  projectId: number,
  channel: ExportChannel,
  format: ExportFormat,
): string {
  const resolved = resolveExportSelection(channel, format);
  return `project-${projectId}-${resolved.channel}.${resolved.format}`;
}

export function exportQuery(
  projectId: number,
  channel: ExportChannel,
  format: ExportFormat,
  includeDrafts = false,
): string {
  const resolved = resolveExportSelection(channel, format);
  const params = new URLSearchParams({
    channel: resolved.channel,
    format: resolved.format,
  });
  if (includeDrafts) {
    params.set("include_drafts", "true");
  }
  return `/projects/${projectId}/export?${params.toString()}`;
}
