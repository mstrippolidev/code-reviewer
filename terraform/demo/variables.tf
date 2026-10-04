variable "region" {
  description = "AWS region. Keep equal to BEDROCK_REGION so model calls stay in-region."
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

variable "name" {
  description = "Prefix for every named resource in this stack."
  type        = string
  default     = "code-reviewer-demo"
}

variable "instance_types" {
  description = "On-demand instance types the ASG may choose from. All must have the same vCPU and memory."
  type        = list(string)
  default     = ["m5.2xlarge", "m5a.2xlarge", "m6i.2xlarge", "m6a.2xlarge", "m7i.2xlarge"]
}

variable "root_volume_size_gb" {
  description = "Root volume size. Must be at least the AMI's snapshot size."
  type        = number
  default     = 50
}

variable "node_port" {
  description = "NodePort the frontend Service listens on, set in the single-node overlay."
  type        = number
  default     = 30080
}

variable "boot_grace_seconds" {
  description = "How long the ASG ignores failing ELB health checks after launch, covering k3s and pod startup."
  type        = number
  default     = 900
}

variable "alb_idle_timeout_seconds" {
  description = "ALB idle timeout, long enough for the review-progress stream."
  type        = number
  default     = 600
}

variable "bedrock_model_ids" {
  description = "Foundation model IDs the instance may invoke."
  type        = list(string)
  default     = ["deepseek.v3-v1:0", "amazon.titan-embed-text-v2:0"]
}

variable "dlq_sns_topic_arn" {
  description = "SNS topic the api publishes a notification to whenever a message lands on a dead-letter queue."
  type        = string
  default     = "arn:aws:sns:us-east-1:413001138120:portfolioTopic"
}
