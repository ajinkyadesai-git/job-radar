import { describe, expect, it } from "vitest";
import {
  fitSegments,
  median,
  money,
  payRange,
  percent,
  plural,
  shortDay,
  steadyDays,
} from "./format";

describe("format", () => {
  it("shows pay in thousands and handles missing pay", () => {
    expect(money(154606)).toBe("$155k");
    expect(payRange(120000, 180000)).toBe("$120k–$180k");
    expect(payRange(150000, 150400)).toBe("$150k");
    expect(payRange(null, null)).toBe("Pay not posted");
    expect(payRange(null, 90000)).toBe("$90k");
    expect(payRange(0, 0)).toBe("Pay not posted");
    expect(payRange(0, 150000)).toBe("$150k");
  });

  it("maps a fit score to meter segments, and unscored to null", () => {
    expect(fitSegments(0.97)).toBe(5);
    expect(fitSegments(0.5)).toBe(3);
    expect(fitSegments(0.04)).toBe(0);
    expect(fitSegments(null)).toBeNull();
  });

  it("formats percents, days and counts", () => {
    expect(percent(0.989)).toBe("99%");
    expect(percent(null)).toBe("");
    expect(shortDay("2026-11-19")).toBe("Nov 19");
    expect(plural(1, "job")).toBe("1 job");
    expect(plural(1382, "job")).toBe("1,382 jobs");
    expect(plural(6, "company", "companies")).toBe("6 companies");
    expect(plural(1, "company", "companies")).toBe("1 company");
  });

  it("drops the startup spike days and finds a typical day", () => {
    const days = [4102, 4600, 160, 240, 198, 230, 180, 120].map((n, i) => ({ day: `d${i}`, new_jobs: n }));
    const steady = steadyDays(days);
    expect(steady[0].new_jobs).toBe(160);
    expect(median(steady.map((d) => d.new_jobs))).toBe(189);
    expect(steadyDays([])).toEqual([]);
  });
});
