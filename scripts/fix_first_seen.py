"""repara first_seen en un grafo cargado fuera de orden: deja la menor fecha observada.
uso: docker compose exec -T jupyter python scripts/fix_first_seen.py
despues: python scripts/recompute_kpis.py --all
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config                                             # noqa: E402
from load_neo4j import BATCH, build_edges, read_interactions   # noqa: E402

FIX = """
UNWIND $rows AS row
MATCH (:User {login: row.user})-[rel:%s]->(:Repo {name: row.repo})
WHERE rel.first_seen IS NULL OR rel.first_seen > datetime(row.ts)
SET rel.first_seen = datetime(row.ts)
"""

s = config.cassandra_session()
hours = sorted((r.run_date.date(), r.run_hour) for r in s.execute("SELECT run_date, run_hour FROM pipeline_runs"))
print(f"{len(hours)} horas en pipeline_runs")

total = 0
with config.neo4j_driver() as driver:
    for d, h in hours:
        hour = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
        by_rel, _ = build_edges(read_interactions(hour))
        fixed = 0
        for rel, rows in by_rel.items():
            for i in range(0, len(rows), BATCH):
                res = driver.execute_query(FIX % rel, rows=rows[i:i + BATCH], database_=config.NEO4J_DATABASE)
                fixed += res.summary.counters.properties_set
        total += fixed
        if fixed:
            print(f"{hour:%Y-%m-%d %H}h -> {fixed} aristas corregidas", flush=True)
print(f"listo: {total} aristas con first_seen corregido")
