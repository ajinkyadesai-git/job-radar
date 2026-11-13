"""The container image: no secrets or local data inside, non-root, health check wired."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
IGNORE = (ROOT / ".dockerignore").read_text().split()


def test_secrets_and_local_data_never_enter_the_build():
    for path in (".env", "data", ".git", "evals/results"):
        assert path in IGNORE, f"{path} must be in .dockerignore"
    copies = re.findall(r"^COPY (?!--from)(.+)$", DOCKERFILE, re.MULTILINE)
    assert copies == ["pyproject.toml README.md ./", "src ./src"]  # never "COPY . ."


def test_no_secret_values_are_baked_into_the_image():
    for name in ("JOBRADAR_API_KEY", "DATABRICKS_TOKEN", "ANTHROPIC_API_KEY"):
        assert not re.search(rf"^\s*(ENV|ARG)\b.*{name}", DOCKERFILE, re.MULTILINE)


def test_runs_as_non_root_with_health_check():
    assert re.search(r"^USER app$", DOCKERFILE, re.MULTILINE)
    assert "AWS_LWA_READINESS_CHECK_PATH=/health" in DOCKERFILE
    assert "HEALTHCHECK" in DOCKERFILE and "/health" in DOCKERFILE
