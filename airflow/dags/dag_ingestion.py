"""
Data Ingestion DAG - Dynamically adapts to infrastructure
Reads documents, chunks them, and prepares for embedding generation
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator
from airflow.utils.task_group import TaskGroup

from config.infra_config import infra_config

# DAG configuration adapts to infrastructure
default_args = {
    'owner': 'mlops-team',
    'depends_on_past': False,
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': infra_config.config.get('default_task_retries', 1),
    'retry_delay': timedelta(minutes=5),
}

# Calculate dynamic parallelism
BASE_PARALLELISM = 8
actual_parallelism = infra_config.calculate_dynamic_parallelism(BASE_PARALLELISM)

with DAG(
    'data_ingestion_pipeline',
    default_args=default_args,
    description='Ingest and preprocess documents for RAG',
    schedule_interval='@daily' if infra_config.environment == 'prod' else None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    concurrency=actual_parallelism,
    tags=['ingestion', 'rag', f'env:{infra_config.environment}'],
) as dag:
    
    def validate_infrastructure(**context):
        """Validate that infrastructure is ready"""
        import requests
        
        # Check storage availability
        try:
            response = requests.get(f"{infra_config.storage_endpoint}/minio/health/live", timeout=5)
            assert response.status_code == 200, "MinIO not healthy"
        except Exception as e:
            raise Exception(f"Storage check failed: {e}")
        
        # Check vector DB
        try:
            response = requests.get(f"{infra_config.vector_db_endpoint}/api/v1/heartbeat", timeout=5)
            assert response.status_code == 200, "ChromaDB not healthy"
        except Exception as e:
            raise Exception(f"Vector DB check failed: {e}")
        
        # Push metadata
        context['ti'].xcom_push(key='environment', value=infra_config.environment)
        context['ti'].xcom_push(key='max_parallel_tasks', value=infra_config.max_parallel_tasks)
        
        print(f"Infrastructure validated successfully")
        print(f"Environment: {infra_config.environment}")
        print(f"Max parallel tasks: {infra_config.max_parallel_tasks}")
    
    validate_infra = PythonOperator(
        task_id='validate_infrastructure',
        python_callable=validate_infrastructure,
    )
    
    def load_documents(**context):
        """Load documents from storage"""
        from ml_pipelines.ingestion.document_loader import DocumentLoader
        from airflow.include.utils.storage_client import MinIOClient
        
        storage_client = MinIOClient(
            endpoint=infra_config.storage_endpoint,
            bucket=infra_config.get_storage_bucket('raw_data')
        )
        
        loader = DocumentLoader(storage_client)
        documents = loader.load_all()
        
        # Store document IDs for downstream processing
        doc_ids = [doc['id'] for doc in documents]
        context['ti'].xcom_push(key='document_ids', value=doc_ids)
        context['ti'].xcom_push(key='document_count', value=len(doc_ids))
        
        return len(doc_ids)
    
    load_docs = PythonOperator(
        task_id='load_documents',
        python_callable=load_documents,
    )
    
    # Dynamic task group - parallelism adapts to infrastructure
    with TaskGroup('process_documents') as process_group:
        
        # Create dynamic number of processing tasks based on infrastructure
        for i in range(actual_parallelism):
            
            # Get appropriate resource allocation from Terraform outputs
            task_resources = infra_config.get_task_resources('medium')
            
            process_task = KubernetesPodOperator(
                task_id=f'process_chunk_{i}',
                name=f'process-docs-{i}',
                namespace='airflow',
                image='mlops-worker:latest',
                cmds=['python', '-m', 'ml_pipelines.ingestion.chunking'],
                arguments=[
                    '--chunk-id', str(i),
                    '--total-chunks', str(actual_parallelism),
                    '--storage-endpoint', infra_config.storage_endpoint,
                    '--batch-size', str(infra_config.vector_db_batch_size),
                ],
                resources={
                    'request_memory': task_resources['memory_request'],
                    'request_cpu': task_resources['cpu_request'],
                    'limit_memory': task_resources['memory_limit'],
                    'limit_cpu': task_resources['cpu_limit'],
                },
                get_logs=True,
                is_delete_operator_pod=True,
            )
    
    def validate_output(**context):
        """Validate processing output"""
        from airflow.include.utils.storage_client import MinIOClient
        
        storage_client = MinIOClient(
            endpoint=infra_config.storage_endpoint,
            bucket=infra_config.get_storage_bucket('processed_data')
        )
        
        # Check that processed files exist
        doc_count = context['ti'].xcom_pull(key='document_count', task_ids='load_documents')
        processed_files = storage_client.list_objects()
        
        assert len(processed_files) >= doc_count, f"Expected {doc_count} files, found {len(processed_files)}"
        
        # Push metrics to Prometheus
        if infra_config.monitoring_pushgateway:
            from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
            
            registry = CollectorRegistry()
            g = Gauge('documents_processed_total', 'Total documents processed', 
                     ['environment'], registry=registry)
            g.labels(environment=infra_config.environment).set(doc_count)
            
            push_to_gateway(infra_config.monitoring_pushgateway, 
                          job='data_ingestion', registry=registry)
    
    validate_output_task = PythonOperator(
        task_id='validate_output',
        python_callable=validate_output,
    )
    
    # DAG flow
    validate_infra >> load_docs >> process_group >> validate_output_task