# =============================================================================
# CloudWatch Monitoring - RegionalBank Fraud Detection
# =============================================================================
#
# Comprehensive monitoring for:
# - EC2 instances (CPU, Memory, Disk, Network)
# - Application Load Balancer (Latency, Request Count, Errors)
# - Auto Scaling Group health
#
# Dashboard accessible via AWS Console or API
# =============================================================================

# =============================================================================
# SNS Topic for Alerts (Optional - create if you want email/SMS alerts)
# =============================================================================

resource "aws_sns_topic" "alerts" {
  name = "${var.project_name}-alerts"

  tags = {
    Name = "${var.project_name}-alerts"
  }
}

# Uncomment to add email subscription
# resource "aws_sns_topic_subscription" "email" {
#   topic_arn = aws_sns_topic.alerts.arn
#   protocol  = "email"
#   endpoint  = "your-email@example.com"
# }

# =============================================================================
# CloudWatch Dashboard
# =============================================================================

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project_name}-dashboard"

  dashboard_body = jsonencode({
    widgets = [
      # Row 1: Key Metrics Header
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 1
        properties = {
          markdown = "# RegionalBank Fraud Detection - Performance Dashboard\n**Target:** 10,000 TPS @ <50ms P99 latency | **Architecture:** 2× c6i.2xlarge + MongoDB Atlas M60 (3 shards)"
        }
      },

      # Row 2: ALB Request Metrics
      {
        type   = "metric"
        x      = 0
        y      = 1
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum", period = 60, label = "Requests/min" }]
          ]
          title  = "Request Count (per minute)"
          region = var.aws_region
          stat   = "Sum"
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0 }
          }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 1
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Average", label = "Avg" }],
            ["...", { stat = "p95", label = "P95" }],
            ["...", { stat = "p99", label = "P99" }]
          ]
          title  = "ALB Response Time (ms)"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0, max = 200 }
          }
          annotations = {
            horizontal = [
              { value = 50, label = "Target P99", color = "#2ca02c" }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 1
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_2XX_Count", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum", label = "2XX Success", color = "#2ca02c" }],
            [".", "HTTPCode_Target_4XX_Count", ".", ".", { stat = "Sum", label = "4XX Client Error", color = "#ff7f0e" }],
            [".", "HTTPCode_Target_5XX_Count", ".", ".", { stat = "Sum", label = "5XX Server Error", color = "#d62728" }]
          ]
          title  = "HTTP Response Codes"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
          stacked = false
        }
      },

      # Row 3: EC2 CPU and Memory
      {
        type   = "metric"
        x      = 0
        y      = 7
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "CPUUtilization", "AutoScalingGroupName", aws_autoscaling_group.api.name, { stat = "Average", label = "Avg CPU" }],
            ["...", { stat = "Maximum", label = "Max CPU" }]
          ]
          title  = "EC2 CPU Utilization (%)"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0, max = 100 }
          }
          annotations = {
            horizontal = [
              { value = 70, label = "Scale Up Threshold", color = "#ff7f0e" },
              { value = 30, label = "Scale Down Threshold", color = "#2ca02c" }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 7
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/EC2", "NetworkIn", "AutoScalingGroupName", aws_autoscaling_group.api.name, { stat = "Sum", label = "Network In (bytes)" }],
            [".", "NetworkOut", ".", ".", { stat = "Sum", label = "Network Out (bytes)" }]
          ]
          title  = "EC2 Network I/O"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
        }
      },

      # Row 4: ALB Health and Connections
      {
        type   = "metric"
        x      = 0
        y      = 13
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", aws_lb_target_group.api.arn_suffix, "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Average", label = "Healthy Hosts", color = "#2ca02c" }],
            [".", "UnHealthyHostCount", ".", ".", ".", ".", { stat = "Average", label = "Unhealthy Hosts", color = "#d62728" }]
          ]
          title  = "Target Group Health"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0 }
          }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 13
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "ActiveConnectionCount", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum", label = "Active Connections" }],
            [".", "NewConnectionCount", ".", ".", { stat = "Sum", label = "New Connections" }]
          ]
          title  = "ALB Connections"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 13
        width  = 8
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "RequestCountPerTarget", "TargetGroup", aws_lb_target_group.api.arn_suffix, { stat = "Sum", label = "Requests/Target" }]
          ]
          title  = "Request Distribution per Target"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
        }
      },

      # Row 5: V2 Metrics (shown regardless — widgets will be empty if V2 is disabled)
      {
        type   = "text"
        x      = 0
        y      = 19
        width  = 24
        height = 1
        properties = {
          markdown = "## V2 API Metrics (Port 8001)"
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 20
        width  = 8
        height = 6
        properties = {
          metrics = var.enable_v2 ? [
            ["AWS/ApplicationELB", "RequestCount", "TargetGroup", aws_lb_target_group.api_v2[0].arn_suffix, "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum", period = 60, label = "V2 Requests/min" }]
          ] : []
          title  = "V2 Request Count (per minute)"
          region = var.aws_region
          stat   = "Sum"
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0 }
          }
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 20
        width  = 8
        height = 6
        properties = {
          metrics = var.enable_v2 ? [
            ["AWS/ApplicationELB", "TargetResponseTime", "TargetGroup", aws_lb_target_group.api_v2[0].arn_suffix, "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Average", label = "V2 Avg" }],
            ["...", { stat = "p95", label = "V2 P95" }],
            ["...", { stat = "p99", label = "V2 P99" }]
          ] : []
          title  = "V2 Response Time (ms)"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0, max = 200 }
          }
          annotations = {
            horizontal = [
              { value = 50, label = "Target P99", color = "#2ca02c" }
            ]
          }
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 20
        width  = 8
        height = 6
        properties = {
          metrics = var.enable_v2 ? [
            ["AWS/ApplicationELB", "HealthyHostCount", "TargetGroup", aws_lb_target_group.api_v2[0].arn_suffix, "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Average", label = "V2 Healthy", color = "#2ca02c" }],
            [".", "UnHealthyHostCount", ".", ".", ".", ".", { stat = "Average", label = "V2 Unhealthy", color = "#d62728" }]
          ] : []
          title  = "V2 Target Group Health"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
          yAxis = {
            left = { min = 0 }
          }
        }
      },

      # Row 6: ASG Status
      {
        type   = "metric"
        x      = 0
        y      = 27
        width  = 12
        height = 4
        properties = {
          metrics = [
            ["AWS/AutoScaling", "GroupDesiredCapacity", "AutoScalingGroupName", aws_autoscaling_group.api.name, { stat = "Average", label = "Desired" }],
            [".", "GroupInServiceInstances", ".", ".", { stat = "Average", label = "In Service" }],
            [".", "GroupPendingInstances", ".", ".", { stat = "Average", label = "Pending" }]
          ]
          title  = "Auto Scaling Group Status"
          region = var.aws_region
          period = 60
          view   = "singleValue"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 27
        width  = 12
        height = 4
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "ProcessedBytes", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum", label = "Processed Bytes" }]
          ]
          title  = "ALB Data Processed"
          region = var.aws_region
          period = 60
          view   = "timeSeries"
        }
      }
    ]
  })
}

# =============================================================================
# CloudWatch Alarms - ALB Latency
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "alb_high_latency_p99" {
  alarm_name          = "${var.project_name}-alb-high-latency-p99"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 0.1  # 100ms in seconds
  alarm_description   = "ALB P99 latency > 100ms for 3 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-alb-high-latency-p99"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_high_latency_avg" {
  alarm_name          = "${var.project_name}-alb-high-latency-avg"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 0.05  # 50ms in seconds
  alarm_description   = "ALB average latency > 50ms for 2 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-alb-high-latency-avg"
  }
}

# =============================================================================
# CloudWatch Alarms - ALB Error Rates
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "alb_5xx_errors" {
  alarm_name          = "${var.project_name}-alb-5xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 100  # 100 5XX errors per minute
  alarm_description   = "More than 100 5XX errors per minute"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-alb-5xx-errors"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  alarm_name          = "${var.project_name}-alb-unhealthy-hosts"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 0
  alarm_description   = "One or more targets are unhealthy"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer  = aws_lb.api.arn_suffix
    TargetGroup   = aws_lb_target_group.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-alb-unhealthy-hosts"
  }
}

# =============================================================================
# CloudWatch Alarms - EC2 Memory (requires CloudWatch Agent)
# =============================================================================

# Note: Memory metrics require CloudWatch Agent installed on EC2 instances
# The agent is already included via CloudWatchAgentServerPolicy IAM role

resource "aws_cloudwatch_metric_alarm" "ec2_high_memory" {
  alarm_name          = "${var.project_name}-ec2-high-memory"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "mem_used_percent"
  namespace           = "CWAgent"
  period              = 60
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "EC2 memory usage > 85% for 3 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.api.name
  }

  tags = {
    Name = "${var.project_name}-ec2-high-memory"
  }
}

# =============================================================================
# CloudWatch Alarms - Throughput (for monitoring TPS)
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "high_throughput_achieved" {
  alarm_name          = "${var.project_name}-high-throughput"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "RequestCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 500000  # 500k requests/minute = ~8.3k TPS
  alarm_description   = "High throughput achieved (>8.3k TPS) - informational"
  alarm_actions       = []  # No action, just for visibility
  ok_actions          = []

  dimensions = {
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-high-throughput"
  }
}

# =============================================================================
# CloudWatch Log Groups
# =============================================================================

resource "aws_cloudwatch_log_group" "api" {
  name              = "/RegionalBank-fraud/api"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-api-logs"
  }
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/RegionalBank-fraud/access"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-access-logs"
  }
}

# =============================================================================
# V2 CloudWatch Resources (conditional on enable_v2)
# =============================================================================

resource "aws_cloudwatch_log_group" "api_v2" {
  count             = var.enable_v2 ? 1 : 0
  name              = "/RegionalBank-fraud/api-v2"
  retention_in_days = 7

  tags = {
    Name = "${var.project_name}-api-v2-logs"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_v2_unhealthy_hosts" {
  count               = var.enable_v2 ? 1 : 0
  alarm_name          = "${var.project_name}-v2-unhealthy-hosts"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_description   = "One or more V2 targets are unhealthy"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    TargetGroup  = aws_lb_target_group.api_v2[0].arn_suffix
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-v2-unhealthy-hosts"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_v2_high_latency_p99" {
  count               = var.enable_v2 ? 1 : 0
  alarm_name          = "${var.project_name}-v2-high-latency-p99"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  extended_statistic  = "p99"
  threshold           = 0.1
  alarm_description   = "V2 ALB P99 latency > 100ms for 3 consecutive minutes"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]

  dimensions = {
    TargetGroup  = aws_lb_target_group.api_v2[0].arn_suffix
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-v2-high-latency-p99"
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_v2_5xx_errors" {
  count               = var.enable_v2 ? 1 : 0
  alarm_name          = "${var.project_name}-v2-5xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 100
  alarm_description   = "More than 100 V2 5XX errors per minute"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  ok_actions          = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    TargetGroup  = aws_lb_target_group.api_v2[0].arn_suffix
    LoadBalancer = aws_lb.api.arn_suffix
  }

  tags = {
    Name = "${var.project_name}-v2-5xx-errors"
  }
}

# =============================================================================
# Outputs
# =============================================================================

output "cloudwatch_dashboard_url" {
  description = "URL to the CloudWatch dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}

output "sns_topic_arn" {
  description = "SNS topic ARN for alerts"
  value       = aws_sns_topic.alerts.arn
}

output "alarms_list" {
  description = "List of CloudWatch alarms created"
  value = concat(
    [
      aws_cloudwatch_metric_alarm.alb_high_latency_p99.alarm_name,
      aws_cloudwatch_metric_alarm.alb_high_latency_avg.alarm_name,
      aws_cloudwatch_metric_alarm.alb_5xx_errors.alarm_name,
      aws_cloudwatch_metric_alarm.alb_unhealthy_hosts.alarm_name,
      aws_cloudwatch_metric_alarm.ec2_high_memory.alarm_name,
      aws_cloudwatch_metric_alarm.high_throughput_achieved.alarm_name,
    ],
    var.enable_v2 ? [
      aws_cloudwatch_metric_alarm.alb_v2_unhealthy_hosts[0].alarm_name,
      aws_cloudwatch_metric_alarm.alb_v2_high_latency_p99[0].alarm_name,
      aws_cloudwatch_metric_alarm.alb_v2_5xx_errors[0].alarm_name,
    ] : []
  )
}
