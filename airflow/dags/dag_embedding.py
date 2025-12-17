"""
Embedding Generation DAG - Infrastructure-aware parallel processing
Generates embeddings using sentence-transformers with dynamic batching
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator
from airflow.utils.trigger_rule import TriggerRule

from config.infra_config import infra_config

default_args = {
    'owner': 'mlops-team',
    'depends_on_past': True,
    'email_on_failure': True,
    'retries': infra_config.config.get('default_task_retries', 1),
    'retry_delay': timedelta(minutes=5),
}

# Calculate resources for embedding generation (computationally intensive)
BASE_EMBEDDING_PARALLELISM = 6
embedding_parallelism = infra_config.calculate_dynamic_parallelism(BASE_EMBEDDING_PARALLELISM)

with DAG(
    'embedding_generation_pipeline',
    default_args=default_args,
    description='Generate embeddings with infrastructure-aware resource allocation',
    schedule_interval='@daily' if infra_config.environment == 'prod' else None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    concurrency=embedding_parallelism,
    tags=['embeddings', 'rag', f'env:{infra_config.environment}'],
) as dag:
    
    def check_prerequisites(**context):
        """Check if processed data is available"""
        from airflow.include.utils.storage_client import MinIOClient
        
        storage_client = MinIOClient(
            endpoint=infra_config.storage_endpoint,
            bucket=infra_config.get_storage_bucket('processed_data')
        )
        
        files = storage_client.list_objects()
        
        if len(files) == 0:
            return 'skip_pipeline'
        
        context['ti'].xcom_push(key='file_count', value=len(files))
        return 'load_model'
    
    check_prereqs = BranchPythonOperator(
        task_id='check_prerequisites',
        python_callable=check_prerequisites,
    )
    
    # Use large resources for model loading
    model_resources = infra_config.get_task_resources('large')
    
    load_model = KubernetesPodOperator(
        task_id='load_model',
        name='load-embedding-model',
        namespace='airflow',
        image='mlops-worker:latest',
        cmds=['python', '-m', 'ml_pipelines.embeddings.model_registry'],
        arguments=[
            '--model-name', 'all-MiniLM-L6-v2',
            '--storage-endpoint', infra_config.storage_endpoint,
            '--cache-bucket', infra_config.get_storage_bucket('models'),
        ],
        resources={
            'request_memory': model_resources['memory_request'],
            'request_cpu': model_resources['cpu_request'],
            'limit_memory': model_resources['memory_limit'],
            'limit_cpu': model_resources['cpu_limit'],
        },
        get_logs=True,
        is_delete_operator_pod=True,
    )
    
    # Generate embeddings in parallel
    embedding_tasks = []
    for i in range(embedding_parallelism):
        
        # Medium resources for embedding generation
        task_resources = infra_config.get_task_resources('medium')
        
        generate_embeddings = KubernetesPodOperator(
            task_id=f'generate_embeddings_{i}',
            name=f'generate-embeddings-{i}',
            namespace='airflow',
            image='mlops-worker:latest',
            cmds=['python', '-m', 'ml_pipelines.embeddings.batch_processor'],
            arguments=[
                '--partition', str(i),
                '--total-partitions', str(embedding_parallelism),
                '--storage-endpoint', infra_config.storage_endpoint,
                '--input-bucket', infra_config.get_storage_bucket('processed_data'),
                '--output-bucket', infra_config.get_storage_bucket('embeddings'),
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
        
        embedding_tasks.append(generate_embeddings)
    
    def store_in_vector_db(**context):
        """Store embeddings in ChromaDB"""
        import chromadb
        from chromadb.config import Settings
        from airflow.include.utils.storage_client import MinIOClient
        import pickle
        
        # Connect to ChromaDB
        client = chromadb.HttpClient(
            host=infra_config.vector_db_endpoint.split('//')[1].split(':')[0],
            port=int(infra_config.vector_db_endpoint.split(':')[-1].split('/')[0]),
            settings=Settings(anonymized_telemetry=False)
        )
        
        collection_name = f"{infra_config.config['vector_db']['collection_prefix']}documents"
        collection = client.get_or_create_collection(name=collection_name)
        
        # Load embeddings from storage
        storage_client = MinIOClient(
            endpoint=infra_config.storage_endpoint,
            bucket=infra_config.get_storage_bucket('embeddings')
        )
        
        batch_size = infra_config.vector_db_batch_size
        embedding_files = storage_client.list_objects()
        
        total_stored = 0
        for file_name in embedding_files:
            data = storage_client.get_object(file_name)
            embeddings_batch = pickle.loads(data)
            
            # Store in batches
            for i in range(0, len(embeddings_batch), batch_size):
                batch = embeddings_batch[i:i+batch_size]
                
                collection.add(
                    embeddings=[item['embedding'] for item in batch],
                    documents=[item['text'] for item in batch],
                    metadatas=[item['metadata'] for item in batch],
                    ids=[item['id'] for item in batch],
                )
                
                total_stored += len(batch)
        
        context['ti'].xcom_push(key='vectors_stored', value=total_stored)
        
        # Push metrics
        if infra_config.monitoring_pushgateway:
            from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
            
            registry = CollectorRegistry()
            g = Gauge('vectors_stored_total', 'Total vectors in database', 
                     ['environment', 'collection'], registry=registry)
            g.labels(
                environment=infra_config.environment,
                collection=collection_name
            ).set(total_stored)
            
            push_to_gateway(infra_config.monitoring_pushgateway, 
                          job='embedding_storage', registry=registry)
        
        return total_stored
    
    store_vectors = PythonOperator(
        task_id='store_in_vector_db',
        python_callable=store_in_vector_db,
    )
    
    def skip_pipeline(**context):
        """Skip task for branch operator"""
        print("No data available for processing")
    
    skip_task = PythonOperator(
        task_id='skip_pipeline',
        python_callable=skip_pipeline,
    )
    
    # DAG flow
    check_prereqs >> [load_model, skip_task]
    load_model >> embedding_tasks >> store_vectors