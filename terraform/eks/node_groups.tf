locals {
  node_groups = {
    stateful = {
      scaling = var.stateful_node_group
      taints = [{
        key    = "workload"
        value  = "stateful"
        effect = "NO_SCHEDULE"
      }]
    }
    stateless = {
      scaling = var.stateless_node_group
      taints  = []
    }
  }
}

data "aws_iam_policy_document" "eks_node_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_node" {
  name               = "${var.cluster_name}-node"
  assume_role_policy = data.aws_iam_policy_document.eks_node_assume.json
}

resource "aws_iam_role_policy_attachment" "eks_node" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/${each.key}"
}

resource "aws_eks_node_group" "main" {
  for_each = local.node_groups

  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.cluster_name}-${each.key}"
  node_role_arn   = aws_iam_role.eks_node.arn
  subnet_ids      = local.subnet_ids

  capacity_type  = "SPOT"
  ami_type       = "AL2023_x86_64_STANDARD"
  instance_types = each.value.scaling.instance_types
  disk_size      = var.node_disk_size_gb

  scaling_config {
    min_size     = each.value.scaling.min_size
    desired_size = each.value.scaling.desired_size
    max_size     = each.value.scaling.max_size
  }

  update_config {
    max_unavailable = 1
  }

  labels = {
    workload = each.key
  }

  dynamic "taint" {
    for_each = each.value.taints

    content {
      key    = taint.value.key
      value  = taint.value.value
      effect = taint.value.effect
    }
  }

  depends_on = [aws_iam_role_policy_attachment.eks_node]
}
