# Infrastructure (Terraform)

Job Radar's AWS setup as code: the raw-data bucket, the ingest user and its policy, the
budget alarm, and (from T30b) the image registry, the API on Lambda and keyless GitHub access.

```bash
cd infra/terraform
terraform init
terraform plan        # shows what would change; read it before every apply
terraform apply       # asks for "yes"
```

Runs as the `jobradar-admin` profile (never root). State is local and git-ignored. Secrets are
never in these files or in state: they live in SSM Parameter Store, set with the AWS CLI.
The budget alarm's notification email is a variable kept in `terraform.tfvars` (git-ignored).

## The API on Lambda (T30b)

| File | What it creates |
|---|---|
| `ecr.tf` | `job-radar-api` image store: immutable tags, scan on push, keep the last 10 |
| `lambda.tf` | `job-radar-api` function (container image, arm64, 1 GB, 60 s), its role (logs + read `/job-radar/prod/*` parameters only), 14-day logs, a public HTTPS function URL |
| `github_oidc.tf` | GitHub OIDC provider and `job-radar-github-deploy` role: only `main` of this repo can assume it; it can push this image repo and update this function, nothing else |
| `outputs.tf` | `api_url`, `ecr_repository_url`, `github_deploy_role_arn` |

Secrets are SSM SecureString parameters under `/job-radar/prod/`, created once with
`aws ssm put-parameter`; the app loads them at start-up. First deploy: create the image store
(`terraform apply -target=aws_ecr_repository.api`), push an image tagged `bootstrap`, then
`terraform apply`. Later images are shipped by GitHub (T31); Terraform ignores `image_uri`.
