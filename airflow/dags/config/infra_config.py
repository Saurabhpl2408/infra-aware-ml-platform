"""
Terraform Output Loader - Reads infrastructure configuration dynamically
This module is the bridge between Terraform and Airflow
"""
import json
import os
from typing import Dict, Any, Optional
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class InfrastructureConfig:
    """Loads and parses Terraform outputs for dynamic DAG configuration"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or os.getenv(
            'TERRAFORM_OUTPUT_PATH',
            '/opt/airflow/config/terraform_outputs.json'
        )
        self._config = None
        
    @property
    @lru_cache(maxsize=1)
    def config(self) -> Dict[str, Any]:
        """Load and cache Terraform outputs"""
        if self._config is None:
            try:
                with open(self.config_path, 'r') as f:
                    self._config = json.load(f)
                logger.info(f"Loaded infrastructure config from {self.config_path}")
            except FileNotFoundError:
                logger.warning(f"Config file not found: {self.config_path}, using defaults")
                self._config = self._get_default_config()
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in config file: {e}")
                self._config = self._get_default_config()
        
        return self._config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Fallback configuration if Terraform outputs are unavailable"""
        return {
            "environment": "dev",
            "cluster_name": "mlops-local",
            "resources": {
                "cpu_cores": 4,
                "memory_gb": 8,
                "worker_nodes": 2,
                "max_parallel_tasks": 4,
                "task_resources": {
                    "small": {
                        "cpu_request": "0.4",
                        "cpu_limit": "1",
                        "memory_request": "1Gi",
                        "memory_limit": "2Gi"
                    },
                    "medium": {
                        "cpu_request": "1",
                        "cpu_limit": "2",
                        "memory_request": "2Gi",
                        "memory_limit": "4Gi"
                    },
                    "large": {
                        "cpu_request": "2",
                        "cpu_limit": "4",
                        "memory_request": "4Gi",
                        "memory_limit": "8Gi"
                    }
                }
            },
            "storage": {
                "endpoint": "http://minio.storage.svc.cluster.local:9000",
                "buckets": {
                    "raw_data": "raw-data",
                    "processed_data": "processed-data",
                    "embeddings": "embeddings",
                    "models": "models",
                    "artifacts": "artifacts"
                }
            },
            "vector_db": {
                "endpoint": "http://chromadb.vector-db.svc.cluster.local:8000",
                "collection_prefix": "dev-",
                "batch_size": 100
            },
            "monitoring": {
                "pushgateway_url": "http://prometheus-pushgateway.monitoring.svc.cluster.local:9091"
            },
            "feature_flags": {
                "enable_drift_detection": False,
                "enable_quality_gates": True,
                "auto_rollback": False,
                "enable_caching": True
            }
        }
    
    @property
    def environment(self) -> str:
        return self.config.get("environment", "dev")
    
    @property
    def max_parallel_tasks(self) -> int:
        return self.config["resources"]["max_parallel_tasks"]
    
    @property
    def worker_nodes(self) -> int:
        return self.config["resources"]["worker_nodes"]
    
    def get_task_resources(self, size: str = "medium") -> Dict[str, str]:
        """
        Get resource allocation for a task based on size
        Args:
            size: small, medium, or large
        Returns:
            Dict with cpu_request, cpu_limit, memory_request, memory_limit
        """
        return self.config["resources"]["task_resources"].get(
            size,
            self.config["resources"]["task_resources"]["medium"]
        )
    
    def get_storage_bucket(self, bucket_type: str) -> str:
        """Get storage bucket name by type"""
        return self.config["storage"]["buckets"].get(bucket_type, f"{bucket_type}-bucket")
    
    @property
    def storage_endpoint(self) -> str:
        return self.config["storage"]["endpoint"]
    
    @property
    def vector_db_endpoint(self) -> str:
        return self.config["vector_db"]["endpoint"]
    
    @property
    def vector_db_batch_size(self) -> int:
        return self.config["vector_db"]["batch_size"]
    
    @property
    def monitoring_pushgateway(self) -> str:
        return self.config["monitoring"]["pushgateway_url"]
    
    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature flag is enabled"""
        return self.config["feature_flags"].get(feature, False)
    
    def calculate_dynamic_parallelism(self, base_parallelism: int) -> int:
        """
        Calculate actual parallelism based on infrastructure capacity
        This allows DAGs to scale automatically when infrastructure changes
        """
        max_tasks = self.max_parallel_tasks
        return min(base_parallelism, max_tasks)


# Global instance for use across DAGs
infra_config = InfrastructureConfig()