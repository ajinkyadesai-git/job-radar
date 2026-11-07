-- Which discovered companies actually file H-1Bs? (dev filings, Jul 2025 to Jun 2026)
-- Each pattern is matched against the start of the filer's cleaned name.
WITH candidates(company, pattern) AS (
  VALUES
    ('snowflake','snowflake'), ('waymo','waymo'), ('duolingo','duolingo'), ('doordash','doordash'),
    ('cloudflare','cloudflare'), ('elastic','elasticsearch|elastic n ?v|elastic inc'), ('okta','okta'),
    ('roblox','roblox'), ('toast','toast inc'), ('flexport','flexport'), ('gusto','gusto|zenpayroll'),
    ('chime','chime financial|chime inc'), ('sofi','sofi|social finance'), ('plaid','plaid'),
    ('brex','brex'), ('carta','carta|eshares'), ('squarespace','squarespace'),
    ('peloton','peloton'), ('box','box inc'), ('twitch','twitch'), ('rubrik','rubrik'),
    ('verkada','verkada'), ('anduril','anduril'), ('spacex','space exploration'), ('nuro','nuro inc'),
    ('benchling','benchling'), ('faire','faire'), ('zocdoc','zocdoc'), ('oscar','oscar health|oscar management'),
    ('vanta','vanta'), ('mercury','mercury technologies'), ('nerdwallet','nerdwallet'),
    ('upstart','upstart'), ('fivetran','fivetran'), ('sigma-computing','sigma computing'),
    ('amplitude','amplitude inc'), ('mixpanel','mixpanel'), ('braze','braze|appboy'),
    ('klaviyo','klaviyo'), ('workato','workato'), ('celonis','celonis'), ('vercel','vercel'),
    ('perplexity','perplexity'), ('cursor','anysphere'), ('harvey','harvey|counsel ai'),
    ('glean','glean technologies'), ('sierra','sierra technologies'), ('together-ai','together computer'),
    ('modal','modal labs'), ('writer','writer inc'), ('elevenlabs','eleven ?labs'),
    ('gemini','gemini space station|gemini trust'), ('nextdoor','nextdoor'), ('navan','navan|tripactions')
),
filers AS (
  SELECT trim(regexp_replace(lower(employer_name), '[^a-z0-9]+', ' ')) AS name_key,
         employer_name, case_status, soc_code
  FROM workspace.jobradar_dev_silver.lca_filings
),
hits AS (
  SELECT c.company, f.employer_name, count(*) AS filings,
         count_if(f.case_status = 'Certified') AS certified,
         count_if(substr(f.soc_code, 1, 7) IN ('15-1211','15-1221','15-1242','15-1243','15-1251','15-1252',
                  '15-1253','15-1254','15-1299','15-2031','15-2041','15-2051','13-1111','11-3021')) AS tech_filings
  FROM candidates c
  JOIN filers f ON f.name_key RLIKE concat('^(', c.pattern, ')\\b')
  GROUP BY c.company, f.employer_name
)
SELECT c.company,
       coalesce(sum(h.filings), 0)      AS filings,
       coalesce(sum(h.certified), 0)    AS certified,
       coalesce(sum(h.tech_filings), 0) AS tech_filings,
       array_join(slice(array_sort(collect_list(concat(lpad(cast(h.filings AS STRING), 5, '0'), ' ', h.employer_name)), (l, r) -> CASE WHEN l > r THEN -1 WHEN l < r THEN 1 ELSE 0 END), 1, 3), ' | ') AS top_filer_names
FROM candidates c LEFT JOIN hits h USING (company)
GROUP BY c.company
ORDER BY filings DESC
