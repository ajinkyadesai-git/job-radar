"""A fixed list of skills and tools, and how to spot them in a resume or a job posting.

Used by the resume_fit tool. A fixed list (rather than letting a model extract skills) keeps
the result repeatable and testable, and means only skill names, never resume text, leave
the laptop. Skills outside this list are not counted; add them here when a gap shows up.
"""

from __future__ import annotations

import re

# name -> regex (case-insensitive). Word boundaries keep "Java" from matching "JavaScript".
SKILLS: dict[str, str] = {
    # languages
    "Python": r"\bpython\b",
    "SQL": r"\bsql\b",
    "Java": r"\bjava\b(?!\s*script)",
    "JavaScript": r"\bjavascript\b|\bnode\.?js\b",
    "TypeScript": r"\btypescript\b",
    "Scala": r"\bscala\b",
    "C#": r"(?<![\w#])c#(?![\w#])|\.net\b",
    "Bash/shell": r"\bbash\b|\bshell script",
    "Apex": r"\bapex\b",
    # data engineering
    "Spark": r"\bspark\b|\bpyspark\b",
    "Databricks": r"\bdatabricks\b",
    "Snowflake": r"\bsnowflake\b",
    "BigQuery": r"\bbig\s?query\b",
    "Redshift": r"\bredshift\b",
    "dbt": r"\bdbt\b",
    "Airflow": r"\bairflow\b",
    "Kafka": r"\bkafka\b",
    "Delta Lake": r"\bdelta lake\b|\bdelta tables?\b",
    "ETL/ELT": r"\betl\b|\belt\b",
    "Data modeling": r"\bdata model(?:l)?ing\b|\bdimensional model|\bstar schema\b",
    "Data warehousing": r"\bdata warehous",
    "Postgres": r"\bpostgres(?:ql)?\b",
    "MySQL": r"\bmysql\b",
    "NoSQL": r"\bnosql\b|\bmongodb\b|\bdynamodb\b|\bcassandra\b",
    "pandas": r"\bpandas\b",
    # cloud and engineering practice
    "AWS": r"\baws\b|\bamazon web services\b",
    "Azure": r"\bazure\b",
    "GCP": r"\bgcp\b|\bgoogle cloud\b",
    "Docker": r"\bdocker\b|\bcontaineri[sz]",
    "Kubernetes": r"\bkubernetes\b|\bk8s\b",
    "Terraform": r"\bterraform\b",
    "CI/CD": r"\bci\s?/\s?cd\b|\bgithub actions\b|\bjenkins\b",
    "Git": r"\bgit\b|\bgithub\b|\bgitlab\b",
    "Linux": r"\blinux\b|\bunix\b",
    "REST APIs": r"\brest(?:ful)?\s+apis?\b|\brestful\b|\bapis?\b",
    "GraphQL": r"\bgraphql\b",
    "Webhooks": r"\bwebhooks?\b",
    "JSON/XML": r"\bjson\b|\bxml\b",
    "Unit testing": r"\bunit test|\bpytest\b|\btest automation\b",
    "React": r"\breact(?:\.js)?\b",
    "FastAPI/Flask": r"\bfastapi\b|\bflask\b|\bdjango\b",
    # integration platforms
    "MuleSoft": r"\bmulesoft\b",
    "Boomi": r"\bboomi\b",
    "Workato": r"\bworkato\b",
    "Celigo": r"\bceligo\b",
    "Zapier": r"\bzapier\b",
    "iPaaS": r"\bipaas\b|\bintegration platform",
    # business systems / ERP / CRM
    "NetSuite": r"\bnetsuite\b|\bsuitescript\b",
    "Workday": r"\bworkday\b",
    "SAP": r"\bsap\b|\bs/4\s?hana\b",
    "Oracle ERP": r"\boracle (?:cloud|erp|fusion|e-business)|\boracle financials\b",
    "Salesforce": r"\bsalesforce\b|\bsfdc\b",
    "HubSpot": r"\bhubspot\b",
    "ServiceNow": r"\bservicenow\b",
    "Coupa": r"\bcoupa\b",
    "Zuora": r"\bzuora\b",
    "Stripe Billing": r"\bstripe billing\b",
    "Jira": r"\bjira\b",
    "ERP": r"\berp\b",
    "CRM": r"\bcrm\b",
    "Order-to-cash": r"\border[- ]to[- ]cash\b|\bo2c\b|\bquote[- ]to[- ]cash\b",
    "Procure-to-pay": r"\bprocure[- ]to[- ]pay\b|\bp2p\b",
    "Record-to-report": r"\brecord[- ]to[- ]report\b|\bfinancial close\b",
    # analytics and BI
    "Tableau": r"\btableau\b",
    "Power BI": r"\bpower\s?bi\b",
    "Looker": r"\blooker\b",
    "Excel": r"\bexcel\b(?!\s+(?:at|in)\b)",
    "Statistics": r"\bstatistic(?:s|al)\b|\ba/b test",
    # AI / ML
    "Machine learning": r"\bmachine learning\b|\bml\b",
    "LLMs": r"\bllms?\b|\blarge language models?\b|\bgenai\b|\bgenerative ai\b",
    "RAG": r"\brag\b|\bretrieval[- ]augmented\b",
    "Prompt engineering": r"\bprompt engineering\b|\bprompting\b",
    "Agents": r"\bai agents?\b|\bagentic\b",
    "Vector databases": r"\bvector (?:database|store|search)s?\b|\bfaiss\b|\bpinecone\b",
    "scikit-learn": r"\bscikit[- ]learn\b|\bsklearn\b",
    "PyTorch/TensorFlow": r"\bpytorch\b|\btensorflow\b",
    # ways of working
    "Requirements gathering": r"\brequirements? gathering\b|\bbusiness requirements\b",
    "Stakeholder management": r"\bstakeholders?\b",
    "Agile/Scrum": r"\bagile\b|\bscrum\b",
    "Project management": r"\bproject management\b|\bprogram management\b",
    "Customer-facing": r"\bcustomer[- ]facing\b|\bclient[- ]facing\b",
    "Solution design": r"\bsolution design\b|\bsolutions? architect",
    "UAT": r"\buat\b|\buser acceptance test",
    "Process mapping": r"\bprocess (?:mapping|improvement|design)\b",
    "Fivetran": r"\bfivetran\b",
    "Okta": r"\bokta\b",
    "SOX controls": r"\bsox\b|\bsarbanes[- ]oxley\b",
    "Retool": r"\bretool\b",
    "Postman": r"\bpostman\b",
    # AI governance and quality
    "Data quality": r"\bdata[- ]quality\b|\bdata validation\b|\bvalidation checks?\b",
    "AI governance": r"\b(?:ai|model) governance\b|\bresponsible ai\b|\bmodel risk\b",
    "LLM evals": r"\b(?:llm|model|ai|agentic|agent) eval(?:uation)?s?\b|\bevals\b"
    r"|\beval(?:uation)? (?:suite|framework|harness)(?:es|s)?\b",
}

_COMPILED = {name: re.compile(p, re.IGNORECASE) for name, p in SKILLS.items()}

# A specific tool counts as its broader category too: Snowflake experience is data
# warehousing experience even when the resume never says "data warehouse".
IMPLIES: dict[str, tuple[str, ...]] = {
    "Snowflake": ("Data warehousing",),
    "BigQuery": ("Data warehousing",),
    "Redshift": ("Data warehousing",),
    "Databricks": ("Spark",),
    "Salesforce": ("CRM",),
    "HubSpot": ("CRM",),
    "NetSuite": ("ERP",),
    "Workday": ("ERP",),
    "SAP": ("ERP",),
    "Oracle ERP": ("ERP",),
    "MuleSoft": ("iPaaS",),
    "Boomi": ("iPaaS",),
    "Workato": ("iPaaS",),
    "Celigo": ("iPaaS",),
    "Airflow": ("ETL/ELT",),
    "dbt": ("ETL/ELT",),
    "RAG": ("LLMs",),
    "Agents": ("LLMs",),
}


def find_skills(text: str | None, implied: bool = False) -> dict[str, int]:
    """Skill name -> number of mentions in the text (only skills that appear).

    implied=True also adds the broader skills implied by specific ones (see IMPLIES); use
    it for the resume, not for postings, so a posting's own wording decides what it asks.
    """
    text = text or ""
    found = {}
    for name, rx in _COMPILED.items():
        n = len(rx.findall(text))
        if n:
            found[name] = n
    if implied:
        for name in list(found):
            for broader in IMPLIES.get(name, ()):
                found.setdefault(broader, found[name])
    return found


def context(text: str, skill: str, chars: int = 140) -> str:
    """The sentence-ish snippet around the first mention of a skill, for quoting a gap."""
    m = _COMPILED[skill].search(text or "")
    if not m:
        return ""
    start = max(0, m.start() - chars // 2)
    end = min(len(text), m.end() + chars // 2)
    snippet = " ".join(text[start:end].split())
    return ("…" if start else "") + snippet + ("…" if end < len(text) else "")
