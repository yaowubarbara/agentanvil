"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import Waterfall from "../../components/Waterfall";
import PlaybackControls from "../../components/PlaybackControls";

type Event = {
  kind: string;
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
  meta?: Record<string, unknown>;
  verify?: { correct: boolean; reward: number; parsed: unknown; gold: unknown; meta?: Record<string, unknown> };
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

export default function TraceDetail() {
  const params = useParams<{ id: string }>();
  const id = params?.id as string;
  const [mounted, setMounted] = useState(false);
  const [traj, setTraj] = useState<Trajectory | null>(null);
  const [step, setStep] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
    fetch("/api/traces")
      .then((r) => r.json())
      .then((d) => {
        const found = (d.trajectories || []).find(
          (t: Trajectory) => t.trajectory_id === id
        );
        if (!found) setErr("trajectory not found in traces.jsonl");
        else setTraj(found);
      })
      .catch((e) => setErr(String(e)));
  }, [id]);

  const durationMs = useMemo(() => {
    if (!traj) return 0;
    const end =
      traj.finished_at ?? (traj.events.length > 0 ? traj.events[traj.events.length - 1].ts : traj.started_at);
    return Math.round((end - traj.started_at) * 1000);
  }, [traj]);

  if (!mounted) {
    return (
      <main className="trace-page" suppressHydrationWarning>
        <div className="empty-chart">Loading trajectory…</div>
      </main>
    );
  }

  if (err) {
    return (
      <main className="trace-page">
        <div className="empty-chart">
          Error: {err} <Link href="/traces">← back</Link>
        </div>
      </main>
    );
  }
  if (!traj) return <main className="trace-page"><div className="empty-chart">Loading…</div></main>;

  const ok = traj.verify?.correct;

  return (
    <main className="trace-page">
      <div className="trace-head">
        <Link href="/traces" className="back">
          ← all traces
        </Link>
        <div className="trace-title">
          <div className="trace-task">{traj.task_id}</div>
          <div className="trace-sub">
            <span className="scaffold-pill">{traj.scaffold}</span>
            <span className="trace-meta-item">id {traj.trajectory_id.slice(0, 12)}</span>
            <span className="trace-meta-item">{traj.events.length} events</span>
            <span className="trace-meta-item">{durationMs} ms</span>
            {traj.verify && (
              <span className={`trace-verdict ${ok ? "ok" : "bad"}`}>
                {ok ? "✓" : "✗"} parsed=
                <b>{String(traj.verify.parsed)}</b>{" "}
                gold=<b>{String(traj.verify.gold)}</b>{" "}
                reward={traj.verify.reward}
              </span>
            )}
          </div>
        </div>
      </div>

      <section className="panel">
        <div className="panel-title">
          Waterfall
          <span className="panel-sub">event timing relative to rollout start</span>
        </div>
        <Waterfall
          events={traj.events}
          startedAt={traj.started_at}
          finishedAt={traj.finished_at}
          highlightStep={step}
          onSelect={setStep}
        />
      </section>

      <section className="panel">
        <div className="panel-title">
          Playback
          <span className="panel-sub">step through events</span>
        </div>
        <PlaybackControls
          totalSteps={traj.events.length}
          onStepChange={setStep}
          initialStep={0}
        />
        <div className="step-focus">
          <div className="step-focus-head">
            step {step + 1} / {traj.events.length} ·{" "}
            <span className="step-focus-kind">{traj.events[step]?.kind}</span>
          </div>
          <pre className="step-focus-body">
            {renderContent(traj.events[step]?.content)}
          </pre>
          {traj.events[step]?.meta && Object.keys(traj.events[step].meta!).length > 0 && (
            <details className="step-focus-meta">
              <summary>meta</summary>
              <pre>{JSON.stringify(traj.events[step].meta, null, 2)}</pre>
            </details>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="panel-title">
          All events
          <span className="panel-sub">click any row to focus waterfall above</span>
        </div>
        <div className="event-list">
          {traj.events.map((e, i) => (
            <div
              key={i}
              className={`event ${e.kind} ${step === e.step ? "focus" : ""}`}
              onClick={() => setStep(e.step)}
            >
              <div className="event-header">
                <span className="kind">{e.kind}</span>
                <span className="step">step {e.step} · {((e.ts - traj.started_at) * 1000).toFixed(0)}ms</span>
              </div>
              <pre className="content">{renderContent(e.content)}</pre>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
