import { describe, expect, it } from "vitest";
import { clampReaderSettings, READER_DEFAULTS, readerFontFamily } from "./readerSettings";
import { splitParagraphs } from "./readerText";

describe("clampReaderSettings", () => {
  it("returns defaults for empty or invalid input", () => {
    expect(clampReaderSettings(null)).toEqual(READER_DEFAULTS);
    expect(clampReaderSettings({ fontSize: "huge" })).toEqual(READER_DEFAULTS);
  });

  it("snaps values to the allowed type scale", () => {
    const next = clampReaderSettings({
      fontSize: 19,
      lineHeight: 2.0,
      paragraphGap: 1,
      measure: 41.6,
      font: "song",
    });
    expect(next.fontSize).toBe(18);
    expect(next.lineHeight).toBe(1.9);
    expect(next.paragraphGap).toBe(0.85);
    expect(next.measure).toBe(42);
    expect(next.font).toBe("song");
  });
});

describe("readerFontFamily", () => {
  it("keeps the UI sans as inherit", () => {
    expect(readerFontFamily("ui")).toBe("inherit");
  });
});

describe("splitParagraphs", () => {
  it("splits on blank lines first", () => {
    expect(splitParagraphs("上段\n\n下段")).toEqual(["上段", "下段"]);
  });

  it("falls back to single newlines when the draft has no blank lines", () => {
    expect(splitParagraphs("第一段\n第二段")).toEqual(["第一段", "第二段"]);
  });

  it("returns empty for whitespace", () => {
    expect(splitParagraphs("  \n  ")).toEqual([]);
  });
});
