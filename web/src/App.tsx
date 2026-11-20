import { lazy, Suspense, useEffect, useState } from "react";
import Employers from "./pages/Employers";
import Today from "./pages/Today";

// Charts and markdown are the heavy parts: load them only when their tab opens.
const Insights = lazy(() => import("./pages/Insights"));
const Ask = lazy(() => import("./pages/Ask"));

const TABS = [
  { id: "today", label: "Today", page: Today },
  { id: "employers", label: "Employers", page: Employers },
  { id: "insights", label: "Insights", page: Insights },
  { id: "ask", label: "Ask", page: Ask },
] as const;
type TabId = (typeof TABS)[number]["id"];

function fromHash(): TabId {
  const id = window.location.hash.replace("#", "");
  return (TABS.find((t) => t.id === id)?.id ?? "today") as TabId;
}

export default function App() {
  const [tab, setTab] = useState<TabId>(fromHash);
  useEffect(() => {
    const onHash = () => setTab(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const Page = TABS.find((t) => t.id === tab)!.page;

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <h1>Job Radar</h1>
          <p>
            New US jobs at companies that file H-1B wages with the Department of Labor, ranked by
            how well they fit my profile.
          </p>
        </div>
        <nav aria-label="Sections">
          {TABS.map((t) => (
            <a key={t.id} href={`#${t.id}`} aria-current={t.id === tab ? "page" : undefined}>
              {t.label}
            </a>
          ))}
        </nav>
      </header>
      <main>
        <Suspense fallback={<p className="status">Loading…</p>}>
          <Page />
        </Suspense>
      </main>
      <footer className="footer">
        <p>
          Data: public Greenhouse and Ashby job boards, refreshed daily, and Department of Labor
          LCA disclosure files. Read-only. Built by Ajinkya Desai.{" "}
          <a href="https://github.com/ajinkyadesai-git/job-radar">Source on GitHub</a>
        </p>
      </footer>
    </div>
  );
}
