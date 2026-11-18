-- cassandra: keyspace y 7 tablas orientadas a consulta
-- uso: docker exec -i cassandra cqlsh < scripts/init_cassandra.cql

CREATE KEYSPACE IF NOT EXISTS github_metrics
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

USE github_metrics;

-- q1: eventos por tipo en cada hora de un dia
CREATE TABLE IF NOT EXISTS events_by_hour (
    event_date  date,
    event_hour  int,
    event_type  text,
    event_count int,
    PRIMARY KEY ((event_date), event_hour, event_type)
) WITH CLUSTERING ORDER BY (event_hour ASC, event_type ASC);

-- q2: actividad de cada repositorio en un dia
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

-- q3: eventos de cada usuario en un dia
CREATE TABLE IF NOT EXISTS user_activity_by_day (
    event_date   date,
    actor_login  text,
    event_count  int,
    PRIMARY KEY ((event_date), actor_login)
);

-- q4: interacciones usuario-repo por hora (fuente de la etapa 5)
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

-- q5: totales diarios
CREATE TABLE IF NOT EXISTS daily_totals (
    year         int,
    event_date   date,
    total_events int,
    unique_users int,
    unique_repos int,
    PRIMARY KEY ((year), event_date)
) WITH CLUSTERING ORDER BY (event_date DESC);

-- q6: kpis calculados por el dag
CREATE TABLE IF NOT EXISTS kpis_by_date (
    event_date   date,
    kpi_name     text,
    kpi_value    double,
    kpi_label    text,
    computed_at  timestamp,
    PRIMARY KEY ((event_date), kpi_name)
);

-- registro de corridas del pipeline
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
