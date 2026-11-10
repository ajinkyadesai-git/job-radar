{#
  Business rules for job postings. Each rule is written once here and reused by every model,
  so the labeling queue, the app, the agent and Tableau all agree on what "US", "Data / BI / AI"
  or "senior" means. Each macro takes a column name and returns a SQL expression.
  These are the same rules the labeling queue used (sql/label_queue.sql).
#}

{% macro is_us_location(col) -%}
((
     coalesce({{ col }}, '') ILIKE '%United States%'
  OR coalesce({{ col }}, '') RLIKE ', (AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\\b'
  OR coalesce({{ col }}, '') RLIKE '(?i)remote.*(\\bUS\\b|USA|United States)'
  OR coalesce({{ col }}, '') RLIKE '(?i)^(San Francisco|New York|Seattle|Austin|Chicago|Boston|Denver|Mountain View|Palo Alto)'
)
{# ", IN" is Indiana but also India ("Bengaluru, IN"): an Indian city with no US marker is not US. #}
AND NOT (
      coalesce({{ col }}, '') RLIKE '(?i)bengaluru|bangalore|hyderabad|pune|mumbai|delhi|gurgaon|gurugram|chennai|noida|\\bindia\\b'
  AND NOT coalesce({{ col }}, '') RLIKE '(?i)united states|\\busa?\\b'
))
{%- endmacro %}

{% macro role_family(col) -%}
CASE
  WHEN {{ col }} RLIKE '(?i)business systems|systems analyst|\\berp\\b|netsuite|\\bsap\\b|oracle|workday|salesforce|coupa|enterprise applications|financ(e|ial) systems' THEN 'Business systems / ERP'
  WHEN {{ col }} RLIKE '(?i)integration|solutions? (engineer|architect)|\\bconsultant\\b|consulting|implementation|forward deployed|\\bfde\\b|customer engineer' THEN 'Integration / solutions'
  WHEN {{ col }} RLIKE '(?i)data (platform |infrastructure |pipeline )?engineer|analytics engineer|\\betl\\b|data warehouse|business intelligence|\\bbi\\b|power bi|tableau|data analyst|analytics|data scien|machine learning|\\bml\\b|\\bai\\b|artificial intelligence' THEN 'Data / BI / AI'
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
  Levels you would apply to: not an intern, not Staff / principal or above, not a people manager.
  Plain "Program Manager" and "Business Analyst" are left in Other on purpose: they are
  rarely visa-safe, so they are not target roles.
#}
{% macro is_target_level(col) -%}
(
  not coalesce({{ col }}, '') RLIKE '(?i)\\bintern\\b|internship|co-op|apprentice|\\bstudent\\b|\\bstaff\\b|principal|director|\\bhead\\b|\\bvp\\b|vice president'
  {# People managers (from your labels). "Technical Program Manager" and "Product Manager"
     are individual roles and stay in. #}
  and not coalesce({{ col }}, '') RLIKE '(?i)^(?:sr\\.? |senior )?manager\\b|engineering manager|science manager|analytics manager|group product manager|(?:senior|sr\\.?) manager\\b|manager of\\b'
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


{#
  Visa rules on the posting text (CR11). Each regex finds just the phrase; stg_postings then
  cuts 80 characters either side of it, so every dropped job shows exactly why it was dropped
  (gold.audit_dropped_postings). "Unable to sponsor for this role, but..." still matches:
  review the audit table for false positives before tightening a pattern.
  Patterns start with a word, never with "any characters": a leading .{0,80} made Spark try
  every starting point in every description and the build ran for 30+ minutes.
#}
{% macro visa_blocker_regex() -%}
'(?is)((?:unable|not able|cannot|can ?not|can.t|will not|won.t|do not|does not|are not able|is not able)\\s+(?:to\\s+)?(?:currently\\s+)?(?:sponsor|provide|offer|support)\\b.{0,40}?(?:visa|sponsorship|immigration|h-?1b|work authori[sz]ation)|without (?:the )?(?:need for |requiring )?(?:current or future |now or in the future |future )?(?:visa |employer |immigration )?sponsorship|not eligible for (?:visa )?sponsorship|sponsorship (?:is )?not (?:available|offered)|(?:must|need to) be (?:a |an )?u\\.?s\\.? citizen|u\\.?s\\.? citizenship (?:is )?required|(?:active|current|secret|top secret|ts/sci|public trust)\\s+(?:security\\s+)?clearance|(?:obtain|maintain|eligible (?:for|to obtain))\\s+.{0,20}security clearance)'
{%- endmacro %}

{#
  Green-card (PERM) style ads: posted to satisfy a labor-certification requirement for an
  existing employee, not to hire. They read like legal notices.
  Only phrases that ordinary postings don't use: "40 hours per week" and "position offered"
  were dropped after the audit table showed them in normal Reddit, Instacart and MongoDB ads.
#}
{% macro perm_ad_regex() -%}
'(?is)(in each of the following|employer will accept|apply by mail|labor certification|\\bperm\\b)'
{%- endmacro %}

{# The matched phrase with up to 80 characters either side; null when nothing matched. #}
{% macro with_context(text_col, match_col) -%}
case when {{ match_col }} <> '' then
  substring({{ text_col }}, greatest(instr({{ text_col }}, {{ match_col }}) - 80, 1),
            length({{ match_col }}) + 160)
end
{%- endmacro %}
