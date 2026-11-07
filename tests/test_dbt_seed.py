from pathlib import Path

from jobradar.config import companies_seed_csv, load_companies

ROOT = Path(__file__).resolve().parents[1]


def test_companies_seed_matches_yaml():
    expected = companies_seed_csv(load_companies(ROOT / "config" / "companies.yaml"))
    actual = (ROOT / "dbt" / "seeds" / "companies.csv").read_text()
    assert actual == expected, "run: python scripts/export_companies_seed.py"


def test_seed_csv_has_header_and_one_row_per_company():
    companies = load_companies(ROOT / "config" / "companies.yaml")
    lines = companies_seed_csv(companies).splitlines()
    assert lines[0] == "slug,name,source,board_token,tier,enabled"
    assert len(lines) == len(companies.companies) + 1
