import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AgentAnvil — trajectory replay",
  description: "Scaffold-agnostic Agent trajectory viewer",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
