{#
  Business rules for job postings. Each rule is written once here and reused by every model,
  so the labeling queue, the app, the agent and Tableau all agree on what "US", "Data / BI / AI"
  or "senior" means. Each macro takes a column name and returns a SQL expression.
  These are the same rules the labeling queue used (sql/label_queue.sql).
#}

{% macro is_us_location(col) -%}
(
     coalesce({{ col }}, '') ILIKE '%United States%'
  OR coalesce({{ col }}, '') RLIKE ', (AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\\b'
  OR coalesce({{ col }}, '') RLIKE '(?i)remote.*(\\bUS\\b|USA|United States)'
  OR coalesce({{ col }}, '') RLIKE '(?i)^(San Francisco|New York|Seattle|Austin|Chicago|Boston|Denver|Mountain View|Palo Alto)'
)
{%- endmacro %}

{% macro role_family(col) -%}
CASE
  WHEN {{ col }} RLIKE '(?i)business systems|systems analyst|\\berp\\b|netsuite|\\bsap\\b|oracle|workday|salesforce|coupa|enterprise applications|financ(e|ial) systems' THEN 'Business systems / ERP'
  WHEN {{ col }} RLIKE '(?i)integration|solutions? (engineer|architect)|\\bconsultant\\b|consulting|implementation|forward deployed|customer engineer' THEN 'Integration / solutions'
  WHEN {{ col }} RLIKE '(?i)data engineer|analytics engineer|\\betl\\b|data warehouse|business intelligence|\\bbi\\b|power bi|tableau|data analyst|analytics|data scien|machine learning|\\bml\\b|\\bai\\b|artificial intelligence' THEN 'Data / BI / AI'
  WHEN {{ col }} RLIKE '(?i)software (engineer|developer)|backend|full stack|python|application developer' THEN 'Software'
  WHEN {{ col }} RLIKE '(?i)technical program manager|program analyst|product owner|technical product manager' THEN 'Technical program / product'
  ELSE 'Other'
END
{%- endmacro %}

{% macro is_intern(title_col, employment_type_col) -%}
(
     coalesce({{ title_col }}, '') RLIKE '(?i)\\bintern\\b|internship|co-op|apprentice|\\bstudent\\b'
  OR coalesce({{ employment_type_col }}, '') = 'Intern'
)
{%- endmacro %}

{#
  Levels you would apply to: not an intern and not Staff / principal or above.
  Plain "Program Manager" and "Business Analyst" are left in Other on purpose: they are
  rarely visa-safe, so they are not target roles.
#}
{% macro is_target_level(col) -%}
(
  not coalesce({{ col }}, '') RLIKE '(?i)\\bintern\\b|internship|co-op|apprentice|\\bstudent\\b|\\bstaff\\b|principal|director|\\bhead\\b|\\bvp\\b|vice president'
)
{%- endmacro %}

{% macro seniority(col) -%}
CASE
  WHEN {{ col }} RLIKE '(?i)\\bintern\\b|internship|co-op|apprentice|\\bstudent\\b' THEN 'Intern'
  WHEN {{ col }} RLIKE '(?i)director|\\bhead\\b|\\bvp\\b|vice president' THEN 'Director+'
  WHEN {{ col }} RLIKE '(?i)\\bstaff\\b|principal' THEN 'Staff / principal'
  WHEN {{ col }} RLIKE '(?i)\\bsenior\\b|\\bsr\\.?\\b' THEN 'Senior'
  ELSE 'Mid or not stated'
END
{%- endmacro %}
