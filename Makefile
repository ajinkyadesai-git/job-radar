.PHONY: install test lint fmt verify ingest ingest-local check-databricks

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

fmt:
	ruff check --fix .
	ruff format .

verify:            ## read-only: does every board token respond?
	jobradar verify

ingest:            ## land raw JSON in S3 (needs .env)
	jobradar ingest --dest s3

ingest-local:      ## land raw JSON under ./data
	jobradar ingest --dest local

check-databricks:  ## week 1 check: can we reach the Free Edition SQL warehouse?
	pip install -e ".[databricks]" -q
	python scripts/check_databricks.py
