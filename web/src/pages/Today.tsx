import { useState } from "react";
import { api } from "../api";
import { payRange, plural, shortDay } from "../format";
import { Status } from "../Status";
import { useLoad } from "../useLoad";
import { FitMeter } from "./FitMeter";

const FAMILIES = [
  "Data / BI / AI",
  "Software",
  "Integration / solutions",
  "Business systems / ERP",
  "Technical program / product",
];

export default function Today() {
  const [reach, setReach] = useState("");
  const [family, setFamily] = useState("");
  const { data, error, loading } = useLoad(
    () => api.today({ reach: reach || undefined, role_family: family || undefined, limit: 50 }),
    [reach, family],
  );
  const jobs = data?.jobs ?? [];
  const sponsors = new Set(jobs.map((j) => j.company_name)).size;

  return (
    <section aria-labelledby="today-title">
      <h2 id="today-title" className="lede">
        {data
          ? `The ${plural(jobs.length, "best-fitting new job")} at ${plural(sponsors, "company", "companies")} that sponsor H-1B visas.`
          : "New jobs at companies that sponsor H-1B visas, best fit first."}
      </h2>
      <p className="sub">
        At my level: up to 5 years of experience asked. Fit comes from a model trained on 200 jobs
        I labeled; reach compares the years a posting asks for with my 3.
      </p>

      <div className="filters" role="group" aria-label="Filter jobs">
        <label>
          Reach
          <select value={reach} onChange={(e) => setReach(e.target.value)}>
            <option value="">Any</option>
            <option>Within reach</option>
            <option>Stretch</option>
          </select>
        </label>
        <label>
          Role family
          <select value={family} onChange={(e) => setFamily(e.target.value)}>
            <option value="">Any</option>
            {FAMILIES.map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
        </label>
      </div>

      <Status loading={loading} error={error} what="today's jobs" />
      {data && jobs.length === 0 && (
        <p className="status">No jobs match these filters. Set both to Any to see the full list.</p>
      )}

      {jobs.length > 0 && (
        <ol className="jobs">
          {jobs.map((j) => (
            <li key={j.posting_key} className="job">
              <div className="job-main">
                <a className="job-title" href={j.url} target="_blank" rel="noreferrer">
                  {j.title}
                </a>
                <span className="job-where">
                  <strong>{j.company_name}</strong>
                  {j.location ? `, ${j.location}` : ""}
                </span>
              </div>
              <dl className="job-facts">
                <div>
                  <dt>Reach</dt>
                  <dd className={j.reach === "Within reach" ? "reach-in" : "reach-stretch"}>
                    {j.reach ?? "Not stated"}
                    {j.years_required ? ` (${j.years_required} yrs)` : ""}
                  </dd>
                </div>
                <div>
                  <dt>Posted pay</dt>
                  <dd>{payRange(j.salary_min_yearly_usd, j.salary_max_yearly_usd)}</dd>
                </div>
                <div>
                  <dt>H-1B filings</dt>
                  <dd>{j.company_lca_filings?.toLocaleString("en-US") ?? "None found"}</dd>
                </div>
                <div>
                  <dt>First seen</dt>
                  <dd>{shortDay(String(j.first_seen).slice(0, 10))}</dd>
                </div>
                <div>
                  <dt>Fit</dt>
                  <dd>
                    <FitMeter score={j.fit_score} />
                  </dd>
                </div>
              </dl>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
