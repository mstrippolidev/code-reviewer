resource "aws_autoscaling_group" "k3s" {
  name                      = var.name
  min_size                  = 1
  max_size                  = 1
  desired_capacity          = 1
  vpc_zone_identifier       = data.aws_subnets.default.ids
  target_group_arns         = [aws_lb_target_group.app.arn]
  health_check_type         = "ELB"
  health_check_grace_period = var.boot_grace_seconds
  capacity_rebalance        = false
  wait_for_capacity_timeout = "0"

  mixed_instances_policy {
    instances_distribution {
      on_demand_percentage_above_base_capacity = 100
    }

    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.k3s.id
        version            = aws_launch_template.k3s.latest_version
      }

      dynamic "override" {
        for_each = var.instance_types

        content {
          instance_type = override.value
        }
      }
    }
  }
}
