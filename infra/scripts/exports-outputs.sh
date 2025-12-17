#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$INFRA_DIR/terraform_outputs.json"

cd "$INFRA_DIR"

echo "Exporting Terraform outputs..."
terraform output -json infrastructure_metadata > "$OUTPUT_FILE"

echo "Terraform outputs exported to: $OUTPUT_FILE"

# Also export to Airflow config location
AIRFLOW_CONFIG_DIR="$INFRA_DIR/../airflow/config"
mkdir -p "$AIRFLOW_CONFIG_DIR"
cp "$OUTPUT_FILE" "$AIRFLOW_CONFIG_DIR/terraform_outputs.json"

echo "Outputs copied to Airflow config directory"