import { describe, expect, it } from "vitest";
import { parseThemeMode, resolveTheme } from "./theme";

describe("parseThemeMode", () => {
  it("defaults unknown or empty values to system", () => {
    expect(parseThemeMode(null)).toBe("system");
    expect(parseThemeMode(undefined)).toBe("system");
    expect(parseThemeMode("")).toBe("system");
    expect(parseThemeMode("sepia")).toBe("system");
  });

  it("accepts system, light, and dark", () => {
    expect(parseThemeMode("system")).toBe("system");
    expect(parseThemeMode("light")).toBe("light");
    expect(parseThemeMode("dark")).toBe("dark");
  });
});

describe("resolveTheme", () => {
  it("follows the OS only when mode is system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });

  it("ignores OS preference when the user picked a theme", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
  });
});
