export function locateQuote(quote: string, text: string): { start: number; end: number } | null {
  if (!quote || !text) {
    return null;
  }
  const start = text.indexOf(quote);
  if (start < 0) {
    return null;
  }
  return { start, end: start + quote.length };
}

export type HighlightSegment = { text: string; hit: boolean };

export function highlightSegments(text: string, quotes: string[]): HighlightSegment[] {
  const spans = quotes
    .map((quote) => locateQuote(quote, text))
    .filter((span): span is { start: number; end: number } => span !== null)
    .sort((left, right) => left.start - right.start);
  const segments: HighlightSegment[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start < cursor) {
      continue;
    }
    if (span.start > cursor) {
      segments.push({ text: text.slice(cursor, span.start), hit: false });
    }
    segments.push({ text: text.slice(span.start, span.end), hit: true });
    cursor = span.end;
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), hit: false });
  }
  return segments;
}
