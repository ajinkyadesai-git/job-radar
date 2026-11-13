# The API on AWS Lambda: the same container image as on the laptop, on ARM (Graviton) to
# match the Mac and cost about 20% less. A function URL gives it a public HTTPS address;
# the app itself checks the X-API-Key on every endpoint except /health.

locals {
  ssm_prefix = "/job-radar/prod/"
}

resource "aws_iam_role" "api" {
  name = "job-radar-api-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Logs to CloudWatch.
resource "aws_iam_role_policy_attachment" "api_logs" {
  role       = aws_iam_role.api.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Read its own secrets, and nothing else: parameters under /job-radar/prod/ only.
resource "aws_iam_role_policy" "api_secrets" {
  name = "read-job-radar-prod-parameters"
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ssm:GetParametersByPath"]
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${trimsuffix(local.ssm_prefix, "/")}",
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}*",
        ]
      },
      {
        Effect    = "Allow"
        Action    = ["kms:Decrypt"]
        Resource  = "*"
        Condition = { StringEquals = { "kms:ViaService" = "ssm.${var.region}.amazonaws.com" } }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/job-radar-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name = "job-radar-api"
  role          = aws_iam_role.api.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
  architectures = ["arm64"]
  memory_size   = 1024
  timeout       = 60

  environment {
    variables = {
      JOBRADAR_SSM_PREFIX = local.ssm_prefix
      JOBRADAR_API_ENV    = "prod"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy_attachment.api_logs]

  # After the first deploy, GitHub (T31) ships new images; Terraform must not roll them back.
  lifecycle {
    ignore_changes = [image_uri]
  }
}

resource "aws_lambda_function_url" "api" {
  function_name      = aws_lambda_function.api.function_name
  authorization_type = "NONE" # the app checks X-API-Key itself

  cors {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST"]
    allow_headers = ["content-type", "x-api-key"]
    max_age       = 3600
  }
}

# Lets anyone reach the URL (the Console adds this automatically; Terraform does not).
# Access to data is still decided by the app's X-API-Key check.
resource "aws_lambda_permission" "public_url" {
  statement_id           = "AllowPublicFunctionUrl"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.api.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
