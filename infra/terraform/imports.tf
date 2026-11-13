# T30a: bring what was made by hand in the AWS Console under Terraform, without changing it.
# Run `terraform plan -generate-config-out=generated.tf` once: Terraform writes the matching
# resource blocks; after review, `terraform apply` records them in state (no AWS changes),
# and `terraform plan` must then say "No changes".

import {
  to = aws_s3_bucket.raw
  id = "job-radar-ad-4312"
}

import {
  to = aws_s3_bucket_versioning.raw
  id = "job-radar-ad-4312"
}

import {
  to = aws_s3_bucket_server_side_encryption_configuration.raw
  id = "job-radar-ad-4312"
}

import {
  to = aws_s3_bucket_public_access_block.raw
  id = "job-radar-ad-4312"
}

import {
  to = aws_iam_user.ingest
  id = "job-radar-ingest"
}

import {
  to = aws_iam_user_policy.ingest_s3
  id = "job-radar-ingest:job-radar-ingest-s3"
}

import {
  to = aws_budgets_budget.monthly
  id = "${data.aws_caller_identity.current.account_id}:My Monthly Cost Budget"
}
