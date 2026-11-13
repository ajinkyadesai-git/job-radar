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
