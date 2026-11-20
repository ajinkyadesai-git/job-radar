import { api } from "../api";
import { plural, shortDay } from "../format";
import { Status } from "../Status";
import { useLoad } from "../useLoad";

const COLUMNS: [string, string][] = [
  ["visit", "Visits"],
  ["match", "Resume matches"],
  ["ask", "Questions"],
  ["tab:employers", "Employers"],
  ["tab:insights", "Insights"],
  ["tab:ask", "Ask tab"],
  ["feedback", "Feedback"],
];

/** The owner's private page: daily counts, where visits came from, and feedback (CR19). */
export default function Usage() {
  const { data, error, loading } = useLoad(() => api.usage(), []);
  if (!data) return <Status loading={loading} error={error} what="usage" />;

  const total = (key: string) => data.days.reduce((n, d) => n + (d.events[key] ?? 0), 0);
  const sites = new Map<string, number>();
  for (const d of data.days) {
    for (const [host, n] of Object.entries(d.referrers)) sites.set(host, (sites.get(host) ?? 0) + n);
  }
  const topSites = [...sites.entries()].sort((a, b) => b[1] - a[1]).slice(0, 10);

  return (
    <section aria-labelledby="usage-title">
      <h2 id="usage-title" className="lede">
        {`${plural(total("visit"), "visit")}, ${plural(total("match"), "resume match", "resume matches")} and ${plural(total("ask"), "question")} in the last two weeks.`}
      </h2>
      <p className="sub">
        Counts per day, without names, emails, IP addresses or resumes. Your own use while
        unlocked is not counted.
      </p>

      <div className="table-wrap">
        <table className="usage">
          <thead>
            <tr>
              <th scope="col">Day</th>
              {COLUMNS.map(([, label]) => (
                <th key={label} scope="col" className="num">
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.days.map((d) => (
              <tr key={d.day}>
                <th scope="row">{shortDay(d.day)}</th>
                {COLUMNS.map(([key]) => (
                  <td key={key} className="num">
                    {d.events[key] ?? 0}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="usage-cols">
        <div>
          <h3>Where visits came from</h3>
          {topSites.length ? (
            <ol className="sites">
              {topSites.map(([host, n]) => (
                <li key={host}>
                  <span>{host === "direct" ? "Direct or unknown" : host}</span>
                  <b>{n}</b>
                </li>
              ))}
            </ol>
          ) : (
            <p className="status">No visits yet.</p>
          )}
        </div>
        <div>
          <h3>Feedback</h3>
          {data.feedback.length ? (
            <ul className="feedback-list">
              {data.feedback.map((f) => (
                <li key={f.at + f.message.slice(0, 20)}>
                  <p>{f.message}</p>
                  <span>
                    {shortDay(f.at.slice(0, 10))}
                    {f.page ? ` · from ${f.page}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="status">No feedback yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}
