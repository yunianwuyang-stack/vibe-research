/** Date/time formatting utilities shared across pages. */

/** Format an ISO timestamp for display (e.g. "2026-07-27 15:21"). Falls back to the raw string if the date is invalid. */
export const fmtTime = (iso: string | undefined | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};
