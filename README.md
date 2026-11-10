# Proyecto Grupal II · Big Data · Arquitectura multimodelo (MongoDB + Cassandra + Neo4j + Airflow)

Pipeline de **GitHub Events** (GH Archive: todos los eventos públicos de GitHub, un archivo JSON por hora) orquestado con **Apache Airflow**, almacenado en
**MongoDB** (documentos), **Cassandra** (series temporales) y **Neo4j** (grafo), con **dashboard
Streamlit**. Todo corre en **Docker en un solo host**: tu laptop para desarrollar, una VM de Google
Cloud (prueba gratuita de US$300) para la entrega.

```
┌──────────────────── Docker (VM e2-standard-4 en GCP, o laptop ≥ 12 GB RAM) ────────────────────┐
│                                                                                                  │
│  GH Archive ──► Airflow (DAG 6 etapas, @hourly) ────► MongoDB   :27017  capa 1: documentos      │
│  (JSON/hora)         │  Postgres (metadata)              │                                       │
│                      │                                   ▼  (lee Mongo)                          │
│                      │                              Cassandra :9042   capa 2: agregados / KPIs   │
│                      │                                   │                                       │
│                      │                                   ▼  (lee Cassandra)                      │
│                      │                              Neo4j     :7687   capa 3: grafo User→Repo→Org│
│                      ▼                                        ▲                                  │
│  JupyterLab :8888 (notebooks CRUD) ───────────────────────────┤                                  │
│  Streamlit  :8501 (dashboard, público) ───────────────────────┘   Neo4j Browser :7474            │
│                                                                   Mongo Express :8081            │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Componente | Imagen | Puerto (solo localhost salvo 8501) |
|---|---|---|
| MongoDB 7 | `mongo:7` | 27017 · UI `mongo-express` 8081 |
| Cassandra 4.1 | `cassandra:4.1` | 9042 |
| Neo4j 5 | `neo4j:5` | 7687 (bolt) · 7474 (Browser) |
| Airflow 2.10 + Postgres 15 | `docker/Dockerfile.airflow` | 8080 (admin/admin) |
| JupyterLab | `docker/Dockerfile.jupyter` | 8888 (token `bigdata`) |
| Streamlit | `docker/Dockerfile.dashboard` | **8501 público** |

Costo en GCP: solo la VM (≈ US$0.13/h encendida + US$0.17/día de disco). MongoDB, Cassandra y Neo4j
no cuestan nada extra porque son contenedores en la misma VM.

---

## 1. Levantarlo en tu laptop (recomendado antes de ir a la nube)

Requisitos: Docker Desktop o Docker Engine con `docker compose` v2, 12 GB RAM libres, 20 GB disco.

```bash
cp .env.example .env            # los valores por defecto funcionan tal cual
docker compose up -d --build    # primera vez: 5-10 min (descarga imágenes + pip install)
docker compose ps               # esperar a que todo esté healthy; airflow-init termina con exit 0

docker exec -i cassandra cqlsh < scripts/init_cassandra.cql        # keyspace + 6 tablas
docker compose exec -T jupyter python scripts/init_mongo.py         # colección + validador + índices
docker compose exec -T jupyter python scripts/init_neo4j.py         # constraints de unicidad

docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py'   # carga inicial: la última hora publicada (~4k eventos)
docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py 2026-11-09 0 23'   # un día completo (~85k eventos, ~3 min)
```

Abrir: Dashboard http://localhost:8501 · Airflow http://localhost:8080 · Jupyter http://localhost:8888 ·
Neo4j Browser http://localhost:7474 · Mongo Express http://localhost:8081.

Apagar sin perder datos: `docker compose stop`. Borrar todo (datos incluidos): `docker compose down -v`.

## 2. Levantarlo en Google Cloud (entrega / video)

Mismo stack, misma secuencia. Los scripts de `gcp/` automatizan la VM:

```bash
# A) Cloud Shell (>_ en la consola) o laptop con gcloud:
git clone <URL-DE-ESTE-REPO> proyecto-bigdata && cd proyecto-bigdata
bash gcp/01_crear_vm.sh TU_PROJECT_ID          # VM Ubuntu 22.04 e2-standard-4 + Docker + firewall 8501

# B) Entrar a la VM:
bash gcp/02_tunel_ssh.sh TU_PROJECT_ID         # SSH + túneles a todos los puertos (ver tabla arriba)

# C) Dentro de la VM:
git clone <URL-DE-ESTE-REPO> proyecto-bigdata && cd proyecto-bigdata
bash gcp/04_setup_en_vm.sh                     # .env, grupo docker, build, up, init de las 3 BDs, carga inicial

# D) Al terminar de trabajar (control de costos):
bash gcp/03_apagar_encender.sh TU_PROJECT_ID stop     # start | status | delete
```

Dashboard público en `http://IP_EXTERNA:8501`. Airflow/Jupyter/Neo4j/Mongo solo por el túnel SSH
(no están expuestos a internet). Pasos manuales equivalentes (consola web) en `gcp/MANUAL.md`.

## 3. Cómo trabaja el sistema

Cada hora Airflow ejecuta el DAG `github_events_pipeline`. Una corrida procesa **una hora** de GH
Archive (la de `data_interval_start − GHARCHIVE_LAG_HOURS`): eso es la *actualización incremental*
del dataset. Los metadatos pasan de etapa en etapa por XCom (un `dict` con rutas y estadísticas).

| # | Tarea Airflow | Módulo | Qué hace | Escribe en |
|---|---|---|---|---|
| 1 | `extract_data` | `src/extract.py` | Descarga `https://data.gharchive.org/YYYY-MM-DD-H.json.gz` a `data/raw/` (idempotente: si existe no vuelve a bajar) | disco |
| 2 | `validate_and_clean` | `src/clean.py` | Valida campos obligatorios (`id, type, actor.login, repo.name, created_at`), parsea fecha, deduplica por id, recorta `payload` por tipo de evento, limita a `MAX_EVENTS_PER_RUN`; escribe `data/processed/*.clean.jsonl` + estadísticas de calidad | disco |
| 3 | `load_mongodb` | `src/load_mongo.py` | `bulk_write` de upserts con `_id` = id de GitHub (re-ejecutar no duplica). Registra la corrida en `ingestion_log` | MongoDB `events`, `ingestion_log` |
| 4 | `transform_load_cassandra` | `src/load_cassandra.py` | **Lee los eventos de la hora desde MongoDB** (`created_at` en [h, h+1), índice `ix_created_at`), los agrega en memoria y los suma en las tablas por consulta (`events_by_hour`, `repo_activity_by_day`, `user_activity_by_day`, `daily_totals`) y escribe los pares usuario→repo en `user_repo_interactions_by_hour`. Si la hora ya está en `pipeline_runs`, se omite (idempotencia) | Cassandra |
| 5 | `build_graph_neo4j` | `src/load_neo4j.py` | **Lee `user_repo_interactions_by_hour` de Cassandra** (una partición = la hora) y de cada fila deriva `(User)-[PUSHED|STARRED|FORKED|OPENED_ISSUE|OPENED_PR {count}]->(Repo)-[BELONGS_TO]->(Org)`; `MERGE` por lotes de 1000 con `UNWIND`. Marca `pipeline_runs.loaded_neo4j` | Neo4j |
| 6 | `generate_kpis` | `src/kpis.py` | Calcula 5 KPIs del día leyendo **las tres BDs** (3 de Cassandra, 1 de MongoDB, 1 de Neo4j) y los guarda en `kpis_by_date`; el dashboard solo lee | Cassandra |

`src/run_pipeline_local.py` ejecuta las mismas 6 funciones en secuencia sin Airflow (carga inicial,
carga histórica de un día completo, pruebas desde Jupyter).

**Arquitectura por capas (cada BD alimenta a la siguiente):** el archivo limpio solo se usa para
cargar MongoDB. A partir de ahí, Cassandra se construye **desde MongoDB** y Neo4j **desde Cassandra**;
los KPIs leen las tres. Así MongoDB es la única fuente de verdad (capa de documentos), Cassandra la capa
de agregados por tiempo y Neo4j la capa de relaciones; cualquier capa se puede reconstruir desde la anterior
(`scripts/backfill_interactions.py` es un ejemplo: rellena la tabla puente desde MongoDB).

## 4. Qué hace cada archivo

```
docker-compose.yml        define los 10 contenedores, redes, volúmenes, healthchecks y límites de RAM.
                          Sobrescribe MONGO_URI/CASSANDRA_HOST/NEO4J_URI con los nombres de servicio.
.env.example              variables de entorno (copiar a .env). Defaults locales listos para usar.
requirements.txt          drivers: pymongo, cassandra-driver, neo4j, requests, python-dotenv.
docker/
  Dockerfile.airflow      apache/airflow:2.10.5 + requirements.txt
  Dockerfile.jupyter      jupyter/minimal-notebook + requirements + plotly/pandas/matplotlib
  Dockerfile.dashboard    python:3.11-slim + requirements + streamlit/plotly/pandas
dags/github_events_dag.py DAG: 6 PythonOperator encadenados, @hourly, retries=3, max_active_runs=1.
src/
  config.py               lee .env / variables de entorno; fábricas de conexión mongo_db(),
                          cassandra_session(), neo4j_driver(). Único punto de configuración.
  extract.py              etapa 1 (descarga + iterador streaming del .json.gz)
  clean.py                etapa 2 (validación, dedupe, recorte, JSONL)
  load_mongo.py           etapa 3 (upsert masivo + retención opcional)
  load_cassandra.py       etapa 4 (lee MongoDB -> agregación + escritura concurrente + registro pipeline_runs)
  load_neo4j.py           etapa 5 (lee user_repo_interactions_by_hour de Cassandra -> aristas + MERGE por lotes)
  kpis.py                 etapa 6 (5 KPIs, >=1 por BD, con definición/fórmula/interpretación en el docstring)
  run_pipeline_local.py   las 6 etapas sin Airflow: `python run_pipeline_local.py [YYYY-MM-DD h0 [h1]]`
scripts/
  init_cassandra.cql      keyspace github_metrics + 7 tablas (query-first). Se ejecuta con cqlsh.
  backfill_interactions.py rellena user_repo_interactions_by_hour desde MongoDB para horas ya cargadas.
  init_mongo.py           colección events con validador $jsonSchema + 4 índices + ingestion_log.
  init_neo4j.cypher/.py   constraints de unicidad User.login, Repo.name, Org.login.
notebooks/
  01_exploracion_dataset  origen, estructura (payload variable por tipo), volumen, calidad.
  02_crud_mongodb         insert_one / find / aggregate / update_one / delete_one  (demo del video)
  03_crud_cassandra       INSERT / SELECT / UPDATE / DELETE en CQL                 (demo del video)
  04_crud_neo4j           MERGE nodo+relación / MATCH / SET / DELETE y DETACH DELETE (demo del video)
  05_kpis                 corre el pipeline manual y muestra los KPIs en un DataFrame.
dashboard/app.py          Streamlit: 5 stat-tiles de KPIs (con la BD fuente de cada uno) + pestañas Cassandra / Neo4j / MongoDB / doc.
gcp/
  01_crear_vm.sh          gcloud: VM + startup-script (instala Docker) + regla de firewall 8501.
  02_tunel_ssh.sh         gcloud compute ssh con -L para todos los puertos.
  03_apagar_encender.sh   stop / start / status / delete de la VM.
  04_setup_en_vm.sh       dentro de la VM: .env, grupo docker, build, up, init BDs, carga inicial.
data/raw, data/processed  archivos descargados y limpios (ignorados por git).
informe/                  PDF del informe y capturas del dashboard.
```

## 5. Modelo de datos y justificación (resumen para el informe)

**MongoDB — documento original.** El `payload` de GitHub cambia de forma según `type`
(PushEvent trae commits; IssuesEvent, issue; WatchEvent casi nada). Un esquema flexible con
validación solo de la cabecera (`_id, type, actor, repo, created_at`) es el ajuste natural. Índices en
`created_at`, `type`, `repo.name`, `actor.login`. Se usa el id de GitHub como `_id` → idempotencia.

**Cassandra — series temporales y agregados.** Diseño *query-first*: cada tabla responde a una
consulta del dashboard. `events_by_hour` (partición = día, clustering = hora/tipo),
`repo_activity_by_day`, `user_activity_by_day`, `user_repo_interactions_by_hour` (partición = día+hora;
tabla puente que alimenta a Neo4j), `daily_totals`, `kpis_by_date`, `pipeline_runs`.
Escrituras append-only masivas y lecturas por partición temporal: el caso de uso de Cassandra.
Se alimenta leyendo MongoDB, no el archivo: MongoDB es la fuente de verdad.

**Neo4j — relaciones.** `(:User)-[:PUSHED|STARRED|FORKED|OPENED_ISSUE|OPENED_PR {count}]->(:Repo)-[:BELONGS_TO]->(:Org)`,
construido desde `user_repo_interactions_by_hour` de Cassandra (cada fila = una arista con su contador).
"Repositorio con más usuarios distintos" o "usuarios que colaboran en los mismos repos" son recorridos
de grafo (1–2 saltos) que en un modelo relacional serían self-joins costosos. Constraints de unicidad
en `login`/`name` + `MERGE` → idempotencia.

## 6. KPIs implementados (`src/kpis.py`)

Cinco KPIs; cada base de datos aporta al menos uno (requisito: ≥5 indicadores con definición, fórmula e interpretación).

| # | KPI | BD fuente | Fórmula | Interpretación |
|---|---|---|---|---|
| 1 | Eventos procesados por día | Cassandra | Σ `events_by_hour.event_count` | Volumen ingerido; base de los demás |
| 2 | Crecimiento diario | Cassandra | (E(d) − E(d−1)) / E(d−1) × 100, mismas horas | >0: la actividad crece |
| 3 | Promedio de actividad por usuario | Cassandra | E(d) / `daily_totals.unique_users`(d) | Intensidad; valores altos = bots |
| 4 | Tasa de fusión de pull requests | MongoDB | merged(d) / (merged(d) + closed(d)) × 100 sobre `payload.action` | % de PRs resueltos que fueron aceptados; solo existe en el documento original |
| 5 | Entidad con más conexiones | Neo4j | `MATCH (u)-[]->(r) RETURN r, count(DISTINCT u) ORDER BY desc LIMIT 1` | Repo que concentra comunidad (o actividad automatizada) |

## 7. Operación

* **Volumen del dataset**: en 2026 GH Archive publica ~3–5k eventos/hora (~100–120k/día; hasta 2025 eran
  100k+/hora). El feed público de 2026 trae `PushEvent` de forma intermitente (p. ej. 35k el 8 nov, 0 el 10 nov).
  Para superar los 50,000 registros basta **un día completo**. Los archivos de 2025 son 10–30× más grandes.
* **Carga histórica** (~3 min por día de 2026):
  `docker compose exec jupyter bash -c "cd src && python run_pipeline_local.py 2026-11-09 0 23"`
* **Re-ejecutar una hora** es seguro: Mongo upsert por `_id`; Cassandra y Neo4j consultan
  `pipeline_runs` y omiten horas ya cargadas.
* **Reconstruir una capa**: Cassandra se regenera desde MongoDB y Neo4j desde Cassandra. Ejemplo para la
  tabla puente: `docker compose exec -T jupyter bash -c 'cd src && python ../scripts/backfill_interactions.py'`.
* **Ajustes** en `.env`: `MAX_EVENTS_PER_RUN`, `GHARCHIVE_LAG_HOURS`. `MONGO_RETENTION_HOURS` /
  `NEO4J_RETENTION_HOURS` (0 = sin borrado) solo hacen falta si se usa un tier gratuito en la nube.
* **Costos GCP**: `03_apagar_encender.sh stop` al terminar (VM apagada ≈ US$0.17/día). Alerta de
  presupuesto en Facturación → Presupuestos (p. ej. US$30). 6 días a 8 h/día ≈ US$10; 24/7 ≈ US$25.

## 8. Reparto sugerido para el video (20–25 min, todos participan)

1. Arquitectura + dataset (notebook 01) · 2. MongoDB: modelo + CRUD (notebook 02 + Mongo Express) ·
3. Cassandra: modelo + CRUD (notebook 03) · 4. Neo4j: modelo + CRUD (notebook 04 + Neo4j Browser) ·
5. Airflow: DAG corriendo en vivo + logs · 6. Dashboard + KPIs + conclusiones.

## Solución de problemas

* `cassandra` no pasa el healthcheck → esperar 1–2 min más; `docker logs cassandra`. Si falla por
  memoria: `sudo sysctl -w vm.max_map_count=1048575`.
* `neo4j` unhealthy → primera vez tarda ~40 s; `docker logs neo4j`. Si cambiaste `NEO4J_PASSWORD`
  después del primer arranque, la contraseña vieja sigue vigente (está en el volumen): `docker compose down -v`.
* Airflow no ve `src/` → `PYTHONPATH=/opt/airflow/src` está en compose; `docker compose restart airflow-scheduler`.
* Permisos en `data/` → `chmod -R a+rwX data`.
* `permission denied` con docker en la VM → salir y volver a entrar al SSH (grupo docker).
