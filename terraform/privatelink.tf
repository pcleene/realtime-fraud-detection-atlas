# =============================================================================
# MongoDB Atlas PrivateLink Configuration
# =============================================================================
#
# This creates a secure private connection between AWS VPC and MongoDB Atlas.
# Traffic never traverses the public internet, reducing latency and improving security.
#
# Prerequisites:
#   1. MongoDB Atlas cluster must be M10 or higher
#   2. Atlas project must have PrivateLink enabled
#   3. You need Atlas API keys with Project Owner permissions
# =============================================================================

# =============================================================================
# Atlas PrivateLink Endpoint Service
# =============================================================================

# Get the Atlas PrivateLink endpoint service
resource "mongodbatlas_privatelink_endpoint" "main" {
  project_id    = var.mongodb_atlas_project_id
  provider_name = "AWS"
  region        = var.aws_region
}

# =============================================================================
# AWS VPC Endpoint
# =============================================================================

resource "aws_vpc_endpoint" "mongodb" {
  vpc_id              = aws_vpc.main.id
  service_name        = mongodbatlas_privatelink_endpoint.main.endpoint_service_name
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.mongodb.id]
  private_dns_enabled = false # Atlas manages DNS

  tags = {
    Name = "${var.project_name}-mongodb-endpoint"
  }
}

# =============================================================================
# Atlas PrivateLink Endpoint Service Connection
# =============================================================================

# Connect AWS VPC Endpoint to Atlas
resource "mongodbatlas_privatelink_endpoint_service" "main" {
  project_id          = var.mongodb_atlas_project_id
  private_link_id     = mongodbatlas_privatelink_endpoint.main.private_link_id
  endpoint_service_id = aws_vpc_endpoint.mongodb.id
  provider_name       = "AWS"
}

# =============================================================================
# Route 53 Private Hosted Zone (for Atlas DNS resolution)
# =============================================================================

# Atlas provides specific DNS names for PrivateLink connections
# These need to resolve to the VPC endpoint IPs

resource "aws_route53_zone" "mongodb" {
  name = "mongodb.net"

  vpc {
    vpc_id = aws_vpc.main.id
  }

  tags = {
    Name = "${var.project_name}-mongodb-zone"
  }
}

# Create DNS records for each Atlas node
# Note: Atlas cluster endpoints follow pattern: *.mongodb.net
resource "aws_route53_record" "mongodb" {
  zone_id = aws_route53_zone.mongodb.zone_id
  name    = "*.mongodb.net"
  type    = "A"

  alias {
    name                   = aws_vpc_endpoint.mongodb.dns_entry[0]["dns_name"]
    zone_id                = aws_vpc_endpoint.mongodb.dns_entry[0]["hosted_zone_id"]
    evaluate_target_health = true
  }
}

# =============================================================================
# Outputs for PrivateLink
# =============================================================================

output "privatelink_status" {
  description = "Status of the MongoDB Atlas PrivateLink connection"
  value       = mongodbatlas_privatelink_endpoint_service.main.status
}

output "privatelink_endpoint_id" {
  description = "AWS VPC Endpoint ID for MongoDB"
  value       = aws_vpc_endpoint.mongodb.id
}

output "mongodb_connection_string_privatelink" {
  description = "Connection string for MongoDB via PrivateLink"
  value       = "Use your Atlas connection string with the private endpoint suffix"
  sensitive   = true
}
