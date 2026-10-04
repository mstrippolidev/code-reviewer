data "aws_route53_zone" "root" {
  name         = var.domain_name
  private_zone = false
}

data "aws_lb" "frontend" {
  count = var.publish_dns ? 1 : 0

  tags = {
    "kubernetes.io/service-name"                = "${var.app_namespace}/frontend"
    "kubernetes.io/cluster/${var.cluster_name}" = "owned"
  }
}

resource "aws_route53_record" "app" {
  count = var.publish_dns ? 1 : 0

  zone_id = data.aws_route53_zone.root.zone_id
  name    = "${var.subdomain}.${var.domain_name}"
  type    = "A"

  alias {
    name                   = data.aws_lb.frontend[0].dns_name
    zone_id                = data.aws_lb.frontend[0].zone_id
    evaluate_target_health = true
  }
}
