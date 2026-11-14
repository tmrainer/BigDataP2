"""Carga histórica por rango de días (configurable en .env).

Variables (.env):
    BACKFILL_START_DATE   primer día a cargar, YYYY-MM-DD (p. ej. 2026-10-01)
    BACKFILL_END_DATE     último día; vacío = hoy (UTC). Las horas aún no publicadas se omiten.
    MAX_EVENTS_PER_RUN    tope de eventos por hora (200000 = sin recorte en 2026)

Uso (dentro del contenedor jupyter, con src/ en PYTHONPATH):
    python scripts/backfill_days.py                          # rango del .env, secuencial
    python scripts/backfill_days.py --parallel 3             # 3 días a la vez (particiones distintas en Cassandra)
    python scripts/backfill_days.py --start 2026-10-05 --end 2026-10-07

Idempotente: una hora con fila en pipeline_runs y loaded_neo4j > 0 se salta; una hora a medias
se reintenta (cada etapa decide por sí sola qué omitir). Los días se procesan en paralelo, las
horas de un mismo día siempre en secuencia (los agregados diarios se recalculan con lo cargado hasta esa hora).
Airflow sigue encargándose del presente: este script es solo para el pasado.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402,F401  (carga .env)

log = logging.getLogger("backfill")


def _env_date(name: str, default: date) -> date:
    v = os.environ.get(name, "").strip()
    return datetime.strptime(v, "%Y-%m-%d").date() if v else default


def load_day(d: date) -> dict:
    """Carga las 24 horas de un día (en este proceso). Devuelve resumen."""
    import requests
    from extract import hour_to_process
    from load_cassandra import get_pipeline_run
    from run_pipeline_local import run_hour

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    last_published = hour_to_process()
    summary = {"day": str(d), "done": 0, "skipped": 0, "not_published": 0, "failed": []}
    t0 = time.time()
    for h in range(24):
        hour = datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc)
        if hour > last_published:
            summary["not_published"] += 1
            continue
        run = get_pipeline_run(hour)
        if run is not None and (run.loaded_neo4j or 0) > 0:
            summary["skipped"] += 1
            continue
        try:
            run_hour(hour)
            summary["done"] += 1
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                summary["not_published"] += 1
            else:
                summary["failed"].append(f"{h}: {exc}")
        except Exception as exc:  # seguir con las demás horas; se reintenta al relanzar
            summary["failed"].append(f"{h}: {exc}")
    summary["minutes"] = round((time.time() - t0) / 60, 1)
    return summary


def main():
    today = datetime.now(timezone.utc).date()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=date.fromisoformat, default=_env_date("BACKFILL_START_DATE", today))
    ap.add_argument("--end", type=date.fromisoformat, default=_env_date("BACKFILL_END_DATE", today))
    ap.add_argument("--parallel", type=int, default=1, help="días en paralelo (1 = secuencial)")
    args = ap.parse_args()
    if args.end > today:
        args.end = today
    days = [args.start + timedelta(days=i) for i in range((args.end - args.start).days + 1)]
    print(f"backfill {args.start} -> {args.end}: {len(days)} días, {args.parallel} en paralelo, "
          f"MAX_EVENTS_PER_RUN={config.MAX_EVENTS_PER_RUN}", flush=True)
    if args.parallel <= 1:
        results = [load_day(d) for d in days]
        for r in results:
            print(r, flush=True)
    else:
        results = []
        with ProcessPoolExecutor(max_workers=args.parallel) as ex:
            futs = {ex.submit(load_day, d): d for d in days}
            for f in as_completed(futs):
                r = f.result()
                results.append(r)
                print(r, flush=True)
    failed = [r for r in results if r["failed"]]
    print(f"listo: {sum(r['done'] for r in results)} horas cargadas, {sum(r['skipped'] for r in results)} ya estaban, "
          f"{sum(r['not_published'] for r in results)} no publicadas aún, {len(failed)} días con errores", flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
