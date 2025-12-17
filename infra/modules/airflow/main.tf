resource "kubernetes_namespace" "airflow" {
  metadata {
    name = var.namespace
  }
}

resource "helm_release" "airflow" {
  name       = "airflow"
  repository = "https://airflow.apache.org"
  chart      = "airflow"
  version    = "1.11.0"
  namespace  = var.namespace
  
  values = [
    templatefile("${path.module}/helm-values.yaml", {
      executor         = var.executor
      worker_replicas  = var.worker_replicas
      webserver_cpu    = var.resource_limits.webserver_cpu
      webserver_memory = var.resource_limits.webserver_memory
      worker_cpu       = var.resource_limits.worker_cpu
      worker_memory    = var.resource_limits.worker_memory
    })
  ]
  
  set {
    name  = "env[0].name"
    value = "TERRAFORM_OUTPUT_PATH"
  }
  
  set {
    name  = "env[0].value"
    value = var.environment_vars.TERRAFORM_OUTPUT_PATH
  }
  
  set {
    name  = "env[1].name"
    value = "ENVIRONMENT"
  }
  
  set {
    name  = "env[1].value"
    value = var.environment_vars.ENVIRONMENT
  }
  
  set {
    name  = "env[2].name"
    value = "MINIO_ENDPOINT"
  }
  
  set {
    name  = "env[2].value"
    value = var.environment_vars.MINIO_ENDPOINT
  }
  
  set {
    name  = "env[3].name"
    value = "CHROMA_ENDPOINT"
  }
  
  set {
    name  = "env[3].value"
    value = var.environment_vars.CHROMA_ENDPOINT
  }
  
  depends_on = [kubernetes_namespace.airflow]
}

# ConfigMap to mount Terraform outputs
resource "kubernetes_config_map" "terraform_outputs" {
  metadata {
    name      = "terraform-outputs"
    namespace = var.namespace
  }
  
  data = {
    "terraform_outputs.json" = file("${path.root}/../terraform_outputs.json")
  }
  
  depends_on = [helm_release.airflow]
}