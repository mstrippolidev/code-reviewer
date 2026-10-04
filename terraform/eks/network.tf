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

locals {
  subnet_ids = sort(data.aws_subnets.default.ids)

  subnet_tags = {
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }

  subnet_tag_assignments = {
    for pair in setproduct(local.subnet_ids, keys(local.subnet_tags)) :
    "${pair[0]}/${pair[1]}" => {
      subnet_id = pair[0]
      key       = pair[1]
    }
  }
}

resource "aws_ec2_tag" "subnets" {
  for_each = local.subnet_tag_assignments

  resource_id = each.value.subnet_id
  key         = each.value.key
  value       = local.subnet_tags[each.value.key]
}
