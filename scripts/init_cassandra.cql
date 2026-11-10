-- =====================================================================
--  Cassandra: keyspace y 7 tablas orientadas a CONSULTA (query-first design)
--  Ejecutar:  docker exec -i cassandra cqlsh < scripts/init_cassandra.cql
--
--  Justificación: Cassandra se usa para series temporales y agregados
--  append-only con lecturas por rango de tiempo. Cada tabla responde a
--  una pregunta concreta del dashboard / un KPI. No hay JOINs.
-- =====================================================================

CREATE KEYSPACE IF NOT EXISTS github_metrics
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE github_metrics;

-- Q1: ¿Cuántos eventos de cada tipo hubo en cada hora de un día?
--     Partición por día -> todas las horas de un día en una sola partición (lectura rápida).
CREATE TABLE IF NOT EXISTS events_by_hour (
    event_date  date,
    event_hour  int,
    event_type  text,
    event_count int,
    PRIMARY KEY ((event_date), event_hour, event_type)
) WITH CLUSTERING ORDER BY (event_hour ASC, event_type ASC);

-- Q2: ¿Cuál es la actividad de cada repositorio en un día?
CREATE TABLE IF NOT EXISTS repo_activity_by_day (
    event_date   date,
    repo_name    text,
    pushes       int,
    stars        int,
    forks        int,
    issues       int,
    pull_requests int,
    total_events int,
    PRIMARY KEY ((event_date), repo_name)
);

-- Q3: ¿Cuántos eventos generó cada usuario en un día? (para promedio de actividad)
CREATE TABLE IF NOT EXISTS user_activity_by_day (
    event_date   date,
    actor_login  text,
    event_count  int,
    PRIMARY KEY ((event_date), actor_login)
);

-- Q4: ¿Qué hizo cada usuario sobre cada repositorio en una hora dada?
--     Partición por (día, hora). Es la FUENTE de la etapa 5: Neo4j construye sus aristas
--     (User)-[TIPO {count}]->(Repo) leyendo esta tabla, no el archivo ni MongoDB.
CREATE TABLE IF NOT EXISTS user_repo_interactions_by_hour (
    event_date   date,
    event_hour   int,
    actor_login  text,
    repo_name    text,
    event_type   text,
    event_count  int,
    org_login    text,
    first_seen   timestamp,
    PRIMARY KEY ((event_date, event_hour), actor_login, repo_name, event_type)
);

-- Q5: Totales diarios (para KPI de crecimiento día a día)
CREATE TABLE IF NOT EXISTS daily_totals (
    year         int,
    event_date   date,
    total_events int,
    unique_users int,
    unique_repos int,
    PRIMARY KEY ((year), event_date)
) WITH CLUSTERING ORDER BY (event_date DESC);

-- Q6: KPIs calculados por el DAG (etapa 6), leídos por el dashboard
CREATE TABLE IF NOT EXISTS kpis_by_date (
    event_date   date,
    kpi_name     text,
    kpi_value    double,
    kpi_label    text,
    computed_at  timestamp,
    PRIMARY KEY ((event_date), kpi_name)
);

-- Registro de corridas del pipeline (trazabilidad)
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_date     date,
    run_hour     int,
    source_file  text,
    raw_count    int,
    clean_count  int,
    loaded_mongo int,
    loaded_neo4j int,
    finished_at  timestamp,
    PRIMARY KEY ((run_date), run_hour)
);
