# Arquitectura multimodelo para eventos de GitHub

Proyecto Grupal II del curso de Big Data (UTEC).

Integrantes: Percy Castro, Jorge Martínez, Carla Molina, Leonardo Montesinos y Yitzhak Namihas.

## ¿Qué hace el proyecto?

Cada hora el sistema descarga los eventos públicos de GitHub que publica GH Archive
(un archivo JSON comprimido por hora) y los reparte en tres bases NoSQL según el tipo de dato.
Un DAG de Apache Airflow orquesta todo el flujo y un dashboard en Streamlit lee las tres bases.

El objetivo es analizar la actividad de usuarios y repositorios combinando documentos,
series temporales y relaciones de grafo. Los notebooks incluyen operaciones CRUD
(crear, leer, actualizar y eliminar) para cada base de datos.

Al cierre del informe se habían procesado 1 056 archivos horarios (del 1 de octubre al 13 de
noviembre de 2026), equivalentes a 31,6 millones de eventos.

## ¿Cómo funciona?

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

La limpieza valida los campos obligatorios, elimina eventos duplicados por identificador
y conserva los campos del `payload` utilizados en el análisis. Las fechas se procesan en
UTC; para interpretarlas en Lima, se restan cinco horas.

### ¿Por qué se utiliza una base de datos para cada tipo de información?

| Base | Qué guarda | Por qué |
|---|---|---|
| MongoDB | El evento original | El campo `payload` cambia de forma según el tipo de evento; un documento lo admite sin esquema fijo. |
| Cassandra | Conteos por hora y día, KPIs, registro de corridas | Series temporales: se escribe mucho y se lee por rango de fechas. Cada tabla responde una consulta del dashboard. |
| Neo4j | Usuarios, repositorios y organizaciones con sus relaciones | Preguntas como «¿Qué repositorio conecta a más usuarios?» se resuelven mediante recorridos de grafo. |

Decisiones de diseño que conviene conocer:

- **Carga incremental.** Cada corrida procesa una sola hora nueva.
- **Idempotencia.** MongoDB usa el id del evento como `_id`, Cassandra escribe valores absolutos
  y Neo4j omite las horas ya cargadas. Repetir una hora no duplica nada.
- **Recuperación.** La tabla `pipeline_runs` registra cada hora procesada. Si Airflow estuvo
  detenido o una corrida falló, la tarea 0 detecta el hueco y lo repone.
  Por defecto, revisa las últimas 72 horas y recupera hasta seis por ejecución; estos límites
  se ajustan en `.env`.

## Indicadores

| KPI | Definición | Fuente |
|---|---|---|
| `events_per_day` | Eventos procesados en el día | Cassandra |
| `daily_growth_pct` | Variación de los tipos estables frente al día anterior, sobre las horas cargadas en ambos días | Cassandra |
| `avg_events_per_user` | Eventos por usuario único | Cassandra |
| `pr_merge_rate_pct` | Porcentaje de pull requests fusionados entre los cerrados del día | MongoDB |
| `top_repo_connections` | Repositorio con más usuarios distintos conectados hasta el final del día | Neo4j |

Las fórmulas y su interpretación están en el informe y en cada ficha del dashboard.
Para comparar días, se debe revisar cuántas horas se han cargado. El crecimiento diario
excluye `PushEvent`, `CreateEvent` y `DeleteEvent`, cuya cobertura es intermitente en los datos
utilizados; si falta la base de comparación, se muestra como no disponible.

## Guía de uso

Requisitos: Docker con Compose y unos 12 GB de RAM libres.
Los comandos siguientes se ejecutan desde la raíz del repositorio en Bash (Linux, macOS o
WSL en Windows). El archivo `.env` contiene la configuración local de las bases y del pipeline.

```bash
cp .env.example .env
mkdir -p data/raw data/processed && chmod -R a+rwX data

docker compose build
docker compose up -d          # esperar a que todos los servicios estén healthy
docker compose ps

# esquemas de las tres bases
docker exec -i cassandra cqlsh < scripts/init_cassandra.cql
docker compose exec -T jupyter python scripts/init_mongo.py
docker compose exec -T jupyter python scripts/init_neo4j.py

# primera carga: la hora más reciente publicada
docker compose exec -T jupyter bash -c 'cd src && python run_pipeline_local.py'
```

En Airflow, verifica que el DAG `github_events_pipeline` esté activo. Desde ese momento,
carga una hora nueva cada hora sin intervención. Se aplica un retraso de publicación de
dos horas (`GHARCHIVE_LAG_HOURS=2`) antes de solicitar el archivo a GH Archive.

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

### ¿Cómo se consulta el dashboard?

Abre http://localhost:8501, selecciona la fecha de análisis y ajusta la cantidad de elementos
en los rankings. Las pestañas permiten consultar los resultados de cada base de datos y las
fichas explican la definición, fórmula e interpretación de los cinco indicadores.

- **Apariencia:** el interruptor «Modo oscuro», junto a los filtros, permite alternar entre
  el tema oscuro y el claro original.
- **Zoom:** usa la rueda del ratón o arrastra sobre una gráfica para ampliar una zona. Al
  pasar el cursor aparecen los controles para acercar, alejar y desplazar la vista. Un doble
  clic o el botón de restablecer devuelve la escala inicial.

Estas opciones solo cambian la visualización; los datos, indicadores y filtros de análisis
se mantienen.

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
