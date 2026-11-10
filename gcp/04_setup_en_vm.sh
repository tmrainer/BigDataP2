#!/usr/bin/env bash
# =====================================================================
#  Paso 4 (DENTRO de la VM, tras `git clone` del repo): levantar todo.
#  Uso:  cd proyecto-bigdata && bash gcp/04_setup_en_vm.sh
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { cp .env.example .env; echo ">> Se creó .env. EDÍTALO con tus credenciales de Atlas y Aura y vuelve a ejecutar."; exit 1; }
grep -q "CAMBIAR" .env && { echo ">> Completa NEO4J_PASSWORD y MONGO_URI en .env"; exit 1; }

# Permisos: Airflow corre como uid 50000 y Jupyter como uid 1000; ambos escriben en data/
mkdir -p data/raw data/processed
chmod -R a+rwX data

echo ">> Construyendo imágenes y levantando servicios (primera vez: 5-10 min)..."
docker compose build
docker compose up -d
echo ">> Esperando Cassandra..."
until docker exec cassandra cqlsh -e "describe keyspaces" >/dev/null 2>&1; do sleep 10; printf "."; done; echo

echo ">> Creando keyspace y tablas de Cassandra"
docker exec -i cassandra cqlsh < scripts/init_cassandra.cql

echo ">> Creando índices en MongoDB Atlas y constraints en Neo4j Aura"
docker compose exec -T jupyter python scripts/init_mongo.py
docker compose exec -T jupyter python scripts/init_neo4j.py

echo ">> Carga inicial: la hora más reciente publicada por GH Archive (hasta MAX_EVENTS_PER_RUN=60,000 eventos)"
echo "   Para cargar un día completo: docker compose exec jupyter bash -c 'cd src && python run_pipeline_local.py 2026-11-09 0 23'"
docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py'

echo
echo "Listo. Abre túneles con gcp/02_tunel_ssh.sh y entra a:"
echo "  Airflow   http://localhost:8080  (admin/admin)  -> DAG github_events_pipeline"
echo "  Jupyter   http://localhost:8888  (token: $(grep JUPYTER_TOKEN .env | cut -d= -f2))"
echo "  Dashboard http://localhost:8501  o http://$(curl -s -H 'Metadata-Flavor: Google' http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip):8501"
