import { type ComponentType, lazy, Suspense, useEffect, useState } from "react";
import { Feedback } from "./Feedback";
import { clearOwnerKey, currentOwnerKey } from "./owner";
import Employers from "./pages/Employers";
import Today from "./pages/Today";
import Unlock from "./pages/Unlock";
import { trackTab, trackVisit } from "./track";

// Charts and markdown are the heavy parts: load them only when their tab opens.
const Insights = lazy(() => import("./pages/Insights"));
const Ask = lazy(() => import("./pages/Ask"));
const Usage = lazy(() => import("./pages/Usage"));

type Page = ComponentType<{ owner: boolean; onLocked?: () => void }>;

const TABS: readonly { id: string; label: string; page: Page }[] = [
  { id: "today", label: "Today", page: Today },
  { id: "employers", label: "Employers", page: Employers },
  { id: "insights", label: "Insights", page: Insights },
  { id: "ask", label: "Ask", page: Ask },
];
const USAGE_TAB = { id: "usage", label: "Usage", page: Usage as Page };

/** "me" is the owner's unlock page: reachable by its address only, not in the tabs. */
function fromHash(): string {
  const id = window.location.hash.replace("#", "");
  if (id === "me" || id === "usage") return id;
  return TABS.find((t) => t.id === id)?.id ?? "today";
}

export default function App() {
  const [tab, setTab] = useState<string>(fromHash);
  const [owner, setOwner] = useState<boolean>(() => currentOwnerKey() !== null);
  useEffect(() => trackVisit(), []);
  useEffect(() => trackTab(tab), [tab]);
  useEffect(() => {
    const onHash = () => setTab(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const tabs = owner ? [...TABS, USAGE_TAB] : TABS;
  const Page = tabs.find((t) => t.id === tab)?.page ?? Today;

  return (
    <div className="shell">
      <header className="masthead">
        <div className="brand">
          <h1>Job Radar</h1>
          <p>
            {owner
              ? "New US jobs at companies that file H-1B wages with the Department of Labor, ranked by how well they fit my profile."
              : "New US tech jobs at companies that file H-1B wages with the Department of Labor. Match your resume to fresh listings, see who sponsors and what they pay, and ask the data."}
          </p>
        </div>
        <nav aria-label="Sections">
          {tabs.map((t) => (
            <a key={t.id} href={`#${t.id}`} aria-current={t.id === tab ? "page" : undefined}>
              {t.label}
            </a>
          ))}
        </nav>
      </header>
      <main>
        <Suspense fallback={<p className="status">Loading…</p>}>
          {tab === "me" ? (
            <Unlock
              onUnlocked={() => {
                setOwner(true);
                window.location.hash = "#today";
              }}
            />
          ) : (
            <Page owner={owner} onLocked={() => setOwner(false)} />
          )}
        </Suspense>
      </main>
      <footer className="footer">
        <p>
          Data: public Greenhouse and Ashby job boards, refreshed daily, and Department of Labor
          LCA disclosure files. Read-only. Built by Ajinkya Desai.{" "}
          <a href="https://github.com/ajinkyadesai-git/job-radar">Source on GitHub</a>
        </p>
        <p>
          We count visits and which features are used, per day, with no personal data.{" "}
          <Feedback page={tab} />
          {owner && (
            <>
              {" "}
              <button
                type="button"
                className="link"
                onClick={() => {
                  clearOwnerKey();
                  setOwner(false);
                }}
              >
                Lock
              </button>
            </>
          )}
        </p>
      </footer>
    </div>
  );
}
