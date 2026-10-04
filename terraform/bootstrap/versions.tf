terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region = var.region
  # add this tags to any resources created by this provider
  default_tags {
    tags = {
      Project = "code-reviewer"
      Stack   = "bootstrap"
    }
  }
}
