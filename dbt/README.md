# dbt: gold layer

Builds the gold tables from the silver tables made by the notebooks in `spark/`.

| Model | What it is |
|---|---|
| `stg_postings` | Postings with the business rules applied once: `is_us`, `role_family`, `seniority`, `is_intern`, `is_fte_or_contract`, yearly salary |
| `stg_lca_filings`, `stg_employer_matches` | Light renames of the silver tables |
| `dim_employer` | One row per tracked company: open jobs, sponsor history, approval rate, filed pay |
| `fct_postings` | Every posting seen, with sponsor stats attached |
| `fct_lca` | DOL filings, with the tracked company attached when the filer is ours |
| `mart_new_postings` | The "Today" list: new US full-time/contract roles at sponsors, last 7 days |
| `mart_sponsor_stats` | Filings, approval rate and filed pay by company and occupation |

The rules live in `macros/job_rules.sql`. `seeds/companies.csv` is generated from
`config/companies.yaml` by `scripts/export_companies_seed.py`.

## Run

```zsh
pip install -e ".[dbt]"
cd dbt
set -a; source ../.env; set +a
dbt seed  --target dev --profiles-dir .
dbt build --target dev --profiles-dir .   # models + tests + unit test
```

Check that the daily data is fresh (warns after 36 hours, fails after 60; run it on prod,
because the daily schedule writes prod):

```zsh
dbt source freshness --target prod --profiles-dir .
```

## Tests

- **Generic tests** in the `_*.yml` files: unique and not-null keys, allowed values, and links
  between tables (every posting's company exists in `dim_employer`, and so on).
- **Unit test** `posting_rules_us_role_family_intern`: the posting rules on 10 hand-made titles.
- **Data tests** in `tests/`: match rate at least 90%, the Today list follows its rules, at
  least 1,000 open postings, dates in order, employer counts consistent, one company per filer
  name, one row per company and occupation. `warn_salary_min_above_max` only warns.

`--target dev` writes `workspace.jobradar_dev_staging` / `jobradar_dev_gold` from dev silver;
`--target prod` writes `jobradar_staging` / `jobradar_gold` from prod silver.
