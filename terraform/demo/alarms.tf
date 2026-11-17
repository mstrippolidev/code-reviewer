locals {
  promql_alarms = {
    daily-spend = {
      description    = "LLM spend over 10 USD in the last 24 hours."
      query          = "sum(increase(code_reviewer_llm_cost_USD_total[24h])) > 10"
      pending_period = 300
    }
    expensive-review = {
      description    = "A finished review cost more than 5 USD in the last hour."
      query          = "(sum(code_reviewer_review_cost_USD_count) - sum(code_reviewer_review_cost_USD_bucket{le=\"5.0\"})) - ((sum(code_reviewer_review_cost_USD_count offset 1h) - sum(code_reviewer_review_cost_USD_bucket{le=\"5.0\"} offset 1h)) or vector(0)) > 0"
      pending_period = null
    }
    intake-prompt-injection = {
      description    = "The intake rejected a file as prompt injection in the last hour."
      query          = "sum(code_reviewer_intake_rejections_total{code_reviewer_validator=\"prompt_injection\"}) - (sum(code_reviewer_intake_rejections_total{code_reviewer_validator=\"prompt_injection\"} offset 1h) or vector(0)) > 0"
      pending_period = null
    }
    llm-error-rate = {
      description    = "More than 20 percent of the calls to one model failed over 5 minutes."
      query          = "(sum by (code_reviewer_model) (increase(code_reviewer_llm_call_errors_total[5m])) / sum by (code_reviewer_model) (increase(code_reviewer_llm_call_duration_seconds_count[5m])) > 0.2) and on (code_reviewer_model) (sum by (code_reviewer_model) (increase(code_reviewer_llm_call_duration_seconds_count[5m])) >= 5)"
      pending_period = 300
    }
    llm-stalled = {
      description    = "Model calls are in flight but none has finished in 5 minutes."
      query          = "(sum(code_reviewer_llm_calls_in_flight) > 0) and ((sum(increase(code_reviewer_llm_call_duration_seconds_count[5m])) or vector(0)) == 0)"
      pending_period = 300
    }
    llm-unpriced = {
      description    = "A model call had no known price, so reported cost is a lower bound."
      query          = "sum(code_reviewer_llm_unpriced_calls_total) - (sum(code_reviewer_llm_unpriced_calls_total offset 15m) or vector(0)) > 0"
      pending_period = null
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "promql" {
  for_each = local.promql_alarms

  alarm_name        = "${var.name}-${each.key}"
  alarm_description = each.value.description
  alarm_actions     = var.alarm_sns_topic_arns

  evaluation_interval = 60

  evaluation_criteria {
    promql_criteria {
      query           = each.value.query
      pending_period  = each.value.pending_period
      recovery_period = 300
    }
  }
}
