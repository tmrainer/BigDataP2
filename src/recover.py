"""repone las horas recientes sin corrida completa en pipeline_runs."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import requests

from config import cassandra_session, RECOVERY_WINDOW_HOURS, RECOVERY_MAX_HOURS

log = logging.getLogger(__name__)


def missing_hours(until: datetime, window_hours: int = RECOVERY_WINDOW_HOURS) -> list[datetime]:
    """horas de [until - window_hours, until) sin corrida completa, en orden."""
    s = cassandra_session()
    # el driver de cassandra no acepta el datetime de pendulum
    until = datetime.fromisoformat(until.isoformat())
    hours = [until - timedelta(hours=i) for i in range(window_hours, 0, -1)]
    done = set()
    for d in sorted({h.date() for h in hours}):
        for r in s.execute("SELECT run_hour, loaded_neo4j FROM pipeline_runs WHERE run_date=%s", (d,)):
            if (r.loaded_neo4j or 0) > 0:
                done.add((d, r.run_hour))
    return [h for h in hours if (h.date(), h.hour) not in done]


def recover_missing_hours(until: datetime, window_hours: int = RECOVERY_WINDOW_HOURS,
                          max_hours: int = RECOVERY_MAX_HOURS) -> dict:
    """repone hasta max_hours horas faltantes; un fallo queda para la corrida siguiente."""
    from kpis import compute_kpis, save_kpis
    from run_pipeline_local import run_hour

    missing = missing_hours(until, window_hours)
    summary = {"missing": len(missing), "recovered": [], "not_published": [], "failed": []}
    for hour in missing[:max_hours]:
        try:
            run_hour(hour)
            summary["recovered"].append(hour.isoformat())
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                summary["not_published"].append(hour.isoformat())
            else:
                log.error("No se pudo reponer la hora %s: %s", hour, exc)
                summary["failed"].append(hour.isoformat())
        except Exception as exc:
            log.error("No se pudo reponer la hora %s: %s", hour, exc)
            summary["failed"].append(hour.isoformat())

    # kpi 2 y 5 dependen de dias previos: recalcular las fechas posteriores
    if summary["recovered"]:
        s = cassandra_session()
        d = datetime.fromisoformat(summary["recovered"][0]).date() + timedelta(days=1)
        while d < until.date():
            if s.execute("SELECT event_date FROM daily_totals WHERE year=%s AND event_date=%s", (d.year, d)).one():
                save_kpis(d, compute_kpis(d))
            d += timedelta(days=1)
    log.info("Horas faltantes: %s", summary)
    return summary
