import { useMemo, useState } from "react";
import { api } from "../api";
import { money, percent } from "../format";
import { Status } from "../Status";
import type { Employer } from "../types";
import { useLoad } from "../useLoad";

type SortKey = "company_name" | "open_us_postings" | "filings" | "median_filed_wage";
const COLUMNS: { key: SortKey; label: string; numeric: boolean }[] = [
  { key: "company_name", label: "Company", numeric: false },
  { key: "open_us_postings", label: "Open US jobs", numeric: true },
  { key: "filings", label: "H-1B filings", numeric: true },
  { key: "median_filed_wage", label: "Median filed wage", numeric: true },
];

export default function Employers() {
  const { data, error, loading } = useLoad(() => api.employers(), []);
  const [sort, setSort] = useState<SortKey>("open_us_postings");
  const rows = useMemo(() => {
    const list = [...(data?.employers ?? [])];
    list.sort((a: Employer, b: Employer) =>
      sort === "company_name"
        ? a.company_name.localeCompare(b.company_name)
        : (b[sort] ?? -1) - (a[sort] ?? -1),
    );
    return list;
  }, [data, sort]);

  return (
    <section aria-labelledby="emp-title">
      <h2 id="emp-title" className="lede">
        {data
          ? `${data.count} companies tracked, chosen from Department of Labor filings.`
          : "Companies tracked, chosen from Department of Labor filings."}
      </h2>
      <p className="sub">
        Filings are H-1B Labor Condition Applications from the last year. The filed wage is what the
        company put on the form, which is a floor, not a salary range.
      </p>
      <Status loading={loading} error={error} what="employers" />
      {rows.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    className={c.numeric ? "num" : undefined}
                    aria-sort={sort === c.key ? (c.numeric ? "descending" : "ascending") : "none"}
                  >
                    <button type="button" onClick={() => setSort(c.key)}>
                      {c.label}
                    </button>
                  </th>
                ))}
                <th className="num">Approved</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.company}>
                  <td>{e.company_name}</td>
                  <td className="num">{e.open_us_postings.toLocaleString("en-US")}</td>
                  <td className="num">{e.filings.toLocaleString("en-US")}</td>
                  <td className="num">{money(e.median_filed_wage)}</td>
                  <td className="num">{percent(e.certified_rate)}</td>
                  <td>{e.is_h1b_dependent_employer ? "Mostly H-1B staff" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
