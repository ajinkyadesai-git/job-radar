terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.70, < 8.0"
    }
  }

  # State is kept locally (git-ignored) for this one-person project. It holds resource IDs
  # and settings, never secrets: API keys live in SSM Parameter Store, set outside Terraform.
}
