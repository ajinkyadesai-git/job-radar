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

variable "github_sub_prefix" {
  description = <<-EOT
    Start of the OIDC subject GitHub sends for this repo. The repo uses GitHub's immutable
    subject format (owner@owner_id/repo@repo_id), so a renamed or re-created repo with the
    same name cannot deploy. Check with:
    gh api repos/ajinkyadesai-git/job-radar/actions/oidc/customization/sub
  EOT
  type        = string
  default     = "repo:ajinkyadesai-git@58768160/job-radar@1442637701"
}

variable "alert_email" {
  description = "Where alerts go. Set in terraform.tfvars (git-ignored), not here."
  type        = string
  sensitive   = true
}
