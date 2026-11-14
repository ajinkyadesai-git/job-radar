# Job Radar runbook

What to do when something breaks. Each entry: how you find out, how to check, how to fix.
Every case here has actually happened in this project, except where marked.

All commands run from `~/Projects/job-radar` in the `jobradar` conda environment
(`conda activate jobradar`). AWS commands use `--profile jobradar-admin --region us-west-2`.

## Where things run

| Piece | Where | Schedule |
|---|---|---|
| Daily data run: ingest → Databricks → dbt build → freshness | GitHub Actions `daily.yml` | 14:17 UTC (6:17 PST / 7:17 PDT) |
| Watchdog: did the run happen, is the data fresh | Lambda `job-radar-watchdog` | 18:47 UTC (10:47 PST / 11:47 PDT) |
| API | Lambda `job-radar-api`, function URL (`terraform -chdir=infra/terraform output api_url`) | on request |
| Deploy: build image → Lambda → `/health` → roll back on failure | GitHub Actions `deploy.yml` | every merge to `main` that touches the API |
| Alerts | SNS topic `job-radar-alerts` → email | when the watchdog finds a problem or a Lambda keeps erroring |

## 1. Email: "No ingest run today" (GitHub skipped the schedule)

GitHub sometimes skips scheduled runs when it is busy (happened Nov 11). Nothing failed;
nothing ran.

```bash
gh run list --workflow daily --limit 3          # confirm there is no run today
gh workflow run daily                            # start it by hand
gh run watch $(gh run list --workflow daily --limit 1 --json databaseId -q '.[0].databaseId')
```

Then rerun the watchdog check (see 6) and expect `"problems": []`.

## 2. Email: "Gold data is stale" or the daily run is red

The run happened but a later step failed: the Databricks job, `dbt build` (a data test
failed) or `dbt source freshness`.

```bash
gh run list --workflow daily --limit 1
gh run view <run-id> --log-failed | tail -60
```

- A dbt test failed: read which test and which rows; the data changed shape, or a rule needs
  updating. Fix in a PR; `dbt-ci` runs the same tests before merge.
- Databricks job failed: open the run link printed in the log; most often a cluster or token
  problem. Rerun with `gh workflow run daily` once fixed.
- Ingest step failed with an AWS error: see 7.

## 3. A deploy failed, or rolled back

`deploy.yml` checks `/health` 5 times after updating Lambda; if it never returns 200 it puts
the previous image back and the run goes red. The API keeps serving the old version.

```bash
gh run view <run-id> --log-failed | tail -40
API=$(terraform -chdir=infra/terraform output -raw api_url); curl -s "${API}health"
aws lambda get-function --function-name job-radar-api --profile jobradar-admin \
  --region us-west-2 --query Code.ImageUri --output text | sed 's/.*://'   # running image tag
```

Find the cause in the Lambda logs (CloudWatch log group `/aws/lambda/job-radar-api`), fix in a
PR, merge; the next deploy ships it. To redeploy the same commit: `gh run rerun <run-id>`.

## 4. Deploy or daily run: "Not authorized to perform sts:AssumeRoleWithWebIdentity"

GitHub's OIDC pass did not match the AWS role's trust rule (happened on the first deploy:
this repo uses GitHub's immutable subject with owner and repo IDs).

```bash
gh api repos/ajinkyadesai-git/job-radar/actions/oidc/customization/sub   # what GitHub sends
aws cloudtrail lookup-events --profile jobradar-admin --region us-west-2 \
  --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRoleWithWebIdentity \
  --max-results 3 --query 'Events[].CloudTrailEvent' --output json      # what AWS saw
```

Fix `github_sub_prefix` in `infra/terraform/variables.tf`, `terraform plan` (expect only the
trust policy to change), `apply`, then `gh run rerun <run-id>`.

## 5. CI is red on a PR but tests pass on the laptop

- `ModuleNotFoundError` in CI: CI installs only `.[dev]`. Add the package to the `dev` list in
  `pyproject.toml` (happened with `anthropic`).
- `ruff format` fails: run `make check` before every commit; it runs the same lint, format and
  tests as CI.
- `evals-smoke/safety` fails: a change weakened a safety or honesty answer. Read the job summary
  (scores and the failed question), fix the prompt or tool, push again. Each run costs about
  10 cents.

## 6. Checking the watchdog by hand

```bash
aws lambda invoke --function-name job-radar-watchdog --profile jobradar-admin --region us-west-2 \
  --payload '{"source":"manual"}' --cli-binary-format raw-in-base64-out /tmp/wd.json >/dev/null \
  && cat /tmp/wd.json; echo
```

It checks the last run that should be finished: today's after 16:00 UTC, otherwise
yesterday's (a US-evening check is already tomorrow in UTC; that caused false alarms once).
Problems are also emailed.

## 7. A key or token expired

| Secret | Where it lives | Used by | Renew |
|---|---|---|---|
| Anthropic API key (laptop) | `.env` | `jobradar ask`, `jobradar eval` | console → API keys; update `.env` |
| Anthropic API key (CI) | GitHub secret `ANTHROPIC_API_KEY_CI` | `evals-smoke` | new key `job-radar-ci`; `gh secret set ANTHROPIC_API_KEY_CI` |
| Databricks token | `.env`, GitHub secret `DATABRICKS_TOKEN`, SSM `/job-radar/prod/DATABRICKS_TOKEN` | everything that queries Databricks | new token in Databricks; update all three (`aws ssm put-parameter ... --overwrite`) |
| API key for the API | `.env`, SSM `/job-radar/prod/JOBRADAR_API_KEY` | callers of `/jobs/*`, `/ask` | new random value in both |
| AWS access | none stored: GitHub uses OIDC roles; the laptop uses the admin profile with MFA | | |

Symptoms: 401/403 from the service, `invalid x-api-key`, or Databricks `Invalid access token`.
Check each key's expiry date in the console; renew before it lapses.

## 8. Costs

- AWS: budget alarm emails at 85% and 100% of $10 a month and when the forecast passes $10.
  Normal: about $0 (S3 write requests may exceed the free tier by about a cent).
- Claude API: account limit $10 a month (console → Billing). A full eval run is about $2.40
  on Sonnet 5.5, a safety smoke run about 10 cents, a Haiku run of 15 questions about 2 cents.
- Billing access for IAM users is turned off; checking bills needs the root user (with MFA).
  Known open item: the card on file expired, and the account is billed by AWS India
  (Indian payment methods only).

## 9. Changing infrastructure

Never in the AWS Console. Edit `infra/terraform/*.tf` on a branch, then:

```bash
cd infra/terraform && terraform fmt && terraform plan -out=x.tfplan
# read the plan: only what you expect to add / change, never an unexpected destroy
terraform apply x.tfplan && rm x.tfplan
```

Commit the `.tf` change in a PR. `terraform.tfvars` (alert emails) and state stay on the
laptop, git-ignored.
