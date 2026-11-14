#!/usr/bin/env bash
# =====================================================================
#  Paso 4 (DENTRO de la VM, tras `git clone` del repo): levantar todo.
#  Uso:  cd proyecto-bigdata && bash gcp/04_setup_en_vm.sh
# =====================================================================
set -euo pipefail
SCRIPT="$(readlink -f "$0")"
cd "$(dirname "$SCRIPT")/.."

[ -f .env ] || { cp .env.example .env; echo ">> Se creó .env con valores por defecto (todo local)."; }

# Docker sin sudo: el startup-script de la VM corre antes de que exista el usuario SSH, así que
# no pudo agregarlo al grupo docker. Lo hacemos aquí y relanzamos el script con el grupo activo.
if ! docker info >/dev/null 2>&1; then
  if ! id -nG "$USER" | grep -qw docker; then
    echo ">> Agregando $USER al grupo docker (una sola vez)..."
    sudo usermod -aG docker "$USER"
    exec sg docker -c "bash '$SCRIPT'"
  fi
  echo ">> Docker no responde. ¿Terminó el startup-script? Revisa: sudo journalctl -u google-startup-scripts"
  exit 1
fi

# Permisos: Airflow corre como uid 50000 y Jupyter como uid 1000; ambos escriben en data/
mkdir -p data/raw data/processed
chmod -R a+rwX data

echo ">> Construyendo imágenes y levantando servicios: MongoDB, Cassandra, Neo4j, Postgres, Airflow, Jupyter, Streamlit (primera vez: 5-10 min)..."
docker compose build
docker compose up -d
echo ">> Esperando Cassandra..."
until docker exec cassandra cqlsh -e "describe keyspaces" >/dev/null 2>&1; do sleep 10; printf "."; done; echo

echo ">> Creando keyspace y tablas de Cassandra"
docker exec -i cassandra cqlsh < scripts/init_cassandra.cql

echo ">> Creando índices en MongoDB y constraints en Neo4j"
docker compose exec -T jupyter python scripts/init_mongo.py
docker compose exec -T jupyter python scripts/init_neo4j.py

echo ">> Carga inicial: la hora más reciente publicada por GH Archive (~4k eventos)"
echo "   Para cargar un día completo: docker compose exec jupyter bash -c 'cd src && python run_pipeline_local.py 2026-11-09 0 23'"
docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py'

echo
echo "Listo. Abre túneles con gcp/02_tunel_ssh.sh y entra a:"
echo "  Airflow   http://localhost:8080  (admin/admin)  -> DAG github_events_pipeline"
echo "  Jupyter   http://localhost:8888  (token: $(grep JUPYTER_TOKEN .env | cut -d= -f2))"
echo "  Neo4j     http://localhost:7474  (neo4j / $(grep NEO4J_PASSWORD .env | cut -d= -f2))"
echo "  Mongo UI  http://localhost:8081"
echo "  Cassandra UI http://localhost:8083/#/main"
echo "  Dashboard http://localhost:8501  o http://$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip):8501"
