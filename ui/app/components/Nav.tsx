"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Dashboard", accent: "#7cc4ff" },
  { href: "/traces", label: "Traces", accent: "#a78bfa" },
  { href: "/diff", label: "Diff", accent: "#f0b54d" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="top-nav">
      <div className="brand">
        <span className="logo-dot" />
        <span className="brand-text">
          AgentAnvil <span className="brand-suffix">/ v0.0.2</span>
        </span>
      </div>
      <div className="tabs">
        {TABS.map((t) => {
          const active =
            t.href === "/" ? pathname === "/" : pathname.startsWith(t.href);
          return (
            <Link
              key={t.href}
              href={t.href}
              className={`tab ${active ? "active" : ""}`}
              style={{ ["--tab-accent" as string]: t.accent }}
            >
              {t.label}
            </Link>
          );
        })}
      </div>
      <div className="nav-meta">
        <span className="proto-pill">protocol v0.1</span>
      </div>
    </nav>
  );
}
