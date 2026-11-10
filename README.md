# Proyecto Grupal II · Big Data · Arquitectura multimodelo en Google Cloud

Pipeline de **GitHub Events** (GH Archive) orquestado con **Apache Airflow**, almacenado en
**MongoDB Atlas** (documentos), **Cassandra** (series temporales) y **Neo4j AuraDB** (grafo),
con **dashboard Streamlit**. Diseñado para la **prueba gratuita de Google Cloud (US$300)**.

```
                 ┌──────────────── VM Compute Engine e2-standard-4 (us-central1) ────────────────┐
 GH Archive ───► │ Airflow DAG (6 etapas)  ──► Cassandra (docker)   JupyterLab (docker)  Streamlit │ ◄── navegador
 (JSON/hora)     │        │                                                                      │   (túnel SSH / :8501)
                 └────────┼──────────────────────────────────────────────────────────────────────┘
                          ├──► MongoDB Atlas Free  (SaaS, región GCP us-central1)
                          └──► Neo4j AuraDB Free   (SaaS)
```

| Componente | Dónde corre | Costo |
|---|---|---|
| Airflow 2.10 + Postgres | Docker en la VM | incluido en la VM |
| Cassandra 4.1 | Docker en la VM | incluido en la VM |
| JupyterLab | Docker en la VM | incluido en la VM |
| Streamlit | Docker en la VM (puerto 8501 público) | incluido en la VM |
| MongoDB Atlas | SaaS (mongodb.com), tier Free 0.5 GB | US$0 |
| Neo4j AuraDB | SaaS (console.neo4j.io), tier Free 200k nodos / 400k rel. | US$0 |
| VM e2-standard-4 + 50 GB | Compute Engine | ≈ US$0.13/h encendida (≈ US$3/día) |

> **Por qué no Cloud Composer:** es Airflow administrado por Google, pero factura 24/7 sin posibilidad
> de pausa (≈ US$6–12/día para un entorno pequeño) y tarda ~25 min en crearse. Con la cuenta de prueba
> es viable, pero Docker en la VM da el mismo DAG por una fracción del costo. Si el grupo quiere
> mostrarlo, créenlo el día del video y bórrenlo después. Nota: la cuenta de prueba **no permite
> usar Google Cloud Marketplace**, por eso Atlas y Aura se registran directamente en sus webs.

---

## 0. Requisitos previos (10 min)

1. **Google Cloud**: cuenta con la prueba de US$300 activa y un proyecto creado (anota el `PROJECT_ID`).
2. **MongoDB Atlas** → https://cloud.mongodb.com → *Build a Database* → **Free** → proveedor **Google Cloud**,
   región **Iowa (us-central1)** → crea usuario/contraseña de BD → *Connect → Drivers → Python* → copia la URI.
3. **Neo4j AuraDB** → https://console.neo4j.io → *New instance* → **Free** → descarga el archivo `.txt`
   de credenciales (URI `neo4j+s://...`, usuario, contraseña).
4. `gcloud` instalado en tu laptop **o** usar **Cloud Shell** desde la consola (ícono `>_` arriba a la derecha).

## 1. Crear la VM (5 min)

```bash
git clone <URL-DE-ESTE-REPO> proyecto-bigdata && cd proyecto-bigdata
bash gcp/01_crear_vm.sh TU_PROJECT_ID
```
El script crea `bigdata-vm` (Ubuntu 22.04, Docker preinstalado vía startup-script), abre **solo** el
puerto 8501 y muestra la **IP externa**. Copia esa IP y agrégala en Atlas → *Network Access → Add IP Address*.
(Si la VM se apaga y enciende, la IP puede cambiar: repetir este paso o usar `0.0.0.0/0` solo durante la demo.)

## 2. Entrar a la VM y levantar el stack (15 min la primera vez)

```bash
bash gcp/02_tunel_ssh.sh TU_PROJECT_ID        # abre SSH + túneles 8888/8080/8501
# --- dentro de la VM ---
git clone <URL-DE-ESTE-REPO> proyecto-bigdata && cd proyecto-bigdata
cp .env.example .env && nano .env               # pegar MONGO_URI, NEO4J_URI, NEO4J_PASSWORD
bash gcp/04_setup_en_vm.sh
```
El script: construye imágenes, levanta Cassandra/Postgres/Airflow/Jupyter/Streamlit, ejecuta
`scripts/init_cassandra.cql`, `scripts/init_mongo.py`, `scripts/init_neo4j.py` y hace una **carga inicial**.

Con el túnel abierto, en tu navegador:

| Servicio | URL | Acceso |
|---|---|---|
| Airflow | http://localhost:8080 | admin / admin |
| JupyterLab | http://localhost:8888 | token `bigdata` |
| Dashboard | http://localhost:8501 o `http://IP_EXTERNA:8501` | público |

## 3. Operar el pipeline

* **Airflow**: el DAG `github_events_pipeline` corre **cada hora** (`@hourly`) y procesa la hora
  `ahora − 2 h` de GH Archive. Para disparar manualmente: botón ▶ *Trigger DAG*.
* **Carga histórica** (superar 50,000 registros rápido, p. ej. un día completo):
  ```bash
  docker compose exec jupyter bash -c "cd src && python run_pipeline_local.py 2026-11-09 0 23"
  ```
* **Ajustes** en `.env`: `MAX_EVENTS_PER_RUN` (60,000 por defecto; Atlas Free = 0.5 GB ≈ 1–1.5 M
  documentos recortados), `GHARCHIVE_LAG_HOURS`.

## 4. Estructura del repositorio

```
docker-compose.yml        stack completo (Cassandra, Postgres, Airflow x3, Jupyter, Dashboard)
docker/                   Dockerfiles (airflow / jupyter / dashboard)
dags/github_events_dag.py DAG de 6 etapas
src/
  config.py               conexiones a las 3 BDs desde variables de entorno
  extract.py              1. descarga GH Archive (incremental por hora)
  clean.py                2. validación, deduplicación, recorte de payload
  load_mongo.py           3. upsert en Atlas (idempotente por _id)
  load_cassandra.py       4. agregados por hora/día (read-modify-write)
  load_neo4j.py           5. MERGE de relaciones Usuario->Repo por lotes
  kpis.py                 6. 6 KPIs con definición / fórmula / interpretación
  run_pipeline_local.py   ejecutar las 6 etapas sin Airflow
scripts/                  init_cassandra.cql · init_mongo.py · init_neo4j.cypher/.py
notebooks/                01 exploración · 02/03/04 CRUD (demo del video) · 05 KPIs
dashboard/app.py          Streamlit conectado a las 3 BDs
gcp/                      scripts gcloud: crear VM, túnel, apagar/encender, setup
informe/                  (poner aquí el PDF y capturas)
```

## 5. Modelo de datos y justificación (resumen para el informe)

**MongoDB — documento original.** El `payload` de GitHub cambia de forma según `type`
(PushEvent trae commits; IssuesEvent, issue; WatchEvent casi nada). Un esquema flexible con
validación solo de la cabecera (`_id, type, actor, repo, created_at`) es el ajuste natural. Índices en
`created_at`, `type`, `repo.name`, `actor.login`. Se usa el id de GitHub como `_id` → idempotencia.

**Cassandra — series temporales y agregados.** Diseño *query-first*: cada tabla responde a una
consulta del dashboard. `events_by_hour` (partición = día, clustering = hora/tipo),
`repo_activity_by_day`, `user_activity_by_day`, `daily_totals`, `kpis_by_date`, `pipeline_runs`.
Escrituras append-only masivas y lecturas por partición temporal: el caso de uso de Cassandra.

**Neo4j — relaciones.** `(:User)-[:PUSHED|STARRED|FORKED|OPENED_ISSUE|OPENED_PR {count}]->(:Repo)-[:BELONGS_TO]->(:Org)`.
"Repositorio con más usuarios distintos" o "usuarios que colaboran en los mismos repos" son recorridos
de grafo (1–2 saltos) que en un modelo relacional serían self-joins costosos. Constraints de unicidad
en `login`/`name` + `MERGE` → idempotencia.

## 6. KPIs implementados (`src/kpis.py`)

| KPI | Fórmula | Interpretación |
|---|---|---|
| Eventos procesados por día | Σ `events_by_hour.event_count` | Volumen ingerido |
| Crecimiento diario | (E(d) − E(d−1)) / E(d−1) × 100 | >0: la actividad crece |
| Entidad con más conexiones | `MATCH (u)-[]->(r) RETURN r, count(DISTINCT u)` | Repo que concentra comunidad |
| Promedio de actividad por usuario | E(d) / usuarios únicos(d) | Intensidad; detecta bots |
| Tendencia de publicaciones (pushes) | pushes(d) / E(d) × 100 | Código vs. actividad social |
| Hora pico | argmax_h Σ event_count | Ventana de mayor carga |

## 7. Control de costos (importante con la prueba gratuita)

```bash
bash gcp/03_apagar_encender.sh TU_PROJECT_ID stop     # al terminar de trabajar (~US$0.10/día solo disco)
bash gcp/03_apagar_encender.sh TU_PROJECT_ID start    # al retomar (contenedores arrancan solos)
bash gcp/03_apagar_encender.sh TU_PROJECT_ID delete   # al terminar el curso
```
Configura además una **alerta de presupuesto** en *Facturación → Presupuestos y alertas* (p. ej. US$50).
La VM encendida 24/7 toda la semana ≈ US$22; apagándola de noche ≈ US$12.

## 8. Reparto sugerido para el video (20–25 min, todos participan)

1. Arquitectura + dataset + VM en GCP (notebook 01) · 2. MongoDB: modelo + CRUD (notebook 02) ·
3. Cassandra: modelo + CRUD (notebook 03) · 4. Neo4j: modelo + CRUD (notebook 04) ·
5. Airflow: DAG corriendo en vivo + logs · 6. Dashboard + KPIs + conclusiones.

## Solución de problemas

* `cassandra` no pasa el healthcheck → esperar 1–2 min más; ver `docker logs cassandra`. Si falla
  por memoria: `sudo sysctl -w vm.max_map_count=1048575`.
* Airflow no ve `src/` → el `PYTHONPATH=/opt/airflow/src` está en compose; reiniciar `airflow-scheduler`.
* `ServerSelectionTimeoutError` (Atlas) → la IP de la VM no está en *Network Access*.
* `Neo4j: Unable to retrieve routing information` → URI debe ser `neo4j+s://…`; instancia Free pausada → *Resume* en la consola.
* Permisos en `data/` → `chmod -R a+rwX data`.
