import { describe, expect, it } from "vitest";
import { conceptJudgeNotes, type ConceptJudgeState } from "./mapConceptJudge";

describe("conceptJudgeNotes", () => {
  it("returns empty when no verdicts", () => {
    expect(conceptJudgeNotes(null)).toEqual([]);
    expect(conceptJudgeNotes({ after_r2: null, after_r4: null })).toEqual([]);
  });

  it("formats PASS and REJECT notes for the conversation panel", () => {
    const state: ConceptJudgeState = {
      after_r2: {
        verdict: "PASS",
        after_round: "R2",
        reasons: ["黄金三章有当场问题"],
        repair_attempted: false,
        repair_notes: "",
      },
      after_r4: {
        verdict: "REJECT",
        after_round: "R4",
        reasons: ["终局资源提前透支", "冲突不改关系"],
        repair_attempted: true,
        repair_notes: "把兑现推后",
      },
    };
    const notes = conceptJudgeNotes(state);
    expect(notes[0]).toContain("R2");
    expect(notes[0]).toContain("PASS");
    expect(notes[0]).toContain("黄金三章有当场问题");
    expect(notes[1]).toContain("R4");
    expect(notes[1]).toContain("REJECT");
    expect(notes[1]).toContain("已修一轮");
    expect(notes[1]).toContain("终局资源提前透支");
  });
});
