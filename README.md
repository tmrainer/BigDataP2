# Arquitectura multimodelo para eventos de GitHub

Proyecto Grupal II del curso de Big Data (UTEC).

Integrantes: Percy Castro, Jorge Martínez, Carla Molina, Leonardo Montesinos, Yitzhak Namihas.

## Qué hace

Cada hora el sistema descarga los eventos públicos de GitHub que publica GH Archive
(un archivo JSON comprimido por hora) y los reparte en tres bases NoSQL según el tipo de dato.
Un DAG de Apache Airflow orquesta todo el flujo y un dashboard en Streamlit lee las tres bases.

Al cierre del informe se habían procesado 1,056 archivos horarios (1 de octubre al 13 de
noviembre de 2026): 31.6 millones de eventos.

## Cómo funciona

```
GH Archive (un .json.gz por hora)
        |
        v
Airflow: DAG github_events_pipeline, cada hora
        |
        |  0. recover_missing_hours     repone horas recientes que no se cargaron
        |  1. extract_data              descarga el archivo de la hora
        |  2. validate_and_clean        valida, quita duplicados, recorta el payload
        |  3. load_mongodb              --> MongoDB    evento original
        |  4. transform_load_cassandra  --> Cassandra  agregados por hora y por día
        |  5. build_graph_neo4j         --> Neo4j      grafo usuario -> repo -> organización
        |  6. generate_kpis             --> Cassandra  5 KPIs del día
        v
Dashboard Streamlit y notebooks de CRUD
```

Las tres bases forman una cadena, no tres cargas paralelas: la etapa 4 lee los eventos de
MongoDB y la etapa 5 lee las interacciones de Cassandra. Cada capa se puede reconstruir desde
la anterior.

Por qué una base para cada cosa:

| Base | Qué guarda | Por qué |
|---|---|---|
| MongoDB | El evento original | El campo `payload` cambia de forma según el tipo de evento; un documento lo admite sin esquema fijo. |
| Cassandra | Conteos por hora y día, KPIs, registro de corridas | Series temporales: se escribe mucho y se lee por rango de fechas. Cada tabla responde una consulta del dashboard. |
| Neo4j | Usuarios, repositorios y organizaciones con sus relaciones | Preguntas como "qué repositorio conecta a más usuarios" son recorridos de grafo. |

Decisiones de diseño que conviene conocer:

- **Carga incremental.** Cada corrida procesa una sola hora nueva.
- **Idempotencia.** MongoDB usa el id del evento como `_id`, Cassandra escribe valores absolutos
  y Neo4j omite las horas ya cargadas. Repetir una hora no duplica nada.
- **Recuperación.** La tabla `pipeline_runs` registra cada hora procesada. Si Airflow estuvo
  detenido o una corrida falló, la tarea 0 detecta el hueco y lo repone.

## Indicadores

| KPI | Definición | Fuente |
|---|---|---|
| `events_per_day` | Eventos procesados en el día | Cassandra |
| `daily_growth_pct` | Variación frente al día anterior | Cassandra |
| `avg_events_per_user` | Eventos por usuario único | Cassandra |
| `pr_merge_rate_pct` | Pull requests fusionados sobre los resueltos | MongoDB |
| `top_repo_connections` | Repositorio con más usuarios distintos conectados | Neo4j |

Las fórmulas y su interpretación están en el informe y en cada ficha del dashboard.

## Guía de uso

Requisitos: Docker con Compose y unos 12 GB de RAM libres.

```bash
cp .env.example .env
mkdir -p data/raw data/processed && chmod -R a+rwX data

docker compose build
docker compose up -d          # esperar a que todos los servicios estén healthy

# esquemas de las tres bases
docker exec -i cassandra cqlsh < scripts/init_cassandra.cql
docker compose exec -T jupyter python scripts/init_mongo.py
docker compose exec -T jupyter python scripts/init_neo4j.py

# primera carga: la hora más reciente publicada
docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py'
```

Desde ese momento Airflow carga una hora nueva cada hora sin intervención.

Para cargar días anteriores:

```bash
# un día completo
docker compose exec jupyter bash -c 'cd src && python run_pipeline_local.py 2026-11-09 0 23'

# el rango definido en .env (BACKFILL_START_DATE y BACKFILL_END_DATE)
docker compose exec jupyter python scripts/backfill_days.py --parallel 3
```

Servicios una vez levantado el stack:

| Servicio | Dirección | Acceso |
|---|---|---|
| Dashboard | http://localhost:8501 | libre |
| Airflow | http://localhost:8080 | admin / admin |
| Jupyter | http://localhost:8888 | token `bigdata` |
| Neo4j Browser | http://localhost:7474 | neo4j / `NEO4J_PASSWORD` del `.env` |
| Mongo Express | http://localhost:8081 | libre |
| Cassandra Web | http://localhost:8083 | solo lectura |

Para desplegarlo en Google Cloud están los scripts de `gcp/` y el paso a paso en `gcp/MANUAL.md`.

## Estructura del repositorio

```
dags/        DAG de Airflow
src/         una etapa del pipeline por archivo, más config, KPIs y recuperación
scripts/     creación de esquemas y utilidades de carga histórica
notebooks/   exploración del dataset, CRUD en cada base y KPIs
dashboard/   aplicación Streamlit
docker/      imágenes de Airflow, Jupyter y dashboard
gcp/         despliegue en Google Cloud
informe/     informe técnico en LaTeX y PDF
```
