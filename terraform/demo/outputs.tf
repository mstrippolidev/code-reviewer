output "app_url" {
  description = "Public URL of the demo."
  value       = "https://${local.app_fqdn}"
}

output "alb_dns_name" {
  description = "ALB hostname behind the Route 53 alias."
  value       = aws_lb.app.dns_name
}

output "asg_name" {
  description = "Auto Scaling group holding the k3s instance."
  value       = aws_autoscaling_group.k3s.name
}

output "ami_id" {
  description = "AMI the instance launches from."
  value       = data.aws_ami.k3s.id
}
