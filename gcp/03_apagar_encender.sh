#!/usr/bin/env bash
# =====================================================================
#  Control de costos: apagar la VM cuando no se trabaja (no se cobra CPU/RAM,
#  solo el disco ~US$0.10/día). Los contenedores vuelven solos al encender
#  (restart: unless-stopped).
#  Uso:  bash gcp/03_apagar_encender.sh <PROJECT_ID> stop|start|status|delete
# =====================================================================
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/03_apagar_encender.sh <PROJECT_ID> stop|start|status|delete}"
ACTION="${2:-status}"
case "$ACTION" in
  stop)   gcloud compute instances stop  bigdata-vm --project "$PROJECT_ID" --zone us-central1-a ;;
  start)  gcloud compute instances start bigdata-vm --project "$PROJECT_ID" --zone us-central1-a
          echo "Nueva IP externa (si cambió, actualizar en Atlas):"
          gcloud compute instances describe bigdata-vm --project "$PROJECT_ID" --zone us-central1-a --format='get(networkInterfaces[0].accessConfigs[0].natIP)' ;;
  status) gcloud compute instances list --project "$PROJECT_ID" ;;
  delete) echo "Esto borra la VM y su disco (al terminar el curso)."; read -p "¿Seguro? (si/no) " ok
          [ "$ok" = "si" ] && gcloud compute instances delete bigdata-vm --project "$PROJECT_ID" --zone us-central1-a ;;
  *) echo "Acción desconocida: $ACTION" ;;
esac
