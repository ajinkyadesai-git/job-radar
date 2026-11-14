# Keyless daily run (T33): the GitHub daily workflow signs in with OIDC, like deploys, so no
# long-lived AWS keys are stored in GitHub. Same trust rule (this repo's main branch, by its
# permanent IDs); same S3 permissions as the ingest user, copied from its policy.

resource "aws_iam_role" "github_daily" {
  name = "job-radar-github-daily"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "${var.github_sub_prefix}:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_daily" {
  name   = "ingest-to-s3"
  role   = aws_iam_role.github_daily.id
  policy = aws_iam_user_policy.ingest_s3.policy
}
