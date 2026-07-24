import { describe, expect, it } from "vitest";
import { researchMapReadiness } from "./research-map";

const emptyNarrative = {
  question: "",
  tension: "",
  mechanism: "",
  hypotheses: [""],
  claims: [""],
  competing_explanations: [""],
  boundaries: [""],
  limitations: [""],
};

describe("P9.1 research map readiness", () => {
  it("blocks without project", () => {
    const r = researchMapReadiness({
      project: null,
      narrative: emptyNarrative,
      frozenCount: 0,
    });
    expect(r.status).toBe("blocked");
    expect(r.canSave).toBe(false);
    expect(r.blockers[0]).toMatch(/项目/);
  });

  it("allows save when project and frozen hypothesis exist", () => {
    const r = researchMapReadiness({
      project: {
        id: "p1",
        title: "T",
        research_question: "Q",
        inclusion_criteria: "I",
        status: "running",
        artifacts: [],
        evidence_cards: [],
        hypotheses: [],
        hypothesis_readiness: {} as never,
        events: [],
      },
      narrative: {
        ...emptyNarrative,
        tension: "t",
        mechanism: "m",
        claims: ["C1"],
        competing_explanations: ["alt"],
      },
      frozenCount: 1,
    });
    expect(r.canSave).toBe(true);
    expect(r.blockers).toEqual([]);
  });

  it("marks approved map as accepted", () => {
    const r = researchMapReadiness({
      project: {
        id: "p1",
        title: "T",
        research_question: "Q",
        inclusion_criteria: "I",
        status: "approved",
        artifacts: [],
        evidence_cards: [],
        hypotheses: [],
        hypothesis_readiness: {} as never,
        events: [],
      },
      narrative: {
        ...emptyNarrative,
        tension: "t",
        mechanism: "m",
        claims: ["C1"],
        competing_explanations: ["alt"],
        approved: true,
      },
      frozenCount: 1,
    });
    expect(r.status).toBe("accepted");
    expect(r.canApprove).toBe(false);
  });
});
