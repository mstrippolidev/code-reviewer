variable "region" {
  description = "AWS region for the cluster. Keep equal to BEDROCK_REGION so model calls stay in-region."
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

variable "cluster_name" {
  description = "EKS cluster name; also used to name and tag the VPC and IAM roles."
  type        = string
  default     = "code-reviewer-demo"
}

variable "kubernetes_version" {
  description = "EKS control plane version."
  type        = string
  default     = "1.34"
}

variable "stateful_node_group" {
  description = "Spot node group for Postgres and Kafka, tainted workload=stateful:NoSchedule."
  type = object({
    instance_types = list(string)
    min_size       = number
    desired_size   = number
    max_size       = number
  })
  default = {
    instance_types = ["c5.xlarge", "c5a.xlarge", "c6i.xlarge", "c6a.xlarge", "c7i.xlarge"]
    min_size       = 3
    desired_size   = 3
    max_size       = 3
  }
}

variable "stateless_node_group" {
  description = "Spot node group for the api and frontend pods that KEDA scales."
  type = object({
    instance_types = list(string)
    min_size       = number
    desired_size   = number
    max_size       = number
  })
  default = {
    instance_types = ["c5.xlarge", "c5a.xlarge", "c6i.xlarge", "c6a.xlarge", "c7i.xlarge"]
    min_size       = 3
    desired_size   = 3
    max_size       = 3
  }
}

variable "node_disk_size_gb" {
  description = "Root volume size per node. The api image bundles the cross-encoder model, so the 20 GiB default is tight."
  type        = number
  default     = 40
}

variable "cluster_admin_principal_arns" {
  description = "IAM principals granted cluster-admin through EKS access entries, in addition to whoever runs terraform apply."
  type        = list(string)
  default     = []
}

variable "app_namespace" {
  description = "Kubernetes namespace of the api ServiceAccount, used in the IRSA trust policy."
  type        = string
  default     = "code-reviewer"
}

variable "api_service_account" {
  description = "Name of the api ServiceAccount, used in the IRSA trust policy."
  type        = string
  default     = "api"
}

variable "bedrock_model_ids" {
  description = "Foundation model IDs the api pod may invoke."
  type        = list(string)
  default     = ["deepseek.v3-v1:0", "amazon.titan-embed-text-v2:0"]
}

variable "api_public_access_cidrs" {
  description = "CIDRs allowed to reach the public EKS API endpoint. GitHub-hosted runners have no fixed IPs, hence the open default."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "publish_dns" {
  description = "Create the Route 53 alias to the frontend NLB. False on the first apply: Kubernetes only creates the NLB after the manifests are applied."
  type        = bool
  default     = false
}
