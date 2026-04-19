"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import MetricCard from "./components/MetricCard";
import AccuracyBarChart from "./components/AccuracyBarChart";
import Heatmap from "./components/Heatmap";
import Sparkline from "./components/Sparkline";

type Event = { kind: string; step: number; ts: number; content: unknown };
type Trajectory = {
  trajectory_id: string;
  task_id: string;
  scaffold: string;
  started_at: number;
  finished_at: number | null;
  events: Event[];
  verify?: { correct: boolean; reward: number; parsed: unknown; gold: unknown };
};

function shortTime(ts: number) {
  if (!ts) return "";
  return new Date(ts * 1000).toISOString().slice(11, 19);
}

export default function Dashboard() {
  const [mounted, setMounted] = useState(false);
  const [trajs, setTrajs] = useState<Trajectory[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [apiSource, setApiSource] = useState<string | null>(null);

  useEffect(() => {
    setMounted(true);
    fetch("/api/traces")
      .then((r) => r.json())
      .then((d) => {
        setTrajs(d.trajectories || []);
        setApiSource(d.source || null);
        if (d.error) setErr(String(d.error));
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => {
    const byScaffold = new Map<string, { n: number; correct: number; rewards: number[] }>();
    const byTask = new Map<string, number>();
    const cells: { scaffold: string; task: string; correct: boolean | null }[] = [];
    let total = 0;
    let correct = 0;
    let totalEvents = 0;

    for (const t of trajs) {
      total += 1;
      totalEvents += t.events.length;
      const ok = !!t.verify?.correct;
      if (ok) correct += 1;
      const s = byScaffold.get(t.scaffold) || { n: 0, correct: 0, rewards: [] };
      s.n += 1;
      if (ok) s.correct += 1;
      s.rewards.push(t.verify?.reward ?? 0);
      byScaffold.set(t.scaffold, s);
      byTask.set(t.task_id, (byTask.get(t.task_id) || 0) + 1);
      cells.push({
        scaffold: t.scaffold,
        task: t.task_id,
        correct: t.verify ? !!t.verify.correct : null,
      });
    }
    const scaffolds = Array.from(byScaffold.entries()).map(([name, v]) => ({
      scaffold: name,
      n: v.n,
      correct: v.correct,
      rewards: v.rewards,
    }));
    return {
      total,
      correct,
      accuracy: total ? correct / total : 0,
      totalEvents,
      avgEvents: total ? totalEvents / total : 0,
      scaffolds,
      taskCount: byTask.size,
      cells,
    };
  }, [trajs]);

  const recent = useMemo(() => trajs.slice(0, 6), [trajs]);

  if (!mounted) {
    return (
      <main className="dashboard" suppressHydrationWarning>
        <section className="hero">
          <h1 className="hero-title">
            <span className="hero-gradient">Agent evaluation</span> at a glance
          </h1>
          <p className="hero-sub">initializing…</p>
        </section>
      </main>
    );
  }

  return (
    <main className="dashboard">
      {/* Debug panel — always visible so you can see fetch state at a glance. */}
      <div className="debug-panel">
        <div><b>DEBUG</b></div>
        <div>mounted: <code>{String(mounted)}</code></div>
        <div>loading: <code>{String(loading)}</code></div>
        <div>trajs.length: <code>{trajs.length}</code></div>
        <div>err: <code>{err ?? "(none)"}</code></div>
        <div>source: <code>{apiSource ?? "(not yet)"}</code></div>
        <div>first trajectory_id: <code>{trajs[0]?.trajectory_id?.slice(0, 8) ?? "(none)"}</code></div>
        <button className="refetch-btn" onClick={() => {
          setLoading(true);
          fetch("/api/traces")
            .then((r) => r.json())
            .then((d) => { setTrajs(d.trajectories || []); setApiSource(d.source || null); })
            .catch((e) => setErr(String(e)))
            .finally(() => setLoading(false));
        }}>↻ Manual refetch</button>
      </div>
      {err && (
        <div className="banner err">
          Error loading traces: {err}
          {apiSource && <div className="banner-sub">source: {apiSource}</div>}
        </div>
      )}
      {loading && !err && (
        <div className="banner info">Loading trajectories…</div>
      )}
      {!loading && !err && trajs.length === 0 && (
        <div className="banner warn">
          <strong>No trajectories yet.</strong> Run{" "}
          <code>python3 examples/seed_demo_traces.py</code> or{" "}
          <code>aa eval run gsm8k-mini</code> to populate{" "}
          <code>{apiSource || "traces/traces.jsonl"}</code>.
        </div>
      )}

      <section className="hero">
        <h1 className="hero-title">
          <span className="hero-gradient">Agent evaluation</span> at a glance
        </h1>
        <p className="hero-sub">
          Scaffold-agnostic trajectory observability for {stats.taskCount || 0} tasks across{" "}
          {stats.scaffolds.length} scaffold{stats.scaffolds.length === 1 ? "" : "s"}.
          {apiSource && (
            <span className="hero-source"> · source: <code>{apiSource}</code></span>
          )}
        </p>
      </section>

      <section className="metrics-row">
        <MetricCard
          label="Trajectories"
          value={stats.total}
          sub={stats.totalEvents.toLocaleString() + " total events"}
          accent="#7cc4ff"
        />
        <MetricCard
          label="Accuracy"
          value={(stats.accuracy * 100).toFixed(1) + "%"}
          sub={stats.correct + "/" + stats.total + " correct"}
          accent="#6fcf97"
        />
        <MetricCard
          label="Scaffolds"
          value={stats.scaffolds.length}
          sub={stats.taskCount + " unique tasks"}
          accent="#a78bfa"
        />
        <MetricCard
          label="Avg events / run"
          value={stats.avgEvents.toFixed(1)}
          sub="higher = more tool use"
          accent="#f0b54d"
        />
      </section>

      <section className="panels">
        <div className="panel">
          <div className="panel-title">
            Accuracy by scaffold
            <span className="panel-sub">horizontal bars; animated on load</span>
          </div>
          <AccuracyBarChart data={stats.scaffolds.map(({ scaffold, n, correct }) => ({ scaffold, n, correct }))} />
        </div>

        <div className="panel">
          <div className="panel-title">
            Recent activity
            <span className="panel-sub">6 most recent trajectories</span>
          </div>
          <div className="recent-list">
            {recent.length === 0 && (
              <div className="empty-chart">
                No traces yet. Run{" "}
                <code>python examples/seed_demo_traces.py</code> or{" "}
                <code>aa eval run gsm8k-mini</code>.
              </div>
            )}
            {recent.map((t) => {
              const ok = t.verify?.correct;
              return (
                <Link
                  key={t.trajectory_id}
                  href={`/trace/${t.trajectory_id}`}
                  className="recent-row"
                >
                  <div className="recent-main">
                    <div className="recent-task">{t.task_id}</div>
                    <div className="recent-scaffold">{t.scaffold}</div>
                  </div>
                  <Sparkline
                    values={t.events.map((e) =>
                      e.kind === "reward" ? 1 : e.kind === "tool_call" ? 0.6 : 0.3
                    )}
                    color={ok ? "#6fcf97" : "#eb5757"}
                  />
                  <div className={`recent-verdict ${ok ? "ok" : "bad"}`}>
                    {ok ? "✓" : "✗"}
                  </div>
                  <div className="recent-meta">
                    {t.events.length}ev · {shortTime(t.started_at)}
                  </div>
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      <section className="panel wide">
        <div className="panel-title">
          Scaffold × Task heatmap
          <span className="panel-sub">green=correct, red=wrong, gray=not run</span>
        </div>
        <Heatmap cells={stats.cells} />
      </section>
    </main>
  );
}
