.PHONY: help setup deploy destroy test clean

help:
	@echo "MLOps Infrastructure-Aware Pipeline"
	@echo ""
	@echo "Available commands:"
	@echo "  make setup     - Install all prerequisites and setup environment"
	@echo "  make deploy    - Deploy complete infrastructure"
	@echo "  make destroy   - Teardown all infrastructure"
	@echo "  make test      - Run integration tests"
	@echo "  make clean     - Clean temporary files"
	@echo "  make port-forward - Forward all service ports"

setup:
	@bash scripts/setup-local-env.sh

deploy:
	@cd infrastructure && terraform apply -auto-approve
	@bash infrastructure/scripts/export-outputs.sh

destroy:
	@cd infrastructure && terraform destroy -auto-approve
	@kind delete cluster --name mlops-cluster

test:
	@pytest tests/ -v

clean:
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@rm -rf venv/

port-forward:
	@echo "Forwarding ports..."
	@kubectl port-forward svc/airflow-webserver -n airflow 8080:8080 &
	@kubectl port-forward svc/grafana -n monitoring 3000:80 &
	@kubectl port-forward svc/prometheus-server -n monitoring 9090:80 &
	@kubectl port-forward svc/minio -n storage 9001:9001 &
	@echo "Ports forwarded. Press Ctrl+C to stop."