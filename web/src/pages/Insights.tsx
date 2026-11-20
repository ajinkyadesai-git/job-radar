import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { median, money, shortDay, steadyDays } from "../format";
import { Status } from "../Status";
import { useLoad } from "../useLoad";

const INK = "#1F2933";
const NAVY = "#13294B";
const FILED = "#1F7A5A";
const RULE = "#D5DAD3";
const axis = { fontSize: 12, fill: INK };

function Chart({ title, takeaway, children }: { title: string; takeaway: string; children: ReactNode }) {
  return (
    <figure className="chart">
      <figcaption>
        <h3>{title}</h3>
        <p>{takeaway}</p>
      </figcaption>
      <div className="chart-body">{children}</div>
    </figure>
  );
}

export default function Insights({ owner = false }: { owner?: boolean }) {
  const { data, error, loading } = useLoad(() => api.insights(), []);
  if (!data) return <Status loading={loading} error={error} what="insights" />;

  const families = data.jobs_by_family.filter((f) => f.role_family !== "Other");
  const bestShare = [...families].sort(
    (a, b) => b.good_fit / b.open_jobs - a.good_fit / a.open_jobs,
  )[0];
  const days = steadyDays(data.new_per_day); // without the first loads of newly added companies
  const typicalNew = median(days.map((d) => d.new_jobs));
  const biggest = [...families].sort((a, b) => b.open_jobs - a.open_jobs)[0];
  const pay = data.pay_by_family.filter((p) => p.role_family !== "Other");
  const sponsors = data.top_sponsors.slice(0, 10);

  return (
    <section aria-labelledby="ins-title">
      <h2 id="ins-title" className="lede">
        {owner
          ? "What the market looks like for my target roles."
          : "What the tech job market looks like at H-1B sponsors."}
      </h2>
      <p className="sub">Open US jobs at the 74 tracked companies, updated every morning.</p>

      <div className="charts">
        <Chart
          title="Open jobs by role family"
          takeaway={
            owner && bestShare
              ? `${bestShare.role_family} has the highest share of good fits: ${bestShare.good_fit} of ${bestShare.open_jobs.toLocaleString("en-US")}.`
              : biggest
                ? `${biggest.role_family} has the most open jobs: ${biggest.open_jobs.toLocaleString("en-US")}.`
                : ""
          }
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={families} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke={RULE} />
              <XAxis type="number" tick={axis} />
              <YAxis type="category" dataKey="role_family" width={170} tick={axis} />
              <Tooltip />
              <Bar dataKey="open_jobs" name="Open jobs" fill={NAVY} />
              {owner && <Bar dataKey="good_fit" name="Good fit for me (0.5+)" fill={FILED} />}
            </BarChart>
          </ResponsiveContainer>
        </Chart>

        <Chart
          title="New jobs per day"
          takeaway={`About ${typicalNew.toLocaleString("en-US")} new US jobs appear on a typical day (median; the first loads of newly added companies are left out).`}
        >
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={days} margin={{ left: 8, right: 16 }}>
              <CartesianGrid vertical={false} stroke={RULE} />
              <XAxis dataKey="day" tickFormatter={(d: string) => shortDay(String(d).slice(0, 10))} tick={axis} />
              <YAxis tick={axis} />
              <Tooltip labelFormatter={(d) => shortDay(String(d).slice(0, 10))} />
              <Line dataKey="new_jobs" name="New jobs" stroke={NAVY} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Chart>

        <Chart
          title="Median posted pay"
          takeaway={
            pay[0] ? `${pay[0].role_family} posts the highest midpoint, ${money(pay[0].median_posted_midpoint)}.` : ""
          }
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={pay} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke={RULE} />
              <XAxis type="number" tickFormatter={(v: number) => money(v)} tick={axis} />
              <YAxis type="category" dataKey="role_family" width={170} tick={axis} />
              <Tooltip formatter={(v) => money(Number(v))} />
              <Bar dataKey="median_posted_midpoint" name="Median midpoint" fill={NAVY} />
            </BarChart>
          </ResponsiveContainer>
        </Chart>

        <Chart
          title="Most H-1B filings"
          takeaway={
            sponsors[0]
              ? `${sponsors[0].company_name} filed ${sponsors[0].filings.toLocaleString("en-US")}, median filed wage ${money(sponsors[0].median_filed_wage)}.`
              : ""
          }
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={sponsors} layout="vertical" margin={{ left: 8, right: 16 }}>
              <CartesianGrid horizontal={false} stroke={RULE} />
              <XAxis type="number" tick={axis} />
              <YAxis type="category" dataKey="company_name" width={120} tick={axis} />
              <Tooltip />
              <Bar dataKey="filings" name="H-1B filings" fill={FILED} />
            </BarChart>
          </ResponsiveContainer>
        </Chart>
      </div>
    </section>
  );
}
