import React from "react";
import {
  type AdversarialReview,
  type AssuranceEnvelope,
  type InnovationCheck,
  type Project,
} from "../api";
import { Panel, Empty } from "../ui";
import { fmtTime } from "../lib/format";
import { ProjectCard } from "./run-center";

function InnovationCheckPanel({
  busy,
  innovation,
  overrideReason,
  onOverrideReason,
  onReload,
  onRun,
}: {
  busy: boolean;
  innovation?: InnovationCheck;
  overrideReason: string;
  onOverrideReason: (value: string) => void;
  onReload: () => Promise<void>;
  onRun: () => Promise<void>;
}) {
  const gatePassed = Boolean(innovation?.gate?.passed);
  return (
    <section className="assurance-panel innovation-panel" aria-label="创新性核验">
      <div className="section-command">
        <div>
          <p className="eyebrow">Novelty / Innovation</p>
          <h3>创新性核验门禁</h3>
        </div>
        <div className="inline-actions">
          <span className={`assurance-status ${gatePassed ? "pass" : "blocked"}`}>
            {innovation?.status === "missing" || !innovation ? "未运行" : gatePassed ? "通过" : "阻断"}
          </span>
          <button className="icon-button quiet" type="button" title="刷新创新性核验"
            aria-label="刷新创新性核验" disabled={busy} onClick={onReload}>
            ↻
          </button>
        </div>
      </div>
      <p className="muted">
        对当前冻结假设做确定性重叠评分；LOW 新颖性必须填写研究者 override 理由，报告以 SHA256 落盘。
      </p>
      <label className="field">
        <span>LOW 新颖性 override 理由（可选）</span>
        <textarea value={overrideReason} onChange={(e) => onOverrideReason(e.target.value)}
          placeholder="说明与最接近既有工作的差异，例如方法机制、边界条件或评价协议。" rows={3} />
      </label>
      <div className="actions">
        <button disabled={busy} onClick={onRun}>运行创新性核验</button>
      </div>
      {innovation && innovation.status !== "missing" ? (
        <>
          <div className="assurance-summary">
            <div><span>主张数</span><b>{innovation.gate?.total_claims ?? innovation.claims?.length ?? 0}</b></div>
            <div>
              <span>LOW 未覆盖</span>
              <b>{(innovation.gate?.low_novelty_claim_ids || []).join(", ") || "无"}</b>
            </div>
            <div>
              <span>报告</span>
              <b>{innovation.artifact ? `${innovation.artifact.sha256.slice(0, 12)}…` : "无"}</b>
            </div>
          </div>
          {innovation.claims?.length ? (
            <ul className="review-findings">
              {innovation.claims.map((claim) => (
                <li key={claim.id}><b>{claim.id}</b><span>{claim.text}{claim.source ? ` · ${claim.source}` : ""}</span></li>
              ))}
            </ul>
          ) : null}
          {innovation.closest_prior_art?.length ? (
            <details>
              <summary>最近既有工作</summary>
              <ul className="review-findings">
                {innovation.closest_prior_art.map((item, index) => (
                  <li key={`${item.id || "prior"}-${index}`}>
                    <b>{item.claim_id || item.id || "prior"}</b>
                    <span>
                      {item.title || "未命名"}
                      {typeof item.overlap === "number" ? ` · overlap ${item.overlap}` : ""}
                      {item.url ? ` · ${item.url}` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          {innovation.findings?.length ? (
            <ul className="review-findings">
              {innovation.findings
                .filter((f) => f.code !== "claim_scored")
                .map((f, i) => (
                  <li key={`${f.code}-${i}`}>
                    <b className={`severity ${f.severity}`}>{f.severity}</b>
                    <span>{f.code}: {f.message}</span>
                  </li>
                ))}
            </ul>
          ) : null}
        </>
      ) : (
        <Empty text="尚未运行创新性核验。先冻结假设后点击上方按钮。" />
      )}
    </section>
  );
}

function AssurancePanel({
  busy,
  assurance,
  onReload,
}: {
  busy: boolean;
  assurance?: AssuranceEnvelope;
  onReload: () => Promise<void>;
}) {
  if (!assurance) {
    return (
      <section className="assurance-panel">
        <div className="section-command">
          <div>
            <p className="eyebrow">质量封装</p>
            <h3>独立提交门禁</h3>
          </div>
          <button className="icon-button quiet" type="button" title="刷新质量封装"
            aria-label="刷新质量封装" disabled={busy} onClick={onReload}>
            ↻
          </button>
        </div>
        <Empty text="尚未生成质量封装。运行一次独立审计后刷新。" />
      </section>
    );
  }
  const statusLabel =
    assurance.status === "PASS" ? "可提交" : assurance.status === "WARN" ? "需复核" : "已阻断";
  return (
    <section className="assurance-panel">
      <div className="section-command">
        <div>
          <p className="eyebrow">质量封装 · {assurance.verifier_version}</p>
          <h3>独立提交门禁</h3>
        </div>
        <div className="inline-actions">
          <span className={`assurance-status ${assurance.status.toLowerCase()}`}>{statusLabel}</span>
          <button className="icon-button quiet" type="button" title="刷新质量封装"
            aria-label="刷新质量封装" disabled={busy} onClick={onReload}>
            ↻
          </button>
        </div>
      </div>
      <div className="assurance-summary">
        <div><span>提交就绪</span><b>{assurance.submission_ready ? "是" : "否"}</b></div>
        <div><span>独立于生成器</span><b>{assurance.independent_from_generator ? "是" : "否"}</b></div>
        <div>
          <span>门禁</span>
          <b>{assurance.gates.filter((g) => g.status === "PASS").length}/{assurance.gates.length} 通过</b>
        </div>
      </div>
      <div className="assurance-gates">
        {assurance.gates.map((gate) => (
          <article key={gate.id} className={`assurance-gate ${gate.status.toLowerCase()}`}>
            <div><b>{gate.label}</b><span>{gate.status}</span></div>
            {gate.findings.length > 0 && (
              <small>{gate.findings.map((f) => `${f.code}: ${f.message}`).join("；")}</small>
            )}
          </article>
        ))}
      </div>
      <div className="assurance-meta">
        <span>项目快照 <code>{assurance.input_hashes.project_snapshot_sha256.slice(0, 16)}</code></span>
        <span>审稿输入 <code>{assurance.input_hashes.latest_review_inputs_sha256?.slice(0, 16) || "无"}</code></span>
        <span>报告 <code>{assurance.input_hashes.review_report_sha256?.slice(0, 16) || "无"}</code></span>
      </div>
      {assurance.findings.length > 0 && (
        <ul className="assurance-findings">
          {assurance.findings.map((f, i) => (
            <li key={`${f.code}-${i}`}>
              <b className={`severity ${f.severity}`}>{f.severity}</b>
              <span>{f.code}: {f.message}</span>
            </li>
          ))}
        </ul>
      )}
      {assurance.repair_actions.length > 0 && (
        <details className="assurance-repairs">
          <summary>修复动作（{assurance.repair_actions.length}）</summary>
          <ul>
            {assurance.repair_actions.map((r) => (
              <li key={`${r.finding_code}-${r.action}`}><b>{r.finding_code}</b><span>{r.action}</span></li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function AuditReviewPage({
  busy,
  project,
  reviews,
  assurance,
  innovation,
  overrideReason,
  onOverrideReason,
  onApprove,
  onReload,
  onReloadAssurance,
  onReloadInnovation,
  onRun,
  onRunInnovation,
  onSettings,
}: {
  busy: boolean;
  project?: Project;
  reviews: AdversarialReview[];
  assurance?: AssuranceEnvelope;
  innovation?: InnovationCheck;
  overrideReason: string;
  onOverrideReason: (value: string) => void;
  onApprove: () => Promise<void>;
  onReload: () => Promise<void>;
  onReloadAssurance: () => Promise<void>;
  onReloadInnovation: () => Promise<void>;
  onRun: (mode: "deterministic" | "model") => Promise<void>;
  onRunInnovation: () => Promise<void>;
  onSettings: () => void;
}) {
  return (
    <Panel title="审批与审计" detail="">
      {project ? (
        <>
          <ProjectCard project={project} />
          <AssurancePanel busy={busy} assurance={assurance} onReload={onReloadAssurance} />
          <InnovationCheckPanel
            busy={busy}
            innovation={innovation}
            overrideReason={overrideReason}
            onOverrideReason={onOverrideReason}
            onReload={onReloadInnovation}
            onRun={onRunInnovation}
          />
          <section className="audit-review-section">
            <div className="section-command">
              <h3>独立对抗审稿</h3>
              <button className="icon-button quiet" type="button" title="刷新审稿历史"
                aria-label="刷新审稿历史" disabled={busy} onClick={onReload}>
                ↻
              </button>
            </div>
            <div className="actions">
              <button disabled={busy} onClick={() => onRun("deterministic")}>运行确定性审计</button>
              <button className="quiet" disabled={busy} onClick={() => onRun("model")}>运行模型独立审稿</button>
              <button className="quiet" disabled={busy} onClick={onApprove}>批准研究合同</button>
              <button className="quiet" onClick={onSettings}>查看环境诊断</button>
            </div>
            {reviews.length ? (
              <ol className="review-list">
                {reviews.map((review) => (
                  <li key={review.id}>
                    <header>
                      <div>
                        <b>{review.mode === "model" ? "模型独立审稿" : "确定性对抗审计"}</b>
                        <span>{fmtTime(review.created_at)}</span>
                      </div>
                      <span className={`review-verdict ${review.verdict}`}>
                        {review.status === "completed" ? review.verdict : review.status}
                      </span>
                    </header>
                    <div className="review-hashes">
                      <code>input {review.inputs_sha256.slice(0, 16)}</code>
                      {review.report_sha256 && <code>report {review.report_sha256.slice(0, 16)}</code>}
                    </div>
                    {review.failure_reason && <p className="review-failure">{review.failure_reason}</p>}
                    {review.findings.length ? (
                      <ul className="review-findings">
                        {review.findings.map((f, i) => (
                          <li key={`${f.code}-${i}`}>
                            <b className={`severity ${f.severity}`}>{f.severity}</b>
                            <span>{f.code}: {f.message}{f.locator ? ` (${f.locator})` : ""}</span>
                          </li>
                        ))}
                      </ul>
                    ) : review.status === "completed" ? (
                      <p className="review-clear">未发现阻断性问题。</p>
                    ) : null}
                    {review.review_text && (
                      <details>
                        <summary>审稿原文</summary>
                        <pre className="json-card">{review.review_text}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <Empty text="尚无独立审稿记录。" />
            )}
          </section>
        </>
      ) : (
        <Empty text="建立研究合同后可运行独立对抗审稿。" />
      )}
    </Panel>
  );
}
