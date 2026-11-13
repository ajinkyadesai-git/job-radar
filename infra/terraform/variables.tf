variable "region" {
  description = "AWS region for Job Radar"
  type        = string
  default     = "us-west-2"
}

variable "profile" {
  description = "AWS CLI profile Terraform runs as (the admin user, never root)"
  type        = string
  default     = "jobradar-admin"
}

variable "budget_alert_emails" {
  description = "Who gets budget alerts. Set in terraform.tfvars (git-ignored), not here."
  type        = list(string)
  sensitive   = true
}

variable "image_tag" {
  description = "Image tag for the first Lambda deploy (later deploys come from GitHub)"
  type        = string
  default     = "bootstrap"
}

variable "github_repo" {
  description = "owner/name of the GitHub repo allowed to deploy"
  type        = string
  default     = "ajinkyadesai-git/job-radar"
}
