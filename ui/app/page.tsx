"use client";

import { useEffect, useState } from "react";

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
  };
};

function renderContent(c: unknown): string {
  if (typeof c === "string") return c;
  try {
    return JSON.stringify(c, null, 2);
  } catch {
    return String(c);
  }
}

function shortTime(ts: number) {
  if (!ts) return "";
  return new Date(ts * 1000).toISOString().slice(11, 19);
}

export default function Home() {
  const [trajs, setTrajs] = useState<Trajectory[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/traces")
      .then((r) => r.json())
      .then((data) => {
        setTrajs(data.trajectories || []);
        if (data.trajectories?.length) {
          setSelected(data.trajectories[0].trajectory_id);
        }
      })
      .catch((e) => setError(String(e)));
  }, []);

  const current = trajs.find((t) => t.trajectory_id === selected);

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>AgentAnvil · traces</h1>
        {error && <div className="empty">Error: {error}</div>}
        {!error && trajs.length === 0 && (
          <div className="empty">
            No traces yet. Run <code>examples/run_jordan_count.py</code>.
          </div>
        )}
        {trajs.map((t) => {
          const ok = t.verify?.correct;
          return (
            <div
              key={t.trajectory_id}
              className={`item ${t.trajectory_id === selected ? "active" : ""}`}
              onClick={() => setSelected(t.trajectory_id)}
            >
              <div>{t.task_id}</div>
              <div className="meta">
                {t.scaffold}
                {t.verify && (
                  <>
                    {" · "}
                    <span className={ok ? "reward-ok" : "reward-bad"}>
                      {ok ? "✓" : "✗"} r={t.verify.reward}
                    </span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </aside>
      <main className="main">
        {!current ? (
          <div className="empty">Select a trajectory from the sidebar.</div>
        ) : (
          <>
            <div className="header">
              <h2>
                {current.task_id} · <span style={{ color: "#a78bfa" }}>{current.scaffold}</span>
              </h2>
              <div className="sub">
                trajectory_id: {current.trajectory_id} · started {shortTime(current.started_at)}
                {current.verify && (
                  <>
                    {" · "}
                    <strong>
                      parsed={String(current.verify.parsed)} gold={String(current.verify.gold)}{" "}
                      {current.verify.correct ? "✓" : "✗"}
                    </strong>
                  </>
                )}
              </div>
            </div>
            {current.events.map((e, i) => (
              <div key={i} className={`event ${e.kind}`}>
                <div className="step">step {e.step} · {shortTime(e.ts)}</div>
                <div className="kind">{e.kind}</div>
                <pre className="content">{renderContent(e.content)}</pre>
              </div>
            ))}
          </>
        )}
      </main>
    </div>
  );
}
