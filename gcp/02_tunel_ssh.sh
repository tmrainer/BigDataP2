#!/usr/bin/env bash
# =====================================================================
#  Paso 2: abrir sesión SSH con túneles hacia la VM. Mientras esta terminal
#  esté abierta, en tu navegador:
#     Jupyter   -> http://localhost:8888   (token: JUPYTER_TOKEN del .env, por defecto "bigdata")
#     Airflow   -> http://localhost:8080   (admin / admin)
#     Dashboard -> http://localhost:8501
#  Uso:  bash gcp/02_tunel_ssh.sh <PROJECT_ID>
# =====================================================================
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/02_tunel_ssh.sh <PROJECT_ID>}"
gcloud compute ssh bigdata-vm --project "$PROJECT_ID" --zone us-central1-a -- \
  -L 8888:localhost:8888 \
  -L 8080:localhost:8080 \
  -L 8501:localhost:8501 \
  -L 9042:localhost:9042
