/** Shared presentational primitives extracted from main.tsx (P9.2 strangler). */
import React from "react";

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
        <h1>{title}</h1>
        {detail && <p>{detail}</p>}
      </header>
      {children}
    </section>
  );
}

export function Empty({ text }: { text: string }) {
  return (
    <div className="empty">
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

