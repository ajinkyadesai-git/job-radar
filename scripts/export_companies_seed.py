"""Write dbt/seeds/companies.csv from config/companies.yaml.

companies.yaml is the source of truth; dbt needs the same list as a CSV seed. Run this after
editing companies.yaml (a test fails if the two drift apart):

    python scripts/export_companies_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jobradar.config import companies_seed_csv, load_companies  # noqa: E402

SEED = ROOT / "dbt" / "seeds" / "companies.csv"

if __name__ == "__main__":
    SEED.write_text(companies_seed_csv(load_companies(ROOT / "config" / "companies.yaml")))
    print(f"wrote {SEED.relative_to(ROOT)}")
