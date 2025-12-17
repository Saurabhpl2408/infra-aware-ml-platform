terraform {
  required_version = ">= 1.5.0"
  
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "kubernetes" {
  config_path    = "~/.kube/config"
  config_context = "kind-mlops-cluster"
}

provider "helm" {
  kubernetes {
    config_path    = "~/.kube/config"
    config_context = "kind-mlops-cluster"
  }
}

locals {
  environment = var.environment
  project_name = "mlops-infra-aware"
  
  resource_limits = {
    dev = {
      cpu_cores    = 4
      memory_gb    = 8
      worker_nodes = 2
      max_parallel_tasks = 4
    }
    staging = {
      cpu_cores    = 8
      memory_gb    = 16
      worker_nodes = 3
      max_parallel_tasks = 8
    }
    prod = {
      cpu_cores    = 16
      memory_gb    = 32
      worker_nodes = 5
      max_parallel_tasks = 16
    }
  }
  
  current_resources = local.resource_limits[local.environment]
}

module "kubernetes" {
  source = "./modules/kubernetes"
  
  cluster_name = "${local.project_name}-${local.environment}"
  worker_nodes = local.current_resources.worker_nodes
  
  labels = {
    environment = local.environment
    project     = local.project_name
    managed_by  = "terraform"
  }
}

module "storage" {
  source = "./modules/storage"
  
  namespace       = "storage"
  bucket_names    = var.storage_buckets
  storage_size_gb = var.storage_size_gb
  
  depends_on = [module.kubernetes]
}

module "vector_db" {
  source = "./modules/vector-db"
  
  namespace       = "vector-db"
  replicas        = local.environment == "prod" ? 3 : 1
  persistence_size = "${var.vector_db_storage_gb}Gi"
  
  depends_on = [module.kubernetes]
}

module "airflow" {
  source = "./modules/airflow"
  
  namespace        = "airflow"
  executor         = "KubernetesExecutor"
  worker_replicas  = local.current_resources.worker_nodes
  
  resource_limits = {
    webserver_cpu    = "${local.current_resources.cpu_cores / 4}"
    webserver_memory = "${local.current_resources.memory_gb / 4}Gi"
    worker_cpu       = "${local.current_resources.cpu_cores / 2}"
    worker_memory    = "${local.current_resources.memory_gb / 2}Gi"
  }
  
  environment_vars = {
    TERRAFORM_OUTPUT_PATH = "/opt/airflow/config/terraform_outputs.json"
    ENVIRONMENT           = local.environment
    MINIO_ENDPOINT        = module.storage.endpoint
    CHROMA_ENDPOINT       = module.vector_db.endpoint
  }
  
  depends_on = [module.kubernetes, module.storage, module.vector_db]
}

module "monitoring" {
  source = "./modules/monitoring"
  
  namespace = "monitoring"
  
  prometheus_config = {
    retention_days = local.environment == "prod" ? 30 : 7
    scrape_interval = "15s"
  }
  
  grafana_admin_password = var.grafana_admin_password
  
  depends_on = [module.kubernetes, module.airflow]
}