output "infrastructure_metadata" {
  description = "Complete infrastructure configuration for Airflow consumption"
  value = {
    environment = local.environment
    cluster_name = module.kubernetes.cluster_name
    
    resources = {
      cpu_cores         = local.current_resources.cpu_cores
      memory_gb         = local.current_resources.memory_gb
      worker_nodes      = local.current_resources.worker_nodes
      max_parallel_tasks = local.current_resources.max_parallel_tasks
      
      task_resources = {
        small = {
          cpu_request = "${local.current_resources.cpu_cores * 0.1}"
          cpu_limit   = "${local.current_resources.cpu_cores * 0.25}"
          memory_request = "${local.current_resources.memory_gb * 0.125}Gi"
          memory_limit   = "${local.current_resources.memory_gb * 0.25}Gi"
        }
        medium = {
          cpu_request = "${local.current_resources.cpu_cores * 0.25}"
          cpu_limit   = "${local.current_resources.cpu_cores * 0.5}"
          memory_request = "${local.current_resources.memory_gb * 0.25}Gi"
          memory_limit   = "${local.current_resources.memory_gb * 0.5}Gi"
        }
        large = {
          cpu_request = "${local.current_resources.cpu_cores * 0.5}"
          cpu_limit   = "${local.current_resources.cpu_cores * 1}"
          memory_request = "${local.current_resources.memory_gb * 0.5}Gi"
          memory_limit   = "${local.current_resources.memory_gb * 1}Gi"
        }
      }
    }
    
    storage = {
      endpoint     = module.storage.endpoint
      access_key   = module.storage.access_key
      secret_key   = module.storage.secret_key
      buckets = {
        raw_data       = module.storage.buckets["raw-data"]
        processed_data = module.storage.buckets["processed-data"]
        embeddings     = module.storage.buckets["embeddings"]
        models         = module.storage.buckets["models"]
        artifacts      = module.storage.buckets["artifacts"]
      }
    }
    
    vector_db = {
      endpoint       = module.vector_db.endpoint
      collection_prefix = "${local.environment}-"
      batch_size     = local.environment == "prod" ? 500 : 100
    }
    
    airflow = {
      webserver_url = module.airflow.webserver_url
      namespace     = module.airflow.namespace
    }
    
    monitoring = {
      prometheus_url = module.monitoring.prometheus_url
      grafana_url    = module.monitoring.grafana_url
      pushgateway_url = module.monitoring.pushgateway_url
    }
    
    feature_flags = {
      enable_drift_detection = local.environment == "prod"
      enable_quality_gates   = true
      auto_rollback         = local.environment == "prod"
      enable_caching        = true
    }
  }
  
  sensitive = false
}

output "airflow_dag_config" {
  description = "Simplified config specifically for DAG consumption"
  value = {
    max_active_runs = local.environment == "prod" ? 3 : 1
    max_active_tasks = local.current_resources.max_parallel_tasks
    concurrency = local.current_resources.max_parallel_tasks
    parallelism = local.current_resources.max_parallel_tasks
    default_task_retries = local.environment == "prod" ? 3 : 1
    task_execution_timeout_seconds = 3600
  }
}