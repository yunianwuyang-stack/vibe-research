/** Literature & evidence page extracted from main.tsx (P9.2 strangler). */
import React from "react";
import type { LiteratureRecord, Project } from "./api";
import { Panel, Empty } from "./ui";
import {
  evidenceReview,
  machineCitationLabel,
  statusText,
} from "./research-helpers";

export type EvidencePageProps = {
  busy: boolean;
  provider: string;
  question: string;
  records: LiteratureRecord[];
  evidenceNotice: string;
  project?: Project | null;
  savedRecordUrls: Set<string>;
  onProviderChange: (value: string) => void;
  onQuestionChange: (value: string) => void;
  onSearch: () => void;
  onSaveRecord: (record: LiteratureRecord) => void;
  onReviewCard: (cardId: string, decision: "approved" | "rejected") => void;
  onReviewSupport: (cardId: string, decision: "approved" | "rejected") => void;
};

export function evidenceLibrarySummary(input: {
  recordCount: number;
  cardCount: number;
  fullyVerified: number;
}): { status: "blocked" | "running" | "accepted"; label: string } {
  const { recordCount, cardCount, fullyVerified } = input;
  if (cardCount === 0) {
    return {
      status: recordCount ? "running" : "blocked",
      label: recordCount
        ? "检索已返回，待保存并核验证据卡"
        : "尚无证据；请检索并保存证据卡",
    };
  }
  if (fullyVerified >= cardCount && cardCount > 0) {
    return { status: "accepted", label: "全部证据卡已完成三维核验" };
  }
  return {
    status: "running",
    label: `已保存 ${cardCount} 张，完成核验 ${fullyVerified} 张`,
  };
}

export function EvidencePage({
  busy,
  provider,
  question,
  records,
  evidenceNotice,
  project,
  savedRecordUrls,
  onProviderChange,
  onQuestionChange,
  onSearch,
  onSaveRecord,
  onReviewCard,
  onReviewSupport,
}: EvidencePageProps) {
  return (
      <Panel
        title="文献与证据库"
        detail="检索结果只有保存为证据卡并经人工核对后才能进入写作。保存、引用核验与主张支持核验是三个独立状态。"
      >
        <div className="search">
          <select
            aria-label="文献数据源"
            value={provider}
            onChange={(e) => onProviderChange(e.target.value)}
          >
            {[
              "openalex",
              "crossref",
              "datacite",
              "arxiv",
              "semantic_scholar",
            ].map((v) => (
              <option value={v} key={v}>
                {v}
              </option>
            ))}
          </select>
          <input
            value={question}
            aria-label="检索词"
            placeholder="输入研究问题或关键词"
            onChange={(e) => onQuestionChange(e.target.value)}
          />
          <button disabled={busy || question.length < 3} onClick={onSearch}>
            检索
          </button>
        </div>
        {evidenceNotice && (
          <p className="evidence-notice" role="status" aria-live="polite">
            {evidenceNotice}
          </p>
        )}
        {records.length ? (
          <ol className="results search-results">
            {records.map((record, index) => {
              const saved = savedRecordUrls.has(record.url);
              return (
                <li
                  className={saved ? "saved-result" : ""}
                  key={`${record.url}-${index}`}
                >
                  <a href={record.url} target="_blank" rel="noreferrer">
                    {record.title}
                  </a>
                  <span>
                    {record.year || "未知年份"} ·{" "}
                    {saved ? "已保存，待核验" : statusText(record.status)} ·{" "}
                    {record.provenance}
                  </span>
                  <button
                    className={saved ? "quiet" : ""}
                    disabled={busy || !project || saved}
                    onClick={() => onSaveRecord(record)}
                  >
                    {saved ? "已保存，待核验" : "保存为证据卡"}
                  </button>
                </li>
              );
            })}
          </ol>
        ) : (
          <Empty text="尚无检索记录。输入至少三个字符后开始查询。" />
        )}
        <div className="saved-evidence-heading">
          <div>
            <h3>已保存证据卡</h3>
            <p>
              只有完成引用核验和主张支持核验
              后，项目才会离开“需要证据”状态。
            </p>
          </div>
          <span>{project?.evidence_cards?.length || 0} 张</span>
        </div>
        {project?.evidence_cards?.length ? (
          <ol className="results">
            {project.evidence_cards.map((card) => {
              const review = evidenceReview(card);
              return (
              <li className="evidence-card" key={card.id}>
                <div className="evidence-card-head">
                  <div>
                    <a href={card.canonical_url} target="_blank" rel="noreferrer">
                      {card.title}
                    </a>
                    <span>
                      {card.provenance.length} 条来源记录 · {review.label}
                    </span>
                  </div>
                  <strong className={`evidence-state state-${review.completed}`}>
                    {review.percent}%
                  </strong>
                </div>
                <div className="evidence-progress" aria-label={`核验进度 ${review.percent}%`}>
                  <span style={{ width: `${review.percent}%` }} />
                </div>
                <div className="evidence-checks">
                  <span
                    className={
                      (card.citation_machine_verdict || "").toUpperCase() ===
                      "PASS"
                        ? "done"
                        : (card.citation_machine_verdict || "").toUpperCase() ===
                            "FAIL"
                          ? "blocked"
                          : ""
                    }
                  >
                    <i aria-hidden="true">
                      {(card.citation_machine_verdict || "").toUpperCase() ===
                      "PASS"
                        ? "✓"
                        : (card.citation_machine_verdict || "").toUpperCase() ===
                            "FAIL"
                          ? "!"
                          : "0"}
                    </i>
                    机器引用 · {machineCitationLabel(card.citation_machine_verdict)}
                    {card.citation_machine_layer
                      ? ` · ${card.citation_machine_layer}`
                      : ""}
                  </span>
                  <span className={card.citation_status === "approved" ? "done" : ""}>
                    <i aria-hidden="true">{card.citation_status === "approved" ? "✓" : "1"}</i>
                    人工引用 · {statusText(card.citation_status)}
                  </span>
                  <span className={card.claim_support_status === "approved" ? "done" : ""}>
                    <i aria-hidden="true">{card.claim_support_status === "approved" ? "✓" : "2"}</i>
                    主张支持 · {statusText(card.claim_support_status)}
                  </span>
                </div>
                {(card.citation_machine_detail ||
                  card.citation_machine_artifact_path ||
                  card.citation_machine_checked_at) && (
                  <p className="evidence-machine-detail">
                    {card.citation_machine_detail || "机器核验已执行"}
                    {card.citation_machine_checked_at
                      ? ` · ${card.citation_machine_checked_at}`
                      : ""}
                    {card.citation_machine_artifact_path
                      ? ` · ${card.citation_machine_artifact_path}`
                      : ""}
                  </p>
                )}
                <div className="inline-actions">
                  <button
                    disabled={busy || card.citation_status === "approved"}
                    onClick={() => onReviewCard(card.id, "approved")}
                    title="批准前会真实执行机器存在性核验；FAIL 返回 409 并阻止人工批准"
                  >
                    批准引用
                  </button>
                  <button
                    disabled={
                      busy ||
                      card.citation_status !== "approved" ||
                      card.claim_support_status === "approved"
                    }
                    onClick={() => onReviewSupport(card.id, "approved")}
                  >
                    批准主张支持
                  </button>
                  <button
                    className="danger"
                    disabled={busy || card.citation_status === "rejected"}
                    onClick={() => onReviewCard(card.id, "rejected")}
                  >
                    驳回引用
                  </button>
                  <button
                    className="danger"
                    disabled={busy || card.citation_status !== "approved"}
                    onClick={() => onReviewSupport(card.id, "rejected")}
                  >
                    驳回主张支持
                  </button>
                </div>
              </li>
              );
            })}
          </ol>
        ) : (
          <Empty
            text={
              project
                ? "尚未保存证据卡。"
                : "请先创建研究合同，再保存检索结果。"
            }
          />
        )}
      </Panel>
  );
}
