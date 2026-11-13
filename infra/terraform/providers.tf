provider "aws" {
  region  = var.region
  profile = var.profile
}

# The account ID is looked up at run time, so it never appears in this repo.
data "aws_caller_identity" "current" {}
