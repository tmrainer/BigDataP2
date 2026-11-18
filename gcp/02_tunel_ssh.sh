#!/usr/bin/env bash
# paso 2: ssh a la vm con tuneles a airflow 8080, jupyter 8888, dashboard 8501,
# neo4j 7474/7687, mongo express 8081, cassandra web 8083, mongodb 27017, cassandra 9042
# uso: bash gcp/02_tunel_ssh.sh <PROJECT_ID>
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/02_tunel_ssh.sh <PROJECT_ID>}"
gcloud compute ssh bigdata-vm --project "$PROJECT_ID" --zone us-central1-a -- \
  -L 8080:localhost:8080 \
  -L 8888:localhost:8888 \
  -L 8501:localhost:8501 \
  -L 7474:localhost:7474 \
  -L 7687:localhost:7687 \
  -L 8081:localhost:8081 \
  -L 8083:localhost:8083 \
  -L 27017:localhost:27017 \
  -L 9042:localhost:9042
