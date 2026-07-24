import { describe, expect, it } from "vitest";
import { evidenceLibrarySummary } from "./evidence-page";
import { evidenceReview } from "./research-helpers";

describe("P9.2 evidence page summary", () => {
  it("blocks when empty", () => {
    const s = evidenceLibrarySummary({
      recordCount: 0,
      cardCount: 0,
      fullyVerified: 0,
    });
    expect(s.status).toBe("blocked");
    expect(s.label).toMatch(/尚无证据/);
  });

  it("runs after search without cards", () => {
    const s = evidenceLibrarySummary({
      recordCount: 3,
      cardCount: 0,
      fullyVerified: 0,
    });
    expect(s.status).toBe("running");
    expect(s.label).toMatch(/待保存/);
  });

  it("accepts only when every card is fully verified", () => {
    const card = {
      citation_status: "approved",
      claim_support_status: "approved",
      citation_machine_verdict: "PASS",
    };
    expect(evidenceReview(card).completed).toBe(3);
    const s = evidenceLibrarySummary({
      recordCount: 2,
      cardCount: 2,
      fullyVerified: 2,
    });
    expect(s.status).toBe("accepted");
  });

  it("tracks partial verification", () => {
    const s = evidenceLibrarySummary({
      recordCount: 1,
      cardCount: 3,
      fullyVerified: 1,
    });
    expect(s.status).toBe("running");
    expect(s.label).toContain("3");
    expect(s.label).toContain("1");
  });
});
