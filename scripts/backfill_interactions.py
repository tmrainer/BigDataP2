"""rellena user_repo_interactions_by_hour desde mongodb para horas ya cargadas.
uso: docker compose exec -T jupyter bash -c 'cd src && python ../scripts/backfill_interactions.py'
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import cassandra_session                       # noqa: E402
from load_cassandra import read_events_from_mongo, aggregate, write_interactions   # noqa: E402

logging.basicConfig(level=logging.WARNING)
s = cassandra_session()
hours = sorted((r.run_date.date(), r.run_hour) for r in s.execute("SELECT run_date, run_hour FROM pipeline_runs"))
done = skipped = 0
for d, h in hours:
    if s.execute("SELECT actor_login FROM user_repo_interactions_by_hour WHERE event_date=%s AND event_hour=%s LIMIT 1", (d, h)).one():
        skipped += 1
        continue
    hour = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
    n = write_interactions(aggregate(read_events_from_mongo(hour)))
    done += 1
    print(f"{hour:%Y-%m-%d %H}h -> {n} filas")
print(f"backfill listo: {done} horas escritas, {skipped} ya existían")
