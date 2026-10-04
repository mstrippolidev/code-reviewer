data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

data "aws_ami" "k3s" {
  owners      = ["self"]
  most_recent = true

  filter {
    name   = "tag:Role"
    values = ["demo-ami"]
  }
}

data "aws_route53_zone" "root" {
  name         = var.domain_name
  private_zone = false
}

data "aws_acm_certificate" "app" {
  domain      = local.app_fqdn
  statuses    = ["ISSUED"]
  most_recent = true
}

locals {
  app_fqdn          = "${var.subdomain}.${var.domain_name}"
  state_bucket_name = "code-reviewer-tfstate-${data.aws_caller_identity.current.account_id}"
}
