import type { Metadata } from "next";
import Nav from "./components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentAnvil — scaffold-agnostic agent harness",
  description: "Trajectory observability + evaluation for any agent scaffold",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <Nav />
        <div className="page-root">{children}</div>
      </body>
    </html>
  );
}
