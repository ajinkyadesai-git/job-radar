export type Reach = "Within reach" | "Stretch";

export interface Job {
  posting_key: string;
  company_name: string;
  title: string;
  location: string | null;
  url: string;
  role_family: string | null;
  seniority: string | null;
  years_required: number | null;
  reach: Reach | null;
  salary_min_yearly_usd: number | null;
  salary_max_yearly_usd: number | null;
  first_seen: string;
  company_lca_filings: number | null;
  company_median_filed_wage: number | null;
  fit_score: number | null;
}

export interface Employer {
  company: string;
  company_name: string;
  board_source: string;
  open_us_postings: number;
  filings: number;
  certified_rate: number | null;
  median_filed_wage: number | null;
  is_h1b_dependent_employer: boolean;
}

export interface Insights {
  jobs_by_family: { role_family: string; open_jobs: number; good_fit: number }[];
  new_per_day: { day: string; new_jobs: number }[];
  pay_by_family: { role_family: string; with_salary: number; median_posted_midpoint: number }[];
  top_sponsors: {
    company_name: string;
    filings: number;
    certified_rate: number | null;
    median_filed_wage: number | null;
    open_us_postings: number;
  }[];
}

export interface AskResult {
  answer: string;
  model: string;
  tools: string[];
  seconds: number;
  questions_left_today: number | null;
}
