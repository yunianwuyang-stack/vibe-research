/** Pure research UI helpers extracted from main.tsx (P9.2 strangler). */

export const inputStatusText = (value?: string) =>
  ({
    uploaded: "已上传",
    pending: "等待解析",
    running: "正在解析",
    completed: "解析完成",
    skipped: "原文件可用",
    failed: "解析失败",
  })[value || ""] || value || "未知";

export const statusText = (value?: string) =>
  ({
    pending: "等待开始",
    running: "执行中",
    paused: "已暂停",
    completed: "已完成",
    failed: "失败",
    approved: "已验证",
    needs_review: "待核验",
    needs_evidence: "需要证据",
    ready_for_review: "待审阅",
    rejected: "已驳回",
    blocked: "已阻塞",
    draft: "草拟中",
    frozen: "已冻结",
    falsified: "已证伪",
    superseded: "已被修订",
    stale: "已失效",
    interrupted: "已中断",
    cancelled: "已取消",
  })[value || ""] ||
  value ||
  "未知";

export const researchStepLabel = (name?: string | null) =>
  ({
    contract: "研究合同",
    question: "研究问题",
    hypothesis: "可证伪假设",
    evidence: "证据核验",
    experiment_run: "实验运行",
    result: "结果固化",
    claim: "主张绑定",
    adversarial_review: "对抗评审",
    approval: "人工批准",
    audit: "审计封存",
  })[name || ""] ||
  name ||
  "未知步骤";

export const machineCitationLabel = (verdict?: string | null) => {
  const value = (verdict || "").toUpperCase();
  if (value === "PASS") return "机器通过";
  if (value === "FAIL") return "机器失败";
  if (value === "UNAVAILABLE") return "机器不可用";
  if (!value) return "机器未检";
  return `机器 ${value}`;
};

export type EvidenceReviewCard = {
  citation_status?: string;
  claim_support_status?: string;
  citation_machine_verdict?: string | null;
};

export const evidenceReview = (card: EvidenceReviewCard) => {
  const citationApproved = card.citation_status === "approved";
  const claimApproved = card.claim_support_status === "approved";
  const machinePass =
    (card.citation_machine_verdict || "").toUpperCase() === "PASS";
  const completed =
    Number(citationApproved) + Number(claimApproved) + Number(machinePass);
  return {
    completed,
    percent: Math.round((completed / 3) * 100),
    label:
      completed === 3
        ? "已核验"
        : completed === 0
          ? "待开始核验"
          : `待完成 ${3 - completed} 项`,
  };
};

export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "请求未完成";
