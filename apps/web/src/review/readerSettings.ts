export const READER_STORAGE_KEY = "moan-reader-v2";

export type ReaderFont = "ui" | "song" | "hei";

export type ReaderSettings = {
  fontSize: number;
  lineHeight: number;
  paragraphGap: number;
  measure: number;
  font: ReaderFont;
};

export const READER_DEFAULTS: ReaderSettings = {
  fontSize: 18,
  lineHeight: 1.8,
  paragraphGap: 0.85,
  measure: 48,
  font: "ui",
};

export const READER_FONT_SIZES = [16, 18, 20, 22, 24] as const;
export const READER_LINE_HEIGHTS = [1.5, 1.7, 1.8, 1.9, 2.2] as const;
export const READER_PARAGRAPH_GAPS = [0.5, 0.85, 1.2] as const;
export const READER_MEASURES = [38, 42, 48, 56, 64] as const;

function nearest(value: number, allowed: readonly number[]): number {
  return allowed.reduce((best, item) =>
    Math.abs(item - value) < Math.abs(best - value) ? item : best,
  );
}

function asFont(value: unknown): ReaderFont {
  if (value === "ui" || value === "song" || value === "hei") {
    return value;
  }
  return "ui";
}

export function clampReaderSettings(raw: unknown): ReaderSettings {
  const input = raw && typeof raw === "object" ? (raw as Partial<ReaderSettings>) : {};
  return {
    fontSize: nearest(Number(input.fontSize) || READER_DEFAULTS.fontSize, READER_FONT_SIZES),
    lineHeight: nearest(
      Number(input.lineHeight) || READER_DEFAULTS.lineHeight,
      READER_LINE_HEIGHTS,
    ),
    paragraphGap: nearest(
      Number(input.paragraphGap) || READER_DEFAULTS.paragraphGap,
      READER_PARAGRAPH_GAPS,
    ),
    measure: nearest(Number(input.measure) || READER_DEFAULTS.measure, READER_MEASURES),
    font: asFont(input.font),
  };
}

export function readStoredReaderSettings(): ReaderSettings {
  try {
    const raw = localStorage.getItem(READER_STORAGE_KEY);
    return clampReaderSettings(raw ? JSON.parse(raw) : null);
  } catch {
    return READER_DEFAULTS;
  }
}

export function persistReaderSettings(settings: ReaderSettings): void {
  try {
    localStorage.setItem(READER_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // 隐私模式或禁用存储时忽略
  }
}

export function readerFontFamily(font: ReaderFont): string {
  switch (font) {
    case "ui":
      return "inherit";
    case "song":
      return '"Songti SC", "STSong", "SimSun", "Noto Serif SC", serif';
    case "hei":
      return '"Heiti SC", "STHeiti", "SimHei", "Noto Sans SC", sans-serif';
    default: {
      const exhaustive: never = font;
      return exhaustive;
    }
  }
}
