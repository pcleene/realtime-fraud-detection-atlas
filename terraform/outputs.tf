# =============================================================================
# Terraform Outputs
# =============================================================================

output "alb_dns_name" {
  description = "DNS name of the Application Load Balancer"
  value       = aws_lb.api.dns_name
}

output "alb_zone_id" {
  description = "Zone ID of the Application Load Balancer"
  value       = aws_lb.api.zone_id
}

output "api_url" {
  description = "URL to access the API"
  value       = "http://${aws_lb.api.dns_name}"
}

output "api_docs_url" {
  description = "URL to access the API documentation"
  value       = "http://${aws_lb.api.dns_name}/docs"
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = aws_subnet.public[*].id
}

output "api_security_group_id" {
  description = "Security group ID for API instances"
  value       = aws_security_group.api.id
}

output "autoscaling_group_name" {
  description = "Name of the Auto Scaling Group"
  value       = aws_autoscaling_group.api.name
}

output "launch_template_id" {
  description = "ID of the EC2 launch template"
  value       = aws_launch_template.api.id
}

# =============================================================================
# V2 Outputs (conditional on enable_v2)
# =============================================================================

output "api_v2_target_group_arn" {
  description = "V2 API Target Group ARN"
  value       = var.enable_v2 ? aws_lb_target_group.api_v2[0].arn : null
}

output "api_v2_url" {
  description = "V2 API URL"
  value       = var.enable_v2 ? "http://${aws_lb.api.dns_name}:${var.api_port_v2}" : null
}

# =============================================================================
# Connection Information
# =============================================================================

output "connection_info" {
  description = "How to connect and test"
  value       = <<-EOT

    ============================================
    RegionalBank Fraud Detection - Deployment Complete
    ============================================

    V1 API URL: http://${aws_lb.api.dns_name}
    V1 API Docs: http://${aws_lb.api.dns_name}/docs
    V1 Health Check: http://${aws_lb.api.dns_name}/api/health
%{if var.enable_v2}
    V2 API URL: http://${aws_lb.api.dns_name}:${var.api_port_v2}
    V2 API Docs: http://${aws_lb.api.dns_name}:${var.api_port_v2}/docs
    V2 Health Check: http://${aws_lb.api.dns_name}:${var.api_port_v2}/api/health
%{endif}
    ============================================
    Load Testing
    ============================================

    V1: python scripts/loadtest_distributed.py \
        --url http://${aws_lb.api.dns_name} \
        --tps 5000 --duration 60
%{if var.enable_v2}
    V2: python scripts/loadtest_distributed.py \
        --url http://${aws_lb.api.dns_name}:${var.api_port_v2} \
        --tps 5000 --duration 60
%{endif}
    ============================================
    Scaling
    ============================================

    Current instances: ${var.api_instance_count}
    Min instances: ${var.min_instances}
    Max instances: ${var.max_instances}

    Manual scale:
    aws autoscaling set-desired-capacity \
        --auto-scaling-group-name ${aws_autoscaling_group.api.name} \
        --desired-capacity 4

    ============================================
    Monitoring
    ============================================

    CloudWatch Logs (V1):
    aws logs tail /RegionalBank-fraud/api --follow
%{if var.enable_v2}
    CloudWatch Logs (V2):
    aws logs tail /RegionalBank-fraud/api-v2 --follow
%{endif}
    EC2 Instances:
    aws ec2 describe-instances \
        --filters "Name=tag:Name,Values=${var.project_name}-api" \
        --query 'Reservations[*].Instances[*].[InstanceId,State.Name,PrivateIpAddress]'

  EOT
}
