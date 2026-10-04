output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.main.name
}

output "region" {
  description = "Region the cluster runs in."
  value       = var.region
}

output "kubeconfig_command" {
  description = "Command that writes this cluster's credentials into the local kubeconfig."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${aws_eks_cluster.main.name}"
}

output "api_irsa_role_arn" {
  description = "Role ARN substituted for <API_IRSA_ROLE_ARN> in the api ServiceAccount."
  value       = aws_iam_role.api.arn
}
