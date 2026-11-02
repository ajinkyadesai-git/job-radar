# AWS setup

Use a **personal** AWS account. At this project's size everything stays inside the free tier;
the budget alarm is the safety net for the project's $50 total budget.

Already done in the AWS console (Milestone 1, day 1):

- A $10 monthly cost budget that emails you.
- MFA on the root user; root has no access keys.
- An admin IAM user with MFA and a CLI profile named `jobradar-admin` (region `us-west-2`).

Check the admin profile works:

```bash
aws sts get-caller-identity --profile jobradar-admin   # Arn ends in user/<your-admin-user>
```

## 1. Bucket (private, encrypted, versioned)

Bucket names are global, so add something unique, for example your initials and four digits.

```bash
BUCKET=job-radar-<initials>-<4-digits>
REGION=us-west-2
aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
  --create-bucket-configuration LocationConstraint="$REGION" --profile jobradar-admin
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true --profile jobradar-admin
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' --profile jobradar-admin
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled --profile jobradar-admin
```

## 2. Least-privilege IAM user for the ingest

The ingest never runs as the admin. This user can read and write only `raw/`, `state/` and
`ops/` under `dev/` and `prod/`, and cannot delete anything; bucket versioning keeps overwritten
state files recoverable.

```bash
sed "s/BUCKET_NAME/$BUCKET/g" infra/aws/ingest-user-policy.json > ingest-policy.json
aws iam create-user --user-name job-radar-ingest --profile jobradar-admin
aws iam put-user-policy --user-name job-radar-ingest \
  --policy-name job-radar-ingest-s3 --policy-document file://ingest-policy.json --profile jobradar-admin
aws iam create-access-key --user-name job-radar-ingest --profile jobradar-admin   # shown once: save both values
aws configure --profile job-radar-ingest                    # paste them; region us-west-2; output json
```

`ingest-policy.json` holds your bucket name; it is git-ignored.

## 3. Run it

```bash
cp .env.example .env    # set JOBRADAR_S3_BUCKET; AWS_PROFILE=job-radar-ingest is already set
make verify             # every board should show 200 and a job count
make ingest             # first run: boards "landed"
make ingest             # second run the same day: all "unchanged", no new raw files
aws s3 ls "s3://$BUCKET/dev/raw/" --recursive --profile job-radar-ingest | head
```

## Later milestones

- **Milestone 3:** the daily GitHub Actions run needs `JOBRADAR_S3_BUCKET` and
  `JOBRADAR_AWS_REGION` as repository variables, and a second access key for `job-radar-ingest`
  as secrets, so laptop and CI keys can be rotated separately.
- **Milestone 5:** Terraform imports the bucket, the ingest user and the budget, and GitHub
  Actions switches to OIDC so no long-lived AWS keys are stored in GitHub.
