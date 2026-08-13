export type ConceptJudgeVerdictView = {
  verdict: "PASS" | "REVISE" | "REJECT";
  after_round: string;
  reasons: string[];
  repair_attempted: boolean;
  repair_notes: string;
};

export type ConceptJudgeState = {
  after_r2: ConceptJudgeVerdictView | null;
  after_r4: ConceptJudgeVerdictView | null;
};

export function conceptJudgeNotes(state: ConceptJudgeState | null | undefined): string[] {
  if (!state) {
    return [];
  }
  const notes: string[] = [];
  for (const key of ["after_r2", "after_r4"] as const) {
    const verdict = state[key];
    if (!verdict) {
      continue;
    }
    const repaired = verdict.repair_attempted ? "（已修一轮）" : "";
    notes.push(
      `${verdict.after_round} Concept Judge ${verdict.verdict}${repaired}：${verdict.reasons.join("；")}`,
    );
  }
  return notes;
}
