# Contributing

Thanks for helping. Issues labeled `good first issue` are a good place to start.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
make install
make test lint
```

Tests never touch the network or AWS: HTTP is mocked with `responses` and S3 with `moto`.

## Adding a company

Add one line to `config/companies.yaml`, run `jobradar verify --only <slug>`, and include the
output in your pull request.

## Adding a job-board vendor

Subclass `BoardAdapter` in `src/jobradar/ingest/boards.py` (URL, params and known fields), add it
to `ADAPTERS`, and add a fixture plus tests modeled on `tests/test_pipeline.py`.

## Pull requests

- One change per PR, with a clear title in the imperative ("Add Lever adapter").
- CI (ruff + pytest) must pass.
- Never commit secrets, resumes or personal data.
