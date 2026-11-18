#!/usr/bin/env bash
# paso 1: crea la vm en gcp (e2-standard-4)
# uso: bash gcp/01_crear_vm.sh <PROJECT_ID>
set -euo pipefail
PROJECT_ID="${1:?Uso: bash gcp/01_crear_vm.sh <PROJECT_ID>}"
ZONE="us-central1-a"
VM="bigdata-vm"

gcloud config set project "$PROJECT_ID"
gcloud services enable compute.googleapis.com

# vm: 4 vcpu, 16 gb ram, 50 gb disco; docker se instala con el startup script
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
      # gcp/04_setup_en_vm.sh completa este paso si /home esta vacio
      usermod -aG docker $(ls /home | head -1) || true
      # cassandra necesita este limite del kernel
      sysctl -w vm.max_map_count=1048575 && echo "vm.max_map_count=1048575" >> /etc/sysctl.conf
    fi'

# firewall: solo el dashboard (8501) es publico
gcloud compute firewall-rules create allow-dashboard-8501 \
  --network=default --allow=tcp:8501 --target-tags=bigdata \
  --source-ranges=0.0.0.0/0 --description="Dashboard Streamlit del proyecto Big Data" || true

echo
echo "VM creada. IP externa (el dashboard quedará en http://IP:8501):"
gcloud compute instances describe "$VM" --zone="$ZONE" --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
echo
echo "Conectarse con túneles:  bash gcp/02_tunel_ssh.sh $PROJECT_ID"
