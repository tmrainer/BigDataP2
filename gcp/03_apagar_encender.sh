#!/usr/bin/env bash
# apaga o enciende la vm para controlar costos
# uso: bash gcp/03_apagar_encender.sh <PROJECT_ID> stop|start|status|delete
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/03_apagar_encender.sh <PROJECT_ID> stop|start|status|delete}"
ACTION="${2:-status}"
case "$ACTION" in
  stop)   gcloud compute instances stop  bigdata-vm --project "$PROJECT_ID" --zone us-central1-a ;;
  start)  gcloud compute instances start bigdata-vm --project "$PROJECT_ID" --zone us-central1-a
          echo "IP externa actual (dashboard en http://IP:8501):"
          gcloud compute instances describe bigdata-vm --project "$PROJECT_ID" --zone us-central1-a --format='get(networkInterfaces[0].accessConfigs[0].natIP)' ;;
  status) gcloud compute instances list --project "$PROJECT_ID" ;;
  delete) echo "Esto borra la VM y su disco (al terminar el curso)."; read -p "¿Seguro? (si/no) " ok
          [ "$ok" = "si" ] && gcloud compute instances delete bigdata-vm --project "$PROJECT_ID" --zone us-central1-a ;;
  *) echo "Acción desconocida: $ACTION" ;;
esac
