resource "aws_ecr_repository" "code-reviewer" {
  for_each             = toset(var.ecr_repositories)
  name                 = each.key
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
}

# delete older images beyond the cap of var.ecr_images_to_keep
resource "aws_ecr_lifecycle_policy" "code-reviewer" {
  for_each   = aws_ecr_repository.code-reviewer
  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire older images beyond the cap of ${var.ecr_images_to_keep}"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.ecr_images_to_keep
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}