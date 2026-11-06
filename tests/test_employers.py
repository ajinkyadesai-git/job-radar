from pathlib import Path

import pytest

from jobradar.config import load_companies
from jobradar.lakehouse.employers import company_keys, load_aliases, normalize_employer

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Stripe, Inc.", "stripe"),
        ("STRIPE INC", "stripe"),
        ("Anthropic, PBC", "anthropic"),
        ("Crusoe Energy Systems L.L.C.", "crusoe energy systems"),
        ("The Home Depot, Inc.", "home depot"),
        ("AT&T Services, Inc.", "at and t services"),
        ("Notion Labs, Inc.", "notion labs"),  # "labs" is kept: it can tell companies apart
        ("Maplebear Inc. d/b/a Instacart", "maplebear"),
        ("Inc.", "inc"),  # never normalize a name down to nothing
        ("", None),
        (None, None),
    ],
)
def test_normalize_employer(raw, expected):
    assert normalize_employer(raw) == expected


def test_company_keys_include_name_and_slug():
    assert company_keys("scale-ai", "Scale AI") == {"scale ai"}
    assert company_keys("gitlab", "GitLab") == {"gitlab"}


def test_alias_file_is_valid_and_names_known_companies():
    slugs = {c.slug for c in load_companies(ROOT / "config/companies.yaml").companies}
    aliases = load_aliases(ROOT / "config/employer_aliases.csv", slugs)
    assert aliases, "alias file should not be empty"


def test_alias_file_rejects_bad_rows(tmp_path):
    bad = tmp_path / "aliases.csv"
    bad.write_text(
        "company_slug,dol_employer_name,status,reason\n"
        "stripe,Stripe Inc.,approved,x\n"
        "ramp,Stripe Inc,approved,same filer approved for two companies\n"
    )
    with pytest.raises(ValueError, match="approved for stripe and ramp"):
        load_aliases(bad)
    bad.write_text("company_slug,dol_employer_name,status,reason\nstripe,Stripe,maybe,x\n")
    with pytest.raises(ValueError, match="status"):
        load_aliases(bad)
