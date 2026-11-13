# The cost alarm (set up first, on Oct 31): $10 a month; emails at 85% and 100% of actual
# spend and when the forecast passes 100%. Credits and refunds are not counted.
resource "aws_budgets_budget" "monthly" {
  name              = "My Monthly Cost Budget"
  account_id        = data.aws_caller_identity.current.account_id
  billing_view_arn  = "arn:aws:billing::${data.aws_caller_identity.current.account_id}:billingview/primary"
  budget_type       = "COST"
  limit_amount      = "10.0"
  limit_unit        = "USD"
  time_unit         = "MONTHLY"
  time_period_start = "2026-10-01_00:00"
  time_period_end   = "2087-06-15_00:00"
  metrics           = ["UnblendedCost"]

  filter_expression {
    not {
      dimensions {
        key    = "RECORD_TYPE"
        values = ["Credit", "Refund"]
      }
    }
  }

  dynamic "notification" {
    for_each = [
      { type = "ACTUAL", threshold = 85 },
      { type = "ACTUAL", threshold = 100 },
      { type = "FORECASTED", threshold = 100 },
    ]
    content {
      comparison_operator        = "GREATER_THAN"
      notification_type          = notification.value.type
      threshold                  = notification.value.threshold
      threshold_type             = "PERCENTAGE"
      subscriber_email_addresses = var.budget_alert_emails
    }
  }
}
