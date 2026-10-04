data "aws_iam_policy_document" "instance_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "instance_permissions" {
  statement {
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      for model_id in var.bedrock_model_ids :
      "arn:aws:bedrock:${var.region}::foundation-model/${model_id}"
    ]
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${local.state_bucket_name}/runtime/*"]
  }

  statement {
    actions   = ["sns:Publish"]
    resources = [var.dlq_sns_topic_arn]
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name}-instance"
  assume_role_policy = data.aws_iam_policy_document.instance_assume.json
}

resource "aws_iam_role_policy" "instance" {
  name   = "demo-runtime"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.instance_permissions.json
}

resource "aws_iam_role_policy_attachment" "instance_ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name}-instance"
  role = aws_iam_role.instance.name
}
