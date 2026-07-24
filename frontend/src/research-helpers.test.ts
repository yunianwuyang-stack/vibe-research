import { describe, expect, it } from "vitest";
import {
  evidenceReview,
  errorText,
  inputStatusText,
  machineCitationLabel,
  researchStepLabel,
  statusText,
} from "./research-helpers";

describe("P9.2 research helpers", () => {
  it("maps workflow and evidence statuses", () => {
    expect(statusText("needs_evidence")).toBe("需要证据");
    expect(statusText("approved")).toBe("已验证");
    expect(statusText(undefined)).toBe("未知");
    expect(inputStatusText("uploaded")).toBe("已上传");
    expect(researchStepLabel("evidence")).toBe("证据核验");
    expect(researchStepLabel("nope")).toBe("nope");
  });

  it("labels machine citation verdicts", () => {
    expect(machineCitationLabel("PASS")).toBe("机器通过");
    expect(machineCitationLabel("fail")).toBe("机器失败");
    expect(machineCitationLabel("UNAVAILABLE")).toBe("机器不可用");
    expect(machineCitationLabel(null)).toBe("机器未检");
    expect(machineCitationLabel("WARN")).toBe("机器 WARN");
  });

  it("scores three-axis evidence review", () => {
    expect(
      evidenceReview({
        citation_status: "pending",
        claim_support_status: "pending",
        citation_machine_verdict: null,
      }),
    ).toMatchObject({ completed: 0, percent: 0, label: "待开始核验" });
    expect(
      evidenceReview({
        citation_status: "approved",
        claim_support_status: "approved",
        citation_machine_verdict: "PASS",
      }),
    ).toMatchObject({ completed: 3, percent: 100, label: "已核验" });
    const partial = evidenceReview({
      citation_status: "approved",
      claim_support_status: "pending",
      citation_machine_verdict: "FAIL",
    });
    expect(partial.completed).toBe(1);
    expect(partial.label).toBe("待完成 2 项");
  });

  it("normalizes unknown errors", () => {
    expect(errorText(new Error("boom"))).toBe("boom");
    expect(errorText("x")).toBe("请求未完成");
  });
});
