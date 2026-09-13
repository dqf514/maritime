import { Suspense } from "react";

export default function HelpLayout({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<div className="help-shell"><p style={{ padding: "2rem" }}>…</p></div>}>{children}</Suspense>;
}
