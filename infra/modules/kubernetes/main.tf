# This module assumes you're using kind for local development
# For production, replace with actual K8s provider (EKS, GKE, AKS alternatives)

resource "null_resource" "kind_cluster" {
  provisioner "local-exec" {
    command = <<-EOT
      #!/bin/bash
      set -e
      
      if ! command -v kind &> /dev/null; then
        echo "Installing kind..."
        curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
        chmod +x ./kind
        sudo mv ./kind /usr/local/bin/kind
      fi
      
      if kind get clusters | grep -q "${var.cluster_name}"; then
        echo "Cluster ${var.cluster_name} already exists"
      else
        echo "Creating kind cluster ${var.cluster_name}..."
        cat <<EOF | kind create cluster --name=${var.cluster_name} --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30000
    hostPort: 8080
    protocol: TCP
  - containerPort: 30001
    hostPort: 9090
    protocol: TCP
  - containerPort: 30002
    hostPort: 3000
    protocol: TCP
$(for i in $(seq 1 ${var.worker_nodes}); do echo "- role: worker"; done)
EOF
      fi
    EOT
  }
  
  provisioner "local-exec" {
    when = destroy
    command = "kind delete cluster --name=${var.cluster_name} || true"
  }
}

resource "kubernetes_namespace" "namespaces" {
  for_each = toset(["airflow", "storage", "vector-db", "monitoring", "ml-workers"])
  
  metadata {
    name = each.key
    labels = var.labels
  }
  
  depends_on = [null_resource.kind_cluster]
}