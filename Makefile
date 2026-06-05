.PHONY: help install dev test seed clean docker-up docker-down docker-logs atlas-setup verify tf-init tf-plan tf-apply tf-destroy
.PHONY: install-v2 dev-v2 test-v2 dev-both atlas-setup-v2 seed-v2-test seed-v2 seed-v2-medium seed-v2-full seed-v2-reset

# Default target
help:
	@echo "RegionalBank Fraud Detection POC - Available Commands"
	@echo "================================================"
	@echo ""
	@echo "Development (Local) - V1:"
	@echo "  make install        - Install V1 dependencies"
	@echo "  make dev            - Run V1 API (:8000) and frontend (:3000)"
	@echo "  make dev-workers    - Run V1 API with 4 Gunicorn workers"
	@echo "  make test           - Run V1 tests"
	@echo ""
	@echo "Development (Local) - V2:"
	@echo "  make install-v2     - Install V2 dependencies"
	@echo "  make dev-v2         - Run V2 API on port 8001"
	@echo "  make test-v2        - Run V2 tests"
	@echo "  make dev-both       - Run V1 (:8000) + V2 (:8001) + frontend (:3000)"
	@echo ""
	@echo "Atlas Setup & Seeding - V1:"
	@echo "  make atlas-setup    - Run V1 Atlas setup script"
	@echo "  make verify         - Verify V1 sharding"
	@echo "  make seed-test      - V1 quick test seed"
	@echo "  make seed           - V1 seed (10k customers)"
	@echo "  make seed-medium    - V1 medium seed (100k customers)"
	@echo "  make seed-reset     - V1 drop + recreate"
	@echo ""
	@echo "Atlas Setup & Seeding - V2:"
	@echo "  make atlas-setup-v2 - Run V2 Atlas setup (RegionalBank_fraud_v2 DB)"
	@echo "  make seed-v2-test   - V2 quick test seed (5 customers)"
	@echo "  make seed-v2        - V2 seed (10k customers)"
	@echo "  make seed-v2-medium - V2 medium seed (100k customers)"
	@echo "  make seed-v2-full   - V2 full seed (40M customers, 100M transactions)"
	@echo "  make seed-v2-reset  - V2 drop + recreate"
	@echo ""
	@echo "Load Testing:"
	@echo "  Use the UI at http://localhost:3000 for embedded load tests"
	@echo "  For 10K+ TPS: Use Locust on bastion host (see docs/LOCUST-SETUP.md)"
	@echo ""
	@echo "Docker (Local/Single EC2):"
	@echo "  make docker-up      - Start API + Frontend containers"
	@echo "  make docker-down    - Stop all containers"
	@echo "  make docker-logs    - View container logs"
	@echo "  make docker-build   - Build Docker images"
	@echo ""
	@echo "AWS Deployment (Terraform):"
	@echo "  make tf-init        - Initialize Terraform"
	@echo "  make tf-plan        - Preview infrastructure changes"
	@echo "  make tf-apply       - Deploy to AWS (EC2 + ALB + PrivateLink)"
	@echo "  make tf-destroy     - Tear down AWS infrastructure"
	@echo "  make tf-scale N=4   - Scale API instances"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean          - Remove generated files and caches"

# ============================================
# Development (Local)
# ============================================

install:
	@echo "Installing backend dependencies..."
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "Copying environment file..."
	cp backend/.env.example backend/.env
	@echo ""
	@echo "Installation complete!"
	@echo "Next: Update backend/.env with your Atlas connection string"

dev:
	@echo "Starting development servers..."
	@echo "API: http://localhost:8000"
	@echo "Frontend: http://localhost:3000"
	@trap 'kill 0' INT; \
	(cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000) & \
	(cd frontend && npm run dev) & \
	wait

dev-workers:
	@echo "Starting API with Gunicorn workers (production-like)..."
	@echo "API: http://localhost:8000 (4 workers)"
	@echo "Frontend: http://localhost:3000"
	@trap 'kill 0' INT; \
	(cd backend && . .venv/bin/activate && pip install -q gunicorn && WORKERS=4 gunicorn -c gunicorn.conf.py app.main:app) & \
	(cd frontend && npm run dev) & \
	wait

test:
	@echo "Running tests..."
	cd backend && . .venv/bin/activate && pytest -v

# ============================================
# Atlas Setup
# ============================================

atlas-setup:
	@echo "Running Atlas setup script..."
	@echo "This will create indexes and configure sharding on your Atlas cluster."
	@echo ""
	@echo "Usage: mongosh \"mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>" < scripts/atlas-setup.js"
	@echo ""
	@read -p "Enter your Atlas connection string: " ATLAS_URI && \
	mongosh "$$ATLAS_URI" < scripts/atlas-setup.js

verify:
	@echo "Verifying Atlas sharding configuration..."
	@echo ""
	@echo "Usage: mongosh \"mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>" < scripts/verify-sharding.js"
	@echo ""
	@read -p "Enter your Atlas connection string: " ATLAS_URI && \
	mongosh "$$ATLAS_URI" < scripts/verify-sharding.js

seed-test:
	@echo "Quick test seed (5 customers, 20 transactions - schema validation)..."
	cd backend && . .venv/bin/activate && python -m seed.main --test

seed:
	@echo "Seeding database with test data (10k customers, 50k transactions)..."
	cd backend && . .venv/bin/activate && \
		SEED_CUSTOMERS=10000 SEED_TRANSACTIONS=50000 python -m seed.main

seed-medium:
	@echo "Seeding database with medium data (100k customers, 500k transactions)..."
	cd backend && . .venv/bin/activate && \
		SEED_CUSTOMERS=100000 SEED_TRANSACTIONS=500000 python -m seed.main

seed-full:
	@echo "Seeding database with full data (50M customers, 100M transactions)..."
	@echo "WARNING: This will take 12-15 hours!"
	cd backend && . .venv/bin/activate && python -m seed.main

seed-reset:
	@echo "Resetting all collections (drop + recreate indexes)..."
	cd backend && . .venv/bin/activate && python -m seed.reset_collections

seed-reset-force:
	@echo "Force resetting all collections (no confirmation)..."
	cd backend && . .venv/bin/activate && python -m seed.reset_collections --force

seed-reset-dry:
	@echo "Dry run - showing what would be reset..."
	cd backend && . .venv/bin/activate && python -m seed.reset_collections --dry-run

# ============================================
# Docker Deployment (Single Instance)
# ============================================

docker-build:
	@echo "Building Docker images..."
	docker-compose build

docker-up:
	@echo "Starting API + Frontend containers..."
	@echo "Make sure MONGODB_URI is set in your environment or .env file"
	docker-compose up -d
	@echo ""
	@echo "Services starting:"
	@echo "  - API: http://localhost:8000"
	@echo "  - Frontend: http://localhost:3000"
	@echo ""
	@echo "Run 'make docker-logs' to view logs"

docker-down:
	@echo "Stopping all containers..."
	docker-compose down

docker-logs:
	docker-compose logs -f

docker-logs-api:
	docker-compose logs -f api

docker-logs-frontend:
	docker-compose logs -f frontend

docker-restart:
	docker-compose restart

# Seed from within Docker container
docker-seed:
	@echo "Seeding database from Docker container..."
	docker-compose exec api sh -c "SEED_CUSTOMERS=10000 SEED_TRANSACTIONS=50000 python -m seed.main"

# ============================================
# AWS Deployment (Terraform)
# ============================================

tf-init:
	@echo "Initializing Terraform..."
	cd terraform && terraform init

tf-plan:
	@echo "Planning infrastructure changes..."
	@if [ ! -f terraform/prod.tfvars ]; then \
		echo "Error: terraform/prod.tfvars not found"; \
		echo "Copy terraform/prod.tfvars.example to terraform/prod.tfvars and fill in your values"; \
		exit 1; \
	fi
	cd terraform && terraform plan -var-file="prod.tfvars"

tf-apply:
	@echo "Deploying to AWS..."
	@if [ ! -f terraform/prod.tfvars ]; then \
		echo "Error: terraform/prod.tfvars not found"; \
		exit 1; \
	fi
	cd terraform && terraform apply -var-file="prod.tfvars"

tf-destroy:
	@echo "WARNING: This will destroy all AWS infrastructure!"
	@read -p "Are you sure? (yes/no): " confirm && [ "$$confirm" = "yes" ]
	cd terraform && terraform destroy -var-file="prod.tfvars"

tf-output:
	@echo "Terraform outputs:"
	cd terraform && terraform output

tf-scale:
	@echo "Scaling API instances to $(N)..."
	aws autoscaling set-desired-capacity \
		--auto-scaling-group-name RegionalBank-fraud-api-asg \
		--desired-capacity $(N)
	@echo "Scaling initiated. Check AWS console for progress."

tf-status:
	@echo "AWS Infrastructure Status:"
	@echo ""
	@echo "EC2 Instances:"
	@aws ec2 describe-instances \
		--filters "Name=tag:Name,Values=RegionalBank-fraud-api" "Name=instance-state-name,Values=running" \
		--query 'Reservations[*].Instances[*].[InstanceId,InstanceType,PrivateIpAddress,State.Name]' \
		--output table 2>/dev/null || echo "  (No instances or AWS CLI not configured)"
	@echo ""
	@echo "Auto Scaling Group:"
	@aws autoscaling describe-auto-scaling-groups \
		--auto-scaling-group-names RegionalBank-fraud-api-asg \
		--query 'AutoScalingGroups[*].[AutoScalingGroupName,DesiredCapacity,MinSize,MaxSize]' \
		--output table 2>/dev/null || echo "  (Not found or AWS CLI not configured)"

# Complete teardown with verification
tf-teardown:
	@echo "============================================"
	@echo "AWS COMPLETE TEARDOWN"
	@echo "============================================"
	@echo ""
	@echo "This will destroy ALL AWS resources:"
	@echo "  - EC2 instances (Auto Scaling Group)"
	@echo "  - Application Load Balancer"
	@echo "  - VPC Endpoints (PrivateLink)"
	@echo "  - NAT Gateway"
	@echo "  - VPC and all subnets"
	@echo "  - Security Groups"
	@echo "  - IAM Roles"
	@echo ""
	@read -p "Type 'DESTROY' to confirm: " confirm && [ "$$confirm" = "DESTROY" ]
	@echo ""
	@echo "Starting teardown..."
	cd terraform && terraform destroy -var-file="prod.tfvars" -auto-approve
	@echo ""
	@echo "Verifying teardown..."
	@$(MAKE) tf-verify-teardown

tf-verify-teardown:
	@echo ""
	@echo "============================================"
	@echo "VERIFYING TEARDOWN"
	@echo "============================================"
	@echo ""
	@echo "Checking for remaining resources..."
	@echo ""
	@echo "1. EC2 Instances:"
	@aws ec2 describe-instances \
		--filters "Name=tag:Project,Values=RegionalBank-fraud-detection" "Name=instance-state-name,Values=running,pending,stopping" \
		--query 'Reservations[*].Instances[*].InstanceId' \
		--output text 2>/dev/null | grep -q . && echo "   WARNING: Instances still exist!" || echo "   ✓ No instances found"
	@echo ""
	@echo "2. Load Balancers:"
	@aws elbv2 describe-load-balancers \
		--query "LoadBalancers[?contains(LoadBalancerName, 'RegionalBank-fraud')].LoadBalancerArn" \
		--output text 2>/dev/null | grep -q . && echo "   WARNING: ALB still exists!" || echo "   ✓ No ALBs found"
	@echo ""
	@echo "3. VPC Endpoints:"
	@aws ec2 describe-vpc-endpoints \
		--filters "Name=tag:Name,Values=*RegionalBank-fraud*" \
		--query 'VpcEndpoints[*].VpcEndpointId' \
		--output text 2>/dev/null | grep -q . && echo "   WARNING: VPC Endpoints still exist!" || echo "   ✓ No VPC Endpoints found"
	@echo ""
	@echo "4. NAT Gateways:"
	@aws ec2 describe-nat-gateways \
		--filter "Name=tag:Name,Values=*RegionalBank-fraud*" "Name=state,Values=available,pending" \
		--query 'NatGateways[*].NatGatewayId' \
		--output text 2>/dev/null | grep -q . && echo "   WARNING: NAT Gateway still exists!" || echo "   ✓ No NAT Gateways found"
	@echo ""
	@echo "5. VPCs:"
	@aws ec2 describe-vpcs \
		--filters "Name=tag:Name,Values=*RegionalBank-fraud*" \
		--query 'Vpcs[*].VpcId' \
		--output text 2>/dev/null | grep -q . && echo "   WARNING: VPC still exists!" || echo "   ✓ No VPCs found"
	@echo ""
	@echo "============================================"
	@echo "Teardown verification complete!"
	@echo "============================================"

# ============================================
# Development (Local) - V2
# ============================================

install-v2:
	@echo "Installing V2 backend dependencies..."
	cd backend_v2 && python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
	@echo ""
	@echo "V2 installation complete!"
	@echo "Next: Update backend_v2/.env with your Atlas connection string (DB_NAME=RegionalBank_fraud_v2)"

dev-v2:
	@echo "Starting V2 API server..."
	@echo "V2 API: http://localhost:8001"
	cd backend_v2 && . .venv/bin/activate && uvicorn app.main:app --reload --port 8001

test-v2:
	@echo "Running V2 tests..."
	cd backend_v2 && . .venv/bin/activate && pytest -v

dev-both:
	@echo "Starting V1 + V2 + Frontend..."
	@echo "V1 API: http://localhost:8000"
	@echo "V2 API: http://localhost:8001"
	@echo "Frontend: http://localhost:3000"
	@trap 'kill 0' INT; \
	(cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000) & \
	(cd backend_v2 && . .venv/bin/activate && uvicorn app.main:app --reload --port 8001) & \
	(cd frontend && npm run dev) & \
	wait

# ============================================
# Atlas Setup & Seeding - V2
# ============================================

atlas-setup-v2:
	@echo "Running V2 Atlas setup script..."
	@echo "This will create indexes and configure sharding on RegionalBank_fraud_v2 database."
	@echo ""
	@echo "Usage: mongosh \"mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>" < scripts/atlas-setup-v2.js"
	@echo ""
	@read -p "Enter your Atlas connection string: " ATLAS_URI && \
	mongosh "$$ATLAS_URI" < scripts/atlas-setup-v2.js

seed-v2-test:
	@echo "V2 quick test seed (5 customers, 20 transactions - schema validation)..."
	cd backend_v2 && . .venv/bin/activate && python -m seed.main --test

seed-v2:
	@echo "V2 seeding (10k customers, 50k transactions)..."
	cd backend_v2 && . .venv/bin/activate && \
		SEED_CUSTOMERS=10000 SEED_TRANSACTIONS=50000 python -m seed.main

seed-v2-medium:
	@echo "V2 medium seeding (100k customers, 500k transactions)..."
	cd backend_v2 && . .venv/bin/activate && \
		SEED_CUSTOMERS=100000 SEED_TRANSACTIONS=500000 python -m seed.main

seed-v2-full:
	@echo "V2 full seeding (40M customers, 100M transactions)..."
	cd backend_v2 && . .venv/bin/activate && \
		SEED_CUSTOMERS=40000000 SEED_TRANSACTIONS=100000000 python -m seed.main

seed-v2-reset:
	@echo "V2 resetting all collections (drop + recreate indexes)..."
	cd backend_v2 && . .venv/bin/activate && python -m seed.reset_collections

seed-v2-reset-force:
	@echo "V2 force resetting all collections (no confirmation)..."
	cd backend_v2 && . .venv/bin/activate && python -m seed.reset_collections --force

# ============================================
# Cleanup
# ============================================

clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "node_modules" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".svelte-kit" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.venv 2>/dev/null || true
	rm -rf backend_v2/.venv 2>/dev/null || true
	@echo "Cleanup complete!"
