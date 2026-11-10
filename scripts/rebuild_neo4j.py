"""Reconstruye la capa 3 (Neo4j) desde la capa 2 (Cassandra).

Vacía el grafo, pone pipeline_runs.loaded_neo4j = 0 en todas las horas y vuelve a ejecutar la
etapa 5 hora por hora leyendo user_repo_interactions_by_hour. Útil tras cambiar el tope de
eventos, el mapeo tipo->relación o si el grafo quedó inconsistente.
Uso: docker compose exec -T jupyter python scripts/rebuild_neo4j.py
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config                                   # noqa: E402
from load_neo4j import load_neo4j               # noqa: E402

logging.basicConfig(level=logging.WARNING)
s = config.cassandra_session()
hours = sorted((r.run_date.date(), r.run_hour) for r in s.execute("SELECT run_date, run_hour FROM pipeline_runs"))
print(f"{len(hours)} horas en pipeline_runs")

with config.neo4j_driver() as drv, drv.session(database=config.NEO4J_DATABASE) as sess:
    deleted = sess.run("MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 5000 ROWS").consume().counters.nodes_deleted
print(f"grafo vaciado: {deleted} nodos")
for d, h in hours:
    s.execute("UPDATE pipeline_runs SET loaded_neo4j=0 WHERE run_date=%s AND run_hour=%s", (d, h))

total = 0
for d, h in hours:
    hour = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
    meta = load_neo4j({"hour": hour.isoformat()})
    total += meta["neo4j"].get("edges", 0)
    print(f"{hour:%Y-%m-%d %H}h -> {meta['neo4j'].get('edges', 0)} aristas", flush=True)
print(f"reconstrucción lista: {total} aristas mergeadas")
