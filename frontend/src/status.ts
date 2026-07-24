/** P9 unified workspace status vocabulary + repair actions. */
export type WorkspaceStatus =
  | "queued"
  | "running"
  | "produced"
  | "verifying"
  | "accepted"
  | "blocked"
  | "stale"
  | "failed";

export const WORKSPACE_STATUSES: readonly WorkspaceStatus[] = [
  "queued",
  "running",
  "produced",
  "verifying",
  "accepted",
  "blocked",
  "stale",
  "failed",
] as const;

/** Human label (zh) for status chips. */
export const STATUS_LABEL: Record<WorkspaceStatus, string> = {
  queued: "排队中",
  running: "执行中",
  produced: "已产出",
  verifying: "核验中",
  accepted: "已接受",
  blocked: "已阻断",
  stale: "已过期",
  failed: "失败",
};

/** Explicit repair / next action for every status (P9.3). */
export const STATUS_REPAIR: Record<WorkspaceStatus, string> = {
  queued: "等待依赖完成后启动",
  running: "查看当前运行日志",
  produced: "提交证据核验",
  verifying: "打开核验队列",
  accepted: "继续下一研究动作",
  blocked: "查看阻断原因并补齐依赖",
  stale: "重新运行受影响步骤",
  failed: "查看失败日志并重试",
};

/** Map heterogeneous backend statuses into the P9 vocabulary. */
export function normalizeWorkspaceStatus(raw?: string | null): WorkspaceStatus {
  const value = (raw || "").trim().toLowerCase();
  if (!value) return "queued";
  if (value === "queued" || value === "pending" || value === "waiting") return "queued";
  if (value === "running" || value === "in_progress" || value === "executing") return "running";
  if (value === "produced" || value === "completed" || value === "done" || value === "success") return "produced";
  if (value === "verifying" || value === "needs_review" || value === "ready_for_review" || value === "reviewing") return "verifying";
  if (value === "accepted" || value === "approved" || value === "verified" || value === "frozen") return "accepted";
  if (value === "blocked" || value === "needs_evidence" || value === "paused") return "blocked";
  if (value === "stale" || value === "superseded" || value === "outdated") return "stale";
  if (
    value === "failed" ||
    value === "error" ||
    value === "rejected" ||
    value === "cancelled" ||
    value === "interrupted" ||
    value === "falsified"
  ) {
    return "failed";
  }
  return "queued";
}

/** Legacy export kept for older imports; prefer WorkspaceStatus. */
export type Status = WorkspaceStatus;
export function nextAction(current: Status): string {
  return STATUS_REPAIR[current];
}
