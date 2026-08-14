import { describe, expect, it } from "vitest";
import {
  channelLabel,
  exportDownloadName,
  exportQuery,
  resolveExportSelection,
} from "./channelExport";

describe("channel export desk helpers", () => {
  it("labels channels for the desk dropdown", () => {
    expect(channelLabel("qidian")).toBe("起点");
    expect(channelLabel("fanqie")).toBe("番茄");
  });

  it("keeps generic markdown as the default pair", () => {
    expect(resolveExportSelection("generic", "md")).toEqual({
      channel: "generic",
      format: "md",
    });
    expect(exportQuery(3, "generic", "md")).toBe("/projects/3/export?channel=generic&format=md");
  });

  it("implies epub channel when format is epub", () => {
    expect(resolveExportSelection("qidian", "epub")).toEqual({
      channel: "epub",
      format: "epub",
    });
    expect(exportDownloadName(1, "generic", "epub")).toBe("project-1-epub.epub");
  });

  it("adds include_drafts for desk preview", () => {
    expect(exportQuery(2, "fanqie", "txt", true)).toBe(
      "/projects/2/export?channel=fanqie&format=txt&include_drafts=true",
    );
  });
});
