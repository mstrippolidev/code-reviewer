variable "region" {
  description = "AWS region for ECR and ACM. Must match the region the NLB runs in, since ACM certificates are regional."
  type        = string
  default     = "us-east-2"
}

variable "domain_name" {
  description = "Apex domain of the existing Route 53 public hosted zone."
  type        = string
  default     = "mstrippolidev.com"
}

variable "subdomain" {
  description = "Label prepended to domain_name to form the app's public hostname."
  type        = string
  default     = "codereview"
}

variable "ecr_repositories" {
  description = "ECR repository names, one per image the cluster pulls."
  type        = list(string)
  default = [
    "code-reviewer-base",
    "code-reviewer-api",
    "code-reviewer-frontend",
    "code-reviewer-postgres",
  ]
}

variable "ecr_images_to_keep" {
  description = "Lifecycle policy cap: older images beyond this count expire."
  type        = number
  default     = 10
}
