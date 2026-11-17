output "ecr_registry" {
  description = "ECR registry host, substituted for <ECR_REGISTRY> in the k8s manifests."
  value       = split("/", aws_ecr_repository.code-reviewer["code-reviewer-api"].repository_url)[0]
}

output "ecr_repository_urls" {
  description = "Full repository URL for each image, keyed by repository name."
  value       = { for name, repo in aws_ecr_repository.code-reviewer : name => repo.repository_url }
}

output "acm_certificate_arn" {
  description = "Validated certificate ARN, substituted for <ACM_CERT_ARN> in the frontend Service."
  value       = aws_acm_certificate_validation.app.certificate_arn
}

output "alarms_topic_arn" {
  description = "SNS topic the CloudWatch alarms notify; the default of alarm_sns_topic_arns in terraform/demo."
  value       = aws_sns_topic.alarms.arn
}

output "app_fqdn" {
  description = "Public hostname of the app."
  value       = local.app_fqdn
}
