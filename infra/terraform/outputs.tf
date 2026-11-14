output "api_url" {
  description = "Public HTTPS address of the API (needs X-API-Key except /health)"
  value       = aws_lambda_function_url.api.function_url
}

output "ecr_repository_url" {
  description = "Where API images are pushed"
  value       = aws_ecr_repository.api.repository_url
}

output "github_deploy_role_arn" {
  description = "Role GitHub Actions assumes to deploy (T31)"
  value       = aws_iam_role.github_deploy.arn
}

output "alerts_topic_arn" {
  description = "SNS topic that emails alerts"
  value       = aws_sns_topic.alerts.arn
}

output "github_daily_role_arn" {
  description = "Role the GitHub daily workflow assumes (OIDC, no stored keys)"
  value       = aws_iam_role.github_daily.arn
}
