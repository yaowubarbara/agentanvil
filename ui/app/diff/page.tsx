"use client";

import { Fragment, Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

type EventKind =
  | "observation"
  | "thought"
  | "tool_call"
  | "tool_result"
  | "final_answer"
  | "reward"
  | "error";

type Event = {
  kind: EventKind;
  content: unknown;
  step: number;
  ts: number;
  meta?: Record<string, unknown>;
};

type Trajectory = {
  trajectory_id: string;
  task_id: string;
  scaffold: string;
  started_at: number;
  finished_at: number | null;
  events: Event[];
  verify?: {
    correct: boolean;
    reward: number;
    parsed: unknown;
    gold: unknown;
    meta?: Record<string, unknown>;
  };
};

function renderContent(c: unknown): string {
  if (c === null || c === undefined) return "";
  if (typeof c === "string") return c;
  try {
    return JSON.stringify(c, null, 2);
  } catch {
    return String(c);
  }
}

function SideHeader({ traj, side }: { traj: Trajectory; side: "left" | "right" }) {
  const ok = traj.verify?.correct;
  const dir = traj.verify?.meta?.direction as string | undefined;
  return (
    <div className={`side-header ${side}`}>
      <div className="scaffold">{traj.scaffold}</div>
      <div className="verdict">
        parsed={String(traj.verify?.parsed ?? "—")} · gold=
        {String(traj.verify?.gold ?? "—")}{" "}
        <span className={ok ? "ok" : "bad"}>{ok ? "✓ correct" : `✗ ${dir || "wrong"}`}</span>
      </div>
      <div className="meta">
        {traj.events.length} events · id {traj.trajectory_id.slice(0, 8)}
      </div>
    </div>
  );
}

function EventCell({ e }: { e: Event | null }) {
  if (!e) return <div className="cell empty">—</div>;
  return (
    <div className={`cell event ${e.kind}`}>
      <div className="kind-row">
        <span className="kind">{e.kind}</span>
        <span className="step">step {e.step}</span>
      </div>
      <pre className="content">{renderContent(e.content)}</pre>
    </div>
  );
}

function DiffPageInner() {
  const params = useSearchParams();
  const a = params.get("a");
  const b = params.get("b");
  const [trajs, setTrajs] = useState<Trajectory[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/traces")
      .then((r) => r.json())
      .then((d) => setTrajs(d.trajectories || []))
      .catch((e) => setError(String(e)));
  }, []);

  const left = trajs.find((t) => t.trajectory_id === a);
  const right = trajs.find((t) => t.trajectory_id === b);

  const rows = useMemo(() => {
    if (!left || !right) return [];
    const n = Math.max(left.events.length, right.events.length);
    const out: {
      step: number;
      l: Event | null;
      r: Event | null;
      diverges: boolean;
    }[] = [];
    for (let i = 0; i < n; i++) {
      const l = left.events[i] ?? null;
      const r = right.events[i] ?? null;
      const diverges = !!l && !!r && l.kind !== r.kind;
      out.push({ step: i, l, r, diverges });
    }
    return out;
  }, [left, right]);

  if (error) return <div className="empty">Error: {error}</div>;
  if (!a || !b) {
    return (
      <div className="diff-empty">
        <div className="diff-empty-icon">⇔</div>
        <h2 className="diff-empty-title">Pick two trajectories to compare</h2>
        <p className="diff-empty-sub">
          The diff view shows two runs side-by-side with divergent steps
          highlighted. You need to choose which two to compare first.
        </p>
        <div className="diff-empty-steps">
          <div className="diff-empty-step">
            <span className="step-num">1</span>
            <span>Open the <a href="/traces">Traces</a> list</span>
          </div>
          <div className="diff-empty-step">
            <span className="step-num">2</span>
            <span>Click the <code>pick</code> button on any two rows (they flip to A / B)</span>
          </div>
          <div className="diff-empty-step">
            <span className="step-num">3</span>
            <span>Click <code>Compare →</code> to land back here with data</span>
          </div>
        </div>
        <div className="diff-empty-actions">
          <a href="/traces" className="cta-btn">Go to Traces →</a>
          <a href="/" className="cta-btn secondary">← Dashboard</a>
        </div>
      </div>
    );
  }
  if (!left || !right) {
    if (trajs.length === 0) return <div className="empty">Loading traces…</div>;
    return (
      <div className="empty">
        One or both trajectories not found in traces.jsonl.
        <br />
        Requested: a=<code>{a}</code>, b=<code>{b}</code>
        <br />
        <a href="/">← back</a>
      </div>
    );
  }

  const sameTask = left.task_id === right.task_id;

  return (
    <div className="diff">
      <div className="diff-top">
        <a href="/" className="back">← back</a>
        <div className="diff-title">
          {sameTask ? (
            <>
              <strong>{left.task_id}</strong> ·{" "}
              <span className="scaffold-a">{left.scaffold}</span>
              {" vs "}
              <span className="scaffold-b">{right.scaffold}</span>
            </>
          ) : (
            <span className="warn">
              ⚠ Comparing across DIFFERENT task_ids — {left.task_id} vs {right.task_id}
            </span>
          )}
        </div>
      </div>
      <div className="diff-grid">
        <SideHeader traj={left} side="left" />
        <SideHeader traj={right} side="right" />
        {rows.map((row) => (
          <Fragment key={row.step}>
            <div className={row.diverges ? "row-mark diverge" : "row-mark"}>
              {row.diverges ? "◆ diverge" : ""}
            </div>
            <div className={`cell-wrap left ${row.diverges ? "diverges" : ""}`}>
              <EventCell e={row.l} />
            </div>
            <div className={`cell-wrap right ${row.diverges ? "diverges" : ""}`}>
              <EventCell e={row.r} />
            </div>
          </Fragment>
        ))}
      </div>
    </div>
  );
}

export default function DiffPage() {
  return (
    <Suspense fallback={<div className="empty">Loading…</div>}>
      <DiffPageInner />
    </Suspense>
  );
}
