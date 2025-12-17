#!/bin/bash
set -e

echo "========================================="
echo "MLOps Infrastructure-Aware Setup"
echo "========================================="

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}Checking prerequisites...${NC}"
    
    # Docker
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Docker not found. Installing...${NC}"
        curl -fsSL https://get.docker.com -o get-docker.sh
        sudo sh get-docker.sh
        sudo usermod -aG docker $USER
    fi
    
    # kubectl
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}kubectl not found. Installing...${NC}"
        curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
        sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
    fi
    
    # Helm
    if ! command -v helm &> /dev/null; then
        echo -e "${RED}Helm not found. Installing...${NC}"
        curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
    fi
    
    # kind
    if ! command -v kind &> /dev/null; then
        echo -e "${RED}kind not found. Installing...${NC}"
        curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
        chmod +x ./kind
        sudo mv ./kind /usr/local/bin/kind
    fi
    
    # Terraform
    if ! command -v terraform &> /dev/null; then
        echo -e "${RED}Terraform not found. Installing...${NC}"
        wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
        echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
        sudo apt update && sudo apt install terraform
    fi
    
    echo -e "${GREEN}All prerequisites installed${NC}"
}

# Setup Python environment
setup_python() {
    echo -e "${YELLOW}Setting up Python environment...${NC}"
    
    cd "$PROJECT_ROOT"
    
    # Create virtual environment
    python3 -m venv venv
    source venv/bin/activate
    
    # Install dependencies
    pip install --upgrade pip
    pip install -r docker/airflow/requirements.txt
    pip install -r docker/ml-worker/requirements.txt
    
    echo -e "${GREEN}Python environment ready${NC}"
}

# Deploy infrastructure
deploy_infrastructure() {
    echo -e "${YELLOW}Deploying infrastructure with Terraform...${NC}"
    
    cd "$PROJECT_ROOT/infrastructure"
    
    # Initialize Terraform
    terraform init
    
    # Create kind cluster and deploy everything
    terraform apply -auto-approve
    
    # Export outputs
    bash scripts/export-outputs.sh
    
    echo -e "${GREEN}Infrastructure deployed${NC}"
}

# Deploy Ollama
deploy_ollama() {
    echo -e "${YELLOW}Deploying Ollama for local LLM...${NC}"
    
    kubectl create namespace ml-workers || true
    
    kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: ml-workers
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
        app: ollama
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: ml-workers
spec:
  selector:
    app: ollama
  ports:
  - port: 11434
    targetPort: 11434
  type: ClusterIP
EOF
    
    # Wait for Ollama to be ready
    kubectl wait --for=condition=available --timeout=300s deployment/ollama -n ml-workers
    
    # Pull llama2 model
    kubectl exec -n ml-workers deployment/ollama -- ollama pull llama2
    
    echo -e "${GREEN}Ollama deployed${NC}"
}

# Build Docker images
build_images() {
    echo -e "${YELLOW}Building Docker images...${NC}"
    
    cd "$PROJECT_ROOT/docker/ml-worker"
    docker build -t mlops-worker:latest .
    
    # Load image into kind cluster
    kind load docker-image mlops-worker:latest --name mlops-cluster
    
    echo -e "${GREEN}Docker images built and loaded${NC}"
}

# Display access information
display_info() {
    echo ""
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}MLOps Platform Ready!${NC}"
    echo -e "${GREEN}=========================================${NC}"
    echo ""
    echo -e "${YELLOW}Access URLs:${NC}"
    echo "  Airflow UI:    http://localhost:8080"
    echo "  Grafana:       http://localhost:3000 (admin/admin)"
    echo "  Prometheus:    http://localhost:9090"
    echo "  MinIO Console: http://localhost:9001 (minioadmin/minioadmin)"
    echo ""
    echo -e "${YELLOW}Next steps:${NC}"
    echo "  1. Port-forward services: kubectl port-forward svc/airflow-webserver -n airflow 8080:8080"
    echo "  2. Access Airflow and trigger DAGs"
    echo "  3. Monitor in Grafana"
    echo ""
}

# Main execution
main() {
    check_prerequisites
    setup_python
    deploy_infrastructure
    deploy_ollama
    build_images
    display_info
}

main