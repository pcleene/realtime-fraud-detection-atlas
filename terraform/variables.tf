# =============================================================================
# RegionalBank Fraud Detection - Terraform Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region for deployment"
  type        = string
  default     = "ap-southeast-1" # Singapore - closest to Indonesia
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "RegionalBank-fraud"
}

# =============================================================================
# MongoDB Atlas Configuration
# =============================================================================

variable "mongodb_atlas_public_key" {
  description = "MongoDB Atlas API public key"
  type        = string
  sensitive   = true
}

variable "mongodb_atlas_private_key" {
  description = "MongoDB Atlas API private key"
  type        = string
  sensitive   = true
}

variable "mongodb_atlas_project_id" {
  description = "MongoDB Atlas project ID"
  type        = string
}

variable "mongodb_atlas_cluster_name" {
  description = "MongoDB Atlas cluster name"
  type        = string
  default     = "RegionalBank-fraud-cluster"
}

variable "mongodb_connection_string" {
  description = "MongoDB connection string (will use PrivateLink endpoint)"
  type        = string
  sensitive   = true
}

# =============================================================================
# EC2 Configuration
# =============================================================================

variable "instance_type" {
  description = "EC2 instance type for API servers"
  type        = string
  default     = "c6i.2xlarge" # 8 vCPU, 16GB - good for 6-8K TPS
}

variable "api_instance_count" {
  description = "Number of API EC2 instances"
  type        = number
  default     = 2
}

variable "api_workers_per_instance" {
  description = "Gunicorn workers per instance (2 * vCPU recommended)"
  type        = number
  default     = 16 # For c6i.2xlarge
}

variable "key_pair_name" {
  description = "EC2 key pair name for SSH access"
  type        = string
}

# =============================================================================
# Network Configuration
# =============================================================================

variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "<private-ip>/16"
}

variable "availability_zones" {
  description = "Availability zones for deployment"
  type        = list(string)
  default     = ["ap-southeast-1a", "ap-southeast-1b"]
}

# =============================================================================
# Application Configuration
# =============================================================================

variable "api_port" {
  description = "Port for the API service"
  type        = number
  default     = 8000
}

variable "frontend_port" {
  description = "Port for the frontend service"
  type        = number
  default     = 3000
}

variable "docker_image_tag" {
  description = "Docker image tag to deploy"
  type        = string
  default     = "latest"
}

variable "locust_host" {
  description = "Private IP of the bastion host running Locust"
  type        = string
  default     = "<private-ip>"
}

# =============================================================================
# V2 Configuration
# =============================================================================

variable "enable_v2" {
  description = "Whether to deploy V2 alongside V1"
  type        = bool
  default     = true
}

variable "docker_image_tag_v2" {
  description = "Docker image tag for V2 API"
  type        = string
  default     = "latest"
}

variable "api_port_v2" {
  description = "Port for the V2 API service"
  type        = number
  default     = 8001
}

# =============================================================================
# Auto Scaling Configuration
# =============================================================================

variable "min_instances" {
  description = "Minimum number of API instances"
  type        = number
  default     = 2
}

variable "max_instances" {
  description = "Maximum number of API instances"
  type        = number
  default     = 6
}

variable "scale_up_cpu_threshold" {
  description = "CPU percentage to trigger scale up"
  type        = number
  default     = 70
}

variable "scale_down_cpu_threshold" {
  description = "CPU percentage to trigger scale down"
  type        = number
  default     = 30
}

# =============================================================================
# Tags
# =============================================================================

variable "tags" {
  description = "Common tags for all resources"
  type        = map(string)
  default = {
    Project     = "RegionalBank-fraud-detection"
    ManagedBy   = "terraform"
    Environment = "prod"
  }
}
