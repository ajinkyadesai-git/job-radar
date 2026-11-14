# Alerts (T32): one email topic, a daily watchdog, and alarms if a function keeps failing.

resource "aws_sns_topic" "alerts" {
  name = "job-radar-alerts"
}

# You get an email from AWS asking you to confirm this subscription; click the link once.
resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- The watchdog: same container image as the API, no public URL ---------------------

resource "aws_iam_role" "watchdog" {
  name = "job-radar-watchdog-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "watchdog_logs" {
  role       = aws_iam_role.watchdog.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Read the run logs and its own secrets; email the alerts topic. Nothing else.
resource "aws_iam_role_policy" "watchdog" {
  name = "read-run-logs-and-alert"
  role = aws_iam_role.watchdog.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.raw.arn
        Condition = { StringLike = { "s3:prefix" = ["prod/ops/*"] } }
      },
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.raw.arn}/prod/ops/*"
      },
      {
        Effect = "Allow"
        Action = "ssm:GetParametersByPath"
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${trimsuffix(local.ssm_prefix, "/")}",
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}*",
        ]
      },
      {
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = "*"
        Condition = { StringEquals = { "kms:ViaService" = "ssm.${var.region}.amazonaws.com" } }
      },
      {
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "watchdog" {
  name              = "/aws/lambda/job-radar-watchdog"
  retention_in_days = 14
}

resource "aws_lambda_function" "watchdog" {
  function_name = "job-radar-watchdog"
  role          = aws_iam_role.watchdog.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
  architectures = ["arm64"]
  memory_size   = 512
  timeout       = 120

  environment {
    variables = {
      JOBRADAR_WATCHDOG         = "1"
      AWS_LWA_PASS_THROUGH_PATH = "/events"
      JOBRADAR_SSM_PREFIX       = local.ssm_prefix
      JOBRADAR_API_ENV          = "prod"
      JOBRADAR_S3_BUCKET        = aws_s3_bucket.raw.bucket
      JOBRADAR_S3_PREFIX        = "prod"
      JOBRADAR_ALERT_TOPIC_ARN  = aws_sns_topic.alerts.arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.watchdog, aws_iam_role_policy_attachment.watchdog_logs]

  lifecycle {
    ignore_changes = [image_uri] # GitHub deploys keep it on the same image as the API
  }
}

# Every day at 18:47 UTC (10:47 PST / 11:47 PDT), about 4.5 hours after the daily run.
resource "aws_cloudwatch_event_rule" "watchdog_daily" {
  name                = "job-radar-watchdog-daily"
  schedule_expression = "cron(47 18 * * ? *)"
}

resource "aws_cloudwatch_event_target" "watchdog_daily" {
  rule = aws_cloudwatch_event_rule.watchdog_daily.name
  arn  = aws_lambda_function.watchdog.arn
}

resource "aws_lambda_permission" "watchdog_schedule" {
  statement_id  = "AllowDailySchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watchdog.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.watchdog_daily.arn
}

# --- Alarms: email if a function errors (the watchdog failing silently would be worst) --

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = {
    watchdog = { function = aws_lambda_function.watchdog.function_name, threshold = 1 }
    api      = { function = aws_lambda_function.api.function_name, threshold = 5 }
  }

  alarm_name          = "job-radar-${each.key}-errors"
  alarm_description   = "${each.value.function} returned errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value.function }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
