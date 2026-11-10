#!/usr/bin/env bash
# =====================================================================
#  Paso 2: abrir sesión SSH con túneles hacia la VM. Mientras esta terminal
#  esté abierta, en tu navegador:
#     Airflow        -> http://localhost:8080   (admin / admin)
#     Jupyter        -> http://localhost:8888   (token: JUPYTER_TOKEN del .env, por defecto "bigdata")
#     Dashboard      -> http://localhost:8501
#     Neo4j Browser  -> http://localhost:7474   (neo4j / NEO4J_PASSWORD; conectar a bolt://localhost:7687)
#     Mongo Express  -> http://localhost:8081
#  Y desde tu laptop con los drivers: mongodb://localhost:27017, localhost:9042, bolt://localhost:7687
#  Uso:  bash gcp/02_tunel_ssh.sh <PROJECT_ID>
# =====================================================================
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/02_tunel_ssh.sh <PROJECT_ID>}"
gcloud compute ssh bigdata-vm --project "$PROJECT_ID" --zone us-central1-a -- \
  -L 8080:localhost:8080 \
  -L 8888:localhost:8888 \
  -L 8501:localhost:8501 \
  -L 7474:localhost:7474 \
  -L 7687:localhost:7687 \
  -L 8081:localhost:8081 \
  -L 27017:localhost:27017 \
  -L 9042:localhost:9042
