#!/usr/bin/env bash
# =====================================================================
#  Paso 1 (desde Cloud Shell o tu laptop con gcloud): crear la VM.
#  Cuenta: prueba gratuita de US$300. Costo aprox. e2-standard-4: ~US$0.13/h.
#  Uso:  bash gcp/01_crear_vm.sh <PROJECT_ID>
# =====================================================================
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/01_crear_vm.sh <PROJECT_ID>}"
ZONE="us-central1-a"          # misma región que Atlas Free (us-central1) -> latencia mínima
VM="bigdata-vm"

gcloud config set project "$PROJECT_ID"
gcloud services enable compute.googleapis.com

# VM: 4 vCPU / 16 GB RAM / 50 GB disco. Docker se instala con el startup script.
gcloud compute instances create "$VM" \
  --zone="$ZONE" \
  --machine-type=e2-standard-4 \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud \
  --boot-disk-size=50GB --boot-disk-type=pd-balanced \
  --tags=bigdata \
  --metadata=startup-script='#!/bin/bash
    if ! command -v docker >/dev/null; then
      apt-get update && apt-get install -y ca-certificates curl git
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
      apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
      usermod -aG docker $(ls /home | head -1) || true
      # Cassandra necesita este límite del kernel
      sysctl -w vm.max_map_count=1048575 && echo "vm.max_map_count=1048575" >> /etc/sysctl.conf
    fi'

# Firewall: SOLO el dashboard es público (8501). Jupyter/Airflow se usan por túnel SSH.
gcloud compute firewall-rules create allow-dashboard-8501 \
  --network=default --allow=tcp:8501 --target-tags=bigdata \
  --source-ranges=0.0.0.0/0 --description="Dashboard Streamlit del proyecto Big Data" || true

echo
echo "VM creada. IP externa (agregarla al IP Access List de MongoDB Atlas):"
gcloud compute instances describe "$VM" --zone="$ZONE" --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
echo
echo "Conectarse con túneles:  bash gcp/02_tunel_ssh.sh $PROJECT_ID"
