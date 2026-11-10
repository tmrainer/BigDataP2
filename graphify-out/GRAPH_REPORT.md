# Graph Report - proyecto-bigdata  (2026-11-10)

## Corpus Check
- 7 files · ~15,682 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 239 nodes · 516 edges · 12 communities (7 shown, 5 thin omitted)
- Extraction: 92% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 37 edges (avg confidence: 0.84)
- Token cost: 60,000 input · 4,000 output

## Community Hubs (Navigation)
- Arquitectura por capas y KPIs (README)
- DAG Airflow e imports
- Extracción y limpieza
- Carga Cassandra y Neo4j
- Stack Docker Compose
- Dashboard Streamlit
- Captura del dashboard de KPIs
- Script GCP: crear VM
- Script GCP: túnel SSH
- Script GCP: apagar/encender VM
- Script GCP: setup en VM

## God Nodes (most connected - your core abstractions)
1. `Cassandra 4.1 - capa 2: series temporales / agregados` - 19 edges
2. `Etapa 4: transform_load_cassandra` - 15 edges
3. `Dashboard KPIs screenshot (GitHub Events · Arquitectura multimodelo)` - 14 edges
4. `MongoDB 7 - capa 1: documentos (fuente de verdad)` - 13 edges
5. `cassandra_session()` - 12 edges
6. `Etapa 6: generate_kpis` - 12 edges
7. `x-airflow-common anchor` - 11 edges
8. `load_neo4j()` - 11 edges
9. `DAG github_events_pipeline (6 etapas, @hourly)` - 11 edges
10. `Etapa 5: build_graph_neo4j` - 11 edges

## Surprising Connections (you probably didn't know these)
- `Day selector (Día = 10 Nov 2026)` --references--> `kpis_for()`  [INFERRED]
  informe/dashboard_kpis.png → dashboard/app.py
- `Tab: MongoDB · documentos` --references--> `mongo_overview()`  [INFERRED]
  informe/dashboard_kpis.png → dashboard/app.py
- `KPI tile: Prom. eventos / usuario = 1.89` --references--> `tile()`  [INFERRED]
  informe/dashboard_kpis.png → dashboard/app.py
- `Chart: Distribución por tipo de evento (horizontal bars: PullRequestEvent 18,080; IssueCommentEvent 7,828; IssuesEvent 7,180; PullRequestReviewEvent 4,550; WatchEvent 3,585; ReleaseEvent 2,375; Other 1,414; ForkEvent 596; no PushEvent)` --references--> `hbar()`  [INFERRED]
  informe/dashboard_kpis.png → dashboard/app.py
- `Caption: 'KPIs calculados por Airflow a las 14:44 UTC · fuente: Cassandra kpis_by_date'` --references--> `kpis_for()`  [INFERRED]
  informe/dashboard_kpis.png → dashboard/app.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Cassandra time-series charts (hourly stacked area, event-type bars, daily trend)** — informe_dashboard_kpis_hourly_events_chart, informe_dashboard_kpis_event_type_distribution_chart, informe_dashboard_kpis_daily_trend_chart, informe_dashboard_kpis_cassandra_tab [EXTRACTED 1.00]
- **KPI stat row (6 tiles computed by Airflow, stored in Cassandra kpis_by_date)** — informe_dashboard_kpis_events_per_day_tile, informe_dashboard_kpis_daily_growth_tile, informe_dashboard_kpis_avg_events_per_user_tile, informe_dashboard_kpis_code_share_tile, informe_dashboard_kpis_peak_hour_tile, informe_dashboard_kpis_most_connected_repo_tile, informe_dashboard_kpis_kpis_by_date_table [EXTRACTED 1.00]
- **Per-database tab navigation (Cassandra / Neo4j / MongoDB / KPIs y arquitectura)** — informe_dashboard_kpis_cassandra_tab, informe_dashboard_kpis_neo4j_tab, informe_dashboard_kpis_mongodb_tab, informe_dashboard_kpis_kpis_architecture_tab, informe_dashboard_kpis_multimodel_architecture [EXTRACTED 1.00]
- **Services that consume the shared x-db-env (connect to the 3 databases by service name)** — docker_compose_db_env, docker_compose_airflow_common, docker_compose_jupyter, docker_compose_dashboard, docker_compose_mongo, docker_compose_cassandra, docker_compose_neo4j [EXTRACTED 1.00]
- **GCP deployment flow: create VM -> firewall -> SSH tunnel -> setup stack -> stop/start for cost control** — gcp_manual_bigdata_vm, gcp_manual_startup_script, gcp_manual_firewall_allow_dashboard_8501, gcp_manual_ssh_tunnel, gcp_manual_stack_setup_in_vm, gcp_manual_vm_lifecycle, gcp_manual_cost_control [EXTRACTED 1.00]
- **Pipeline github_events_pipeline de 6 etapas (extract -> clean -> Mongo -> Cassandra -> Neo4j -> KPIs)** — readme_extract_data, readme_validate_and_clean, readme_load_mongodb, readme_transform_load_cassandra, readme_build_graph_neo4j, readme_generate_kpis, readme_xcom_metadata [EXTRACTED 1.00]
- **Flujo por capas: MongoDB (capa 1) -> Cassandra (capa 2, user_repo_interactions_by_hour) -> Neo4j (capa 3) -> KPIs** — readme_mongodb, readme_cassandra, readme_user_repo_interactions_by_hour, readme_neo4j, readme_generate_kpis, readme_kpis_by_date, readme_layered_architecture [EXTRACTED 1.00]
- **Los 5 KPIs (3 Cassandra, 1 MongoDB, 1 Neo4j) calculados por generate_kpis y mostrados en el dashboard** — readme_kpi_events_per_day, readme_kpi_daily_growth_pct, readme_kpi_avg_events_per_user, readme_kpi_pr_merge_rate_pct, readme_kpi_top_repo_connections, readme_generate_kpis, readme_streamlit_dashboard [EXTRACTED 1.00]

## Communities (12 total, 5 thin omitted)

### Community 0 - "Arquitectura por capas y KPIs (README)"
Cohesion: 0.12
Nodes (38): Apache Airflow 2.10 (orquestador), scripts/backfill_interactions.py (rellena tabla puente desde MongoDB), Etapa 5: build_graph_neo4j, Cassandra 4.1 - capa 2: series temporales / agregados, Tabla daily_totals (Cassandra), dashboard/app.py (Streamlit), docker-compose.yml (10 contenedores, un solo host), Tabla events_by_hour (Cassandra) (+30 more)

### Community 1 - "DAG Airflow e imports"
Cohesion: 0.09
Nodes (15): _kpis(), _mongo(), _neo4j(), Cassandra table kpis_by_date (KPI source), mongo_client(), mongo_db(), compute_kpis(), _day_counts() (+7 more)

### Community 2 - "Extracción y limpieza"
Cohesion: 0.10
Nodes (14): _clean(), _extract(), clean(), clean_events(), parse_ts(), read_processed(), trim_payload(), validate_event() (+6 more)

### Community 3 - "Carga Cassandra y Neo4j"
Cohesion: 0.12
Nodes (17): _cassandra(), cassandra_session(), neo4j_driver(), aggregate(), get_pipeline_run(), load_cassandra(), log_pipeline_run(), mark_neo4j_loaded() (+9 more)

### Community 4 - "Stack Docker Compose"
Cohesion: 0.11
Nodes (24): x-airflow-common anchor, service airflow-init (db migrate + admin user), service airflow-scheduler, service airflow-webserver (8080), service cassandra (cassandra:4.1), service dashboard (Streamlit 8501, public), x-db-env anchor (shared DB connection env), service jupyter (8888) (+16 more)

### Community 5 - "Dashboard Streamlit"
Cohesion: 0.17
Nodes (11): available_dates(), daily_totals(), events_by_hour(), graph_neighbors(), graph_stats(), graph_top_connected(), hbar(), kpis_for() (+3 more)

### Community 6 - "Captura del dashboard de KPIs"
Cohesion: 0.16
Nodes (20): tile(), Dashboard KPIs screenshot (GitHub Events · Arquitectura multimodelo), KPI tile: Prom. eventos / usuario = 1.89, Tab: Cassandra · series temporales (active), KPI tile: Actividad de código (PR+push) = 39.6 %, KPI tile: Crecimiento diario = -25.6 %, Chart: Tendencia diaria de eventos procesados (line, 3 points declining ~120k -> ~97k -> ~45k), Day selector (Día = 10 Nov 2026) (+12 more)

## Ambiguous Edges - Review These
- `KPI tile: Repo más conectado = 116 usuarios` → `Repository 'morluto/rea' (most connected repo caption; small text, reading uncertain)`  [AMBIGUOUS]
  informe/dashboard_kpis.png · relation: references
- `Tab: Neo4j · grafo` → `Top N repositorios slider (value 10)`  [AMBIGUOUS]
  informe/dashboard_kpis.png · relation: conceptually_related_to

## Knowledge Gaps
- **7 isolated node(s):** `service mongo-express (UI 8081)`, `service postgres (Airflow metadata)`, `python-dotenv==1.0.1`, `Tab: KPIs y arquitectura`, `Repository 'morluto/rea' (most connected repo caption; small text, reading uncertain)` (+2 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 61 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `service dashboard (Streamlit 8501, public)` connect `Stack Docker Compose` to `Dashboard Streamlit`?**
  _High betweenness centrality (0.078) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `Etapa 4: transform_load_cassandra` (e.g. with `read_events_from_mongo()` and `write_interactions()`) actually correct?**
  _`Etapa 4: transform_load_cassandra` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `service mongo-express (UI 8081)`, `service postgres (Airflow metadata)`, `python-dotenv==1.0.1` to the rest of the system?**
  _7 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Arquitectura por capas y KPIs (README)` be split into smaller, more focused modules?**
  _Cohesion score 0.1173054587688734 - nodes in this community are weakly interconnected._
- **Why does `src/run_pipeline_local.py (6 etapas sin Airflow)` connect `Arquitectura por capas y KPIs (README)` to `DAG Airflow e imports`, `Stack Docker Compose`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `KPI tile: Repo más conectado = 116 usuarios` and `Repository 'morluto/rea' (most connected repo caption; small text, reading uncertain)`?**
  _Edge tagged AMBIGUOUS (relation: references) - confidence is low._
- **What is the exact relationship between `Tab: Neo4j · grafo` and `Top N repositorios slider (value 10)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._