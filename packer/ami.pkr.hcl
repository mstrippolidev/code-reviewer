packer {
  required_version = ">= 1.10"

  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = ">= 1.3.0"
    }
  }
}

variable "region" {
  type    = string
  default = "us-east-2"
}

variable "build_instance_type" {
  type    = string
  default = "m5.xlarge"
}

variable "volume_size_gb" {
  type    = number
  default = 50
}

variable "k3s_channel" {
  type    = string
  default = "stable"
}

variable "ecr_registry" {
  type = string
}

variable "ecr_password" {
  type      = string
  sensitive = true
}

data "amazon-ami" "al2023" {
  region      = var.region
  owners      = ["amazon"]
  most_recent = true

  filters = {
    name                  = "al2023-ami-2023.*-x86_64"
    "virtualization-type" = "hvm"
    "root-device-type"    = "ebs"
  }
}

source "amazon-ebs" "k3s" {
  region        = var.region
  instance_type = var.build_instance_type
  source_ami    = data.amazon-ami.al2023.id
  ssh_username  = "ec2-user"
  ami_name      = "code-reviewer-k3s-{{timestamp}}"

  launch_block_device_mappings {
    device_name           = "/dev/xvda"
    volume_size           = var.volume_size_gb
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Project = "code-reviewer"
    Role    = "demo-ami"
  }
}

build {
  sources = ["source.amazon-ebs.k3s"]

  provisioner "file" {
    source      = "k8s.tar.gz"
    destination = "/tmp/k8s.tar.gz"
  }

  provisioner "file" {
    source      = "files/boot.sh"
    destination = "/tmp/boot.sh"
  }

  provisioner "file" {
    source      = "files/code-reviewer-boot.service"
    destination = "/tmp/code-reviewer-boot.service"
  }

  provisioner "shell" {
    script          = "scripts/bake.sh"
    execute_command = "{{ .Vars }} sudo -E bash '{{ .Path }}'"
    environment_vars = [
      "K3S_CHANNEL=${var.k3s_channel}",
      "ECR_REGISTRY=${var.ecr_registry}",
      "ECR_PASSWORD=${var.ecr_password}",
    ]
  }
}
