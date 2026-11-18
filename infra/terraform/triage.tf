# Daily triage (T35): its own email topic, so picks and alerts arrive separately, and the
# right for the GitHub daily role to publish to it (and nothing else).

resource "aws_sns_topic" "digest" {
  name = "job-radar-digest"
}

# AWS emails a confirmation link for this subscription; click it once.
resource "aws_sns_topic_subscription" "digest_email" {
  topic_arn = aws_sns_topic.digest.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_iam_role_policy" "github_daily_digest" {
  name = "publish-triage-digest"
  role = aws_iam_role.github_daily.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sns:Publish"
      Resource = aws_sns_topic.digest.arn
    }]
  })
}

output "digest_topic_arn" {
  description = "SNS topic that emails the daily triage digest"
  value       = aws_sns_topic.digest.arn
}
