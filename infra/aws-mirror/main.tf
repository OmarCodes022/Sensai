terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "eu-west-3"
}

variable "image_uri" {
  description = "Immutable ECR image URI including its sha256 digest."
  type        = string
}

variable "enable_schedule" {
  description = "Enable only after the AWS SSH key has GitHub repository access."
  type        = bool
  default     = false
}

data "aws_caller_identity" "current" {}

data "aws_ecr_repository" "mirror" {
  name = "sensai-mirror"
}

resource "aws_cloudwatch_log_group" "build" {
  name              = "/aws/codebuild/sensai-mirror-image"
  retention_in_days = 7
}

resource "aws_iam_role" "build" {
  name = "sensai-mirror-image-build"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "build" {
  role = aws_iam_role.build.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage"
        ]
        Resource = data.aws_ecr_repository.mirror.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.build.arn}:*"
      }
    ]
  })
}

resource "aws_codebuild_project" "image" {
  name         = "sensai-mirror-image"
  service_role = aws_iam_role.build.arn

  artifacts {
    type = "NO_ARTIFACTS"
  }

  source {
    type      = "NO_SOURCE"
    buildspec = <<-YAML
      version: 0.2
      phases:
        install:
          commands:
            - git clone --quiet https://github.com/OmarCodes022/Sensai.git /tmp/sensai
            - git -C /tmp/sensai checkout --quiet "$SOURCE_COMMIT"
        build:
          commands:
            - docker build --platform linux/amd64 -t "$REPOSITORY_URI:$SOURCE_COMMIT" /tmp/sensai/infra/aws-mirror
        post_build:
          commands:
            - aws ecr get-login-password | docker login --username AWS --password-stdin "$ECR_REGISTRY"
            - docker push "$REPOSITORY_URI:$SOURCE_COMMIT"
      YAML
  }

  environment {
    compute_type                = "BUILD_GENERAL1_SMALL"
    image                       = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
    type                        = "LINUX_CONTAINER"
    privileged_mode             = true
    image_pull_credentials_type = "CODEBUILD"

    environment_variable {
      name  = "REPOSITORY_URI"
      value = data.aws_ecr_repository.mirror.repository_url
    }

    environment_variable {
      name  = "ECR_REGISTRY"
      value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.eu-west-3.amazonaws.com"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.build.name
    }
  }

  depends_on = [aws_iam_role_policy.build]
}

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_ssm_parameter" "tested_sha" {
  name  = "/sensai/mirror/last-tested-sha"
  type  = "String"
  value = "awaiting-first-successful-ci-run"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_iam_role" "ci" {
  name = "sensai-personal-main-ci"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "repo:OmarCodes022/Sensai:ref:refs/heads/main"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci" {
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ssm:PutParameter"
      Resource = aws_ssm_parameter.tested_sha.arn
    }]
  })
}

resource "aws_secretsmanager_secret" "ssh" {
  name                    = "sensai/mirror/epitech-ssh"
  recovery_window_in_days = 30
}

resource "aws_iam_role" "lambda" {
  name = "sensai-main-mirror-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = aws_ssm_parameter.tested_sha.arn
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.ssh.arn
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/sensai-main-mirror"
  retention_in_days = 14
}

resource "aws_lambda_function" "mirror" {
  function_name = "sensai-main-mirror"
  package_type  = "Image"
  image_uri     = var.image_uri
  role          = aws_iam_role.lambda.arn
  timeout       = 55
  memory_size   = 256

  ephemeral_storage {
    size = 1024
  }

  environment {
    variables = {
      SSH_SECRET_ARN = aws_secretsmanager_secret.ssh.arn
    }
  }

  depends_on = [aws_iam_role_policy.lambda]
}

resource "aws_cloudwatch_event_rule" "minute" {
  name                = "sensai-main-mirror-minute"
  schedule_expression = "rate(1 minute)"
  state               = var.enable_schedule ? "ENABLED" : "DISABLED"
}

resource "aws_cloudwatch_event_target" "mirror" {
  rule = aws_cloudwatch_event_rule.minute.name
  arn  = aws_lambda_function.mirror.arn
}

resource "aws_lambda_permission" "schedule" {
  statement_id  = "AllowScheduledMirror"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.mirror.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.minute.arn
}

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "sensai-main-mirror-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  dimensions = {
    FunctionName = aws_lambda_function.mirror.function_name
  }
}

output "ci_role_arn" {
  value = aws_iam_role.ci.arn
}

output "ssh_secret_arn" {
  value = aws_secretsmanager_secret.ssh.arn
}
