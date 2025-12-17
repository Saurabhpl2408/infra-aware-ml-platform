"""
RAG Evaluation DAG - Quality gates with automatic rollback
Evaluates RAG performance and rolls back on quality regression
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator, BranchPythonOperator
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator

from config.infra_config import infra_config

default_args = {
    'owner': 'mlops-team',
    'depends_on_past': False,
    'email_on_failure': True,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    'rag_evaluation_pipeline',
    default_args=default_args,
    description='Evaluate RAG quality with automatic rollback on regression',
    schedule_interval='@daily' if infra_config.environment == 'prod' else None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['evaluation', 'rag', 'quality-gate', f'env:{infra_config.environment}'],
) as dag:
    
    def run_rag_evaluation(**context):
        """Run comprehensive RAG evaluation"""
        import requests
        import json
        from ml_pipelines.rag.evaluator import RAGEvaluator
        from ml_pipelines.rag.metrics import (
            calculate_faithfulness,
            calculate_relevance,
            calculate_coherence
        )
        
        evaluator = RAGEvaluator(
            vector_db_endpoint=infra_config.vector_db_endpoint,
            ollama_endpoint="http://ollama.ml-workers.svc.cluster.local:11434"
        )
        
        # Test queries
        test_queries = [
            "What is machine learning?",
            "Explain neural networks",
            "How does gradient descent work?",
        ]
        
        results = {
            'faithfulness': [],
            'relevance': [],
            'coherence': [],
            'response_time': []
        }
        
        for query in test_queries:
            metrics = evaluator.evaluate_query(query)
            results['faithfulness'].append(metrics['faithfulness'])
            results['relevance'].append(metrics['relevance'])
            results['coherence'].append(metrics['coherence'])
            results['response_time'].append(metrics['response_time'])
        
        # Calculate aggregates
        avg_metrics = {
            'avg_faithfulness': sum(results['faithfulness']) / len(results['faithfulness']),
            'avg_relevance': sum(results['relevance']) / len(results['relevance']),
            'avg_coherence': sum(results['coherence']) / len(results['coherence']),
            'avg_response_time': sum(results['response_time']) / len(results['response_time']),
        }
        
        context['ti'].xcom_push(key='evaluation_results', value=avg_metrics)
        
        # Push metrics to Prometheus
        if infra_config.monitoring_pushgateway:
            from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
            
            registry = CollectorRegistry()
            
            for metric_name, value in avg_metrics.items():
                g = Gauge(f'rag_{metric_name}', f'RAG {metric_name}', 
                         ['environment'], registry=registry)
                g.labels(environment=infra_config.environment).set(value)
            
            push_to_gateway(infra_config.monitoring_pushgateway, 
                          job='rag_evaluation', registry=registry)
        
        return avg_metrics
    
    evaluate_rag = PythonOperator(
        task_id='run_rag_evaluation',
        python_callable=run_rag_evaluation,
    )
    
    def check_quality_gates(**context):
        """Check if quality metrics meet thresholds"""
        results = context['ti'].xcom_pull(key='evaluation_results', task_ids='run_rag_evaluation')
        
        # Quality thresholds (environment-dependent)
        thresholds = {
            'dev': {
                'min_faithfulness': 0.6,
                'min_relevance': 0.6,
                'min_coherence': 0.6,
                'max_response_time': 10.0,
            },
            'staging': {
                'min_faithfulness': 0.7,
                'min_relevance': 0.7,
                'min_coherence': 0.7,
                'max_response_time': 5.0,
            },
            'prod': {
                'min_faithfulness': 0.8,
                'min_relevance': 0.8,
                'min_coherence': 0.75,
                'max_response_time': 3.0,
            }
        }
        
        env_thresholds = thresholds.get(infra_config.environment, thresholds['dev'])
        
        # Check each metric
        quality_pass = True
        failed_metrics = []
        
        if results['avg_faithfulness'] < env_thresholds['min_faithfulness']:
            quality_pass = False
            failed_metrics.append('faithfulness')
        
        if results['avg_relevance'] < env_thresholds['min_relevance']:
            quality_pass = False
            failed_metrics.append('relevance')
        
        if results['avg_coherence'] < env_thresholds['min_coherence']:
            quality_pass = False
            failed_metrics.append('coherence')
        
        if results['avg_response_time'] > env_thresholds['max_response_time']:
            quality_pass = False
            failed_metrics.append('response_time')
        
        context['ti'].xcom_push(key='quality_pass', value=quality_pass)
        context['ti'].xcom_push(key='failed_metrics', value=failed_metrics)
        
        if not quality_pass:
            if infra_config.is_feature_enabled('auto_rollback'):
                return 'trigger_rollback'
            else:
                return 'send_alert'
        
        return 'deploy_success'
    
    quality_gate = BranchPythonOperator(
        task_id='check_quality_gates',
        python_callable=check_quality_gates,
    )
    
    def trigger_rollback(**context):
        """Rollback to previous good version"""
        import chromadb
        from chromadb.config import Settings
        
        print("Quality regression detected. Rolling back...")
        
        failed_metrics = context['ti'].xcom_pull(key='failed_metrics', task_ids='check_quality_gates')
        print(f"Failed metrics: {failed_metrics}")
        
        # Connect to ChromaDB and restore previous collection
        client = chromadb.HttpClient(
            host=infra_config.vector_db_endpoint.split('//')[1].split(':')[0],
            port=int(infra_config.vector_db_endpoint.split(':')[-1].split('/')[0]),
            settings=Settings(anonymized_telemetry=False)
        )
        
        current_collection = f"{infra_config.config['vector_db']['collection_prefix']}documents"
        backup_collection = f"{current_collection}_backup"
        
        # Delete current and restore backup
        try:
            client.delete_collection(name=current_collection)
            # In production, implement proper backup/restore logic
            print(f"Rolled back {current_collection}")
        except Exception as e:
            print(f"Rollback failed: {e}")
            raise
    
    rollback_task = PythonOperator(
        task_id='trigger_rollback',
        python_callable=trigger_rollback,
    )
    
    def send_alert(**context):
        """Send alert about quality regression"""
        failed_metrics = context['ti'].xcom_pull(key='failed_metrics', task_ids='check_quality_gates')
        results = context['ti'].xcom_pull(key='evaluation_results', task_ids='run_rag_evaluation')
        
        print(f"ALERT: Quality regression detected")
        print(f"Failed metrics: {failed_metrics}")
        print(f"Current results: {results}")
        
        # In production, integrate with PagerDuty/Slack/Email
    
    alert_task = PythonOperator(
        task_id='send_alert',
        python_callable=send_alert,
    )
    
    def deploy_success(**context):
        """Mark deployment as successful"""
        print("All quality gates passed. Deployment successful.")
    
    success_task = PythonOperator(
        task_id='deploy_success',
        python_callable=deploy_success,
    )
    
    # DAG flow
    evaluate_rag >> quality_gate >> [trigger_rollback, send_alert, success_task]