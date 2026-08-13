import { describe, expect, it } from "vitest";
import { highlightSegments, locateQuote } from "./locateQuote";

describe("locateQuote", () => {
  it("returns the exact span when the quote is in the draft", () => {
    const text = "临安茶楼里灯火通明，苏晚生一拍醒木，满堂皆静。";
    const quote = "茶楼里灯火通明，苏晚生一拍醒木";
    expect(locateQuote(quote, text)).toEqual({ start: 2, end: 2 + quote.length });
  });

  it("does not invent a span when the quote is absent", () => {
    expect(locateQuote("正文里根本没有这句话而且足够长", "茶楼灯火")).toBeNull();
    expect(locateQuote("", "茶楼灯火")).toBeNull();
  });
});

describe("highlightSegments", () => {
  it("wraps only locatable quotes", () => {
    const text = "甲乙丙丁";
    const segments = highlightSegments(text, ["乙丙", "并不存在"]);
    expect(segments).toEqual([
      { text: "甲", hit: false },
      { text: "乙丙", hit: true },
      { text: "丁", hit: false },
    ]);
  });
});
