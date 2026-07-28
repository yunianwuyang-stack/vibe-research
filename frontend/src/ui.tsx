/** Shared presentational primitives extracted from main.tsx (P9.2 strangler). */
import React, { useState } from "react";

/**
 * 核心概念解释提示。
 * 点击 ⓘ 图标展开/收起一段简短说明，帮助不熟悉学术科研流程的用户理解界面术语。
 */
export function ConceptTip({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="concept-tip">
      <button
        type="button"
        className="concept-tip-trigger"
        aria-expanded={open}
        aria-label={`查看「${title}」说明`}
        onClick={() => setOpen((v) => !v)}
      >
        ⓘ
      </button>
      {open && (
        <span className="concept-tip-popover" role="tooltip">
          <strong>{title}</strong>
          {children}
          <button
            type="button"
            className="concept-tip-close"
            aria-label="关闭说明"
            onClick={() => setOpen(false)}
          >
            ✕
          </button>
        </span>
      )}
    </span>
  );
}

export function Panel({
  title,
  detail,
  children,
}: {
  title: string;
  detail: string;
  children: React.ReactNode;
}) {
  return (
    <section className="panel">
      <header className="section-header">
        <p className="eyebrow">研究流程</p>
        <h1>{title}</h1>
        <p>{detail}</p>
      </header>
      {children}
    </section>
  );
}

export function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
      <b>尚无可展示数据</b>
      <p>{text}</p>
    </div>
  );
}

export function Field({
  label,
  value,
  set,
  placeholder,
  area,
}: {
  label: string;
  value: string;
  set: (value: string) => void;
  placeholder: string;
  area?: boolean;
}) {
  return (
    <label className={area ? "wide" : ""}>
      {label}
      {area ? (
        <textarea
          value={value}
          placeholder={placeholder}
          onChange={(e) => set(e.target.value)}
        />
      ) : (
        <input
          value={value}
          placeholder={placeholder}
          onChange={(e) => set(e.target.value)}
        />
      )}
    </label>
  );
}

export function Card({
  title,
  text,
  action,
  meta,
}: {
  title: string;
  text: string;
  action: () => void;
  meta?: string;
}) {
  return (
    <button className="card" onClick={action}>
      {meta && <small className="card-meta">{meta}</small>}
      <span>{title}</span>
      <p>{text}</p>
      <em>进入工作区 <span aria-hidden="true">→</span></em>
    </button>
  );
}

