"""corre las 6 etapas sin airflow.

uso:
    python src/run_pipeline_local.py                   # hora mas reciente
    python src/run_pipeline_local.py 2026-11-09 14     # una hora (utc)
    python src/run_pipeline_local.py 2026-11-09 10 16  # rango de horas
"""
import logging
import sys
from datetime import datetime, timezone

from extract import extract, hour_to_process
from clean import clean
from load_mongo import load_mongo
from load_cassandra import load_cassandra
from load_neo4j import load_neo4j
from kpis import generate_kpis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def run_hour(hour: datetime):
    meta = extract(hour)
    meta = clean(meta)
    meta = load_mongo(meta)
    meta = load_cassandra(meta)
    meta = load_neo4j(meta)
    meta = generate_kpis(meta)
    print("\n=== KPIs", hour.date(), "===")
    for k in meta["kpis"]:
        value = "n/d" if k["kpi_value"] is None else k["kpi_value"]
        print(f"  {k['kpi_name']:<22} {value:>12}  {k['kpi_label']}")
    return meta


if __name__ == "__main__":
    if len(sys.argv) == 1:
        run_hour(hour_to_process())
    else:
        day = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        h0 = int(sys.argv[2])
        h1 = int(sys.argv[3]) if len(sys.argv) > 3 else h0
        for h in range(h0, h1 + 1):
            run_hour(day.replace(hour=h))
