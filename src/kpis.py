"""Etapa 6 - GENERACIÓN AUTOMÁTICA DE INDICADORES (KPIs)
Cada KPI tiene definición, fórmula e interpretación (requisito del informe).
Los resultados se guardan en Cassandra (kpis_by_date) y los lee el dashboard.

KPI 1  events_per_day        Nº de eventos procesados en el día.
       Fórmula: SUM(events_by_hour.event_count) WHERE event_date = D
       Interpretación: volumen de actividad ingerido; base de los demás KPIs.

KPI 2  daily_growth_pct      Crecimiento diario de eventos.
       Fórmula: (events(D) - events(D-1)) / events(D-1) * 100
       Interpretación: >0 la actividad crece respecto al día anterior.

KPI 3  top_repo_connections  Repositorio con mayor número de usuarios distintos conectados (grado en el grafo).
       Fórmula: MATCH (u:User)-[]->(r:Repo) RETURN r, count(DISTINCT u) ORDER BY desc LIMIT 1
       Interpretación: el proyecto que más comunidad concentra; candidato a "trending".

KPI 4  avg_events_per_user   Promedio de actividad por usuario.
       Fórmula: events(D) / unique_users(D)
       Interpretación: intensidad de uso; valores altos indican usuarios muy activos o bots.

KPI 5  push_share_pct        Participación de PushEvent en el total (tendencia de publicaciones).
       Fórmula: pushes(D) / events(D) * 100
       Interpretación: proporción de actividad de código real frente a social (stars/forks).

KPI 6  peak_hour             Hora pico del día.
       Fórmula: argmax_h SUM(event_count) WHERE event_date = D
       Interpretación: momento de mayor carga; útil para planificar ventanas de procesamiento.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from config import cassandra_session, neo4j_driver, NEO4J_DATABASE

log = logging.getLogger(__name__)


def _day_counts(s, d: date) -> Counter:
    c = Counter()
    for r in s.execute("SELECT event_hour, event_type, event_count FROM events_by_hour WHERE event_date=%s", (d,)):
        c[(r.event_hour, r.event_type)] = r.event_count
    return c


def compute_kpis(d: date) -> list[dict]:
    s = cassandra_session()
    today = _day_counts(s, d)
    yesterday = _day_counts(s, d - timedelta(days=1))

    events_today = sum(today.values())
    events_yesterday = sum(yesterday.values())
    pushes_today = sum(n for (h, t), n in today.items() if t == "PushEvent")
    by_hour = Counter()
    for (h, t), n in today.items():
        by_hour[h] += n
    peak_hour = by_hour.most_common(1)[0][0] if by_hour else -1

    row = s.execute("SELECT unique_users FROM daily_totals WHERE year=%s AND event_date=%s", (d.year, d)).one()
    unique_users = row.unique_users if row else 0

    growth = ((events_today - events_yesterday) / events_yesterday * 100) if events_yesterday else 0.0
    avg_per_user = events_today / unique_users if unique_users else 0.0
    push_share = pushes_today / events_today * 100 if events_today else 0.0

    top_repo, top_degree = "n/a", 0
    try:
        with neo4j_driver() as driver:
            rec = driver.execute_query(
                "MATCH (u:User)-[]->(r:Repo) RETURN r.name AS repo, count(DISTINCT u) AS degree "
                "ORDER BY degree DESC LIMIT 1", database_=NEO4J_DATABASE).records
            if rec:
                top_repo, top_degree = rec[0]["repo"], rec[0]["degree"]
    except Exception as exc:  # el KPI de grafo no debe tumbar la etapa
        log.warning("No se pudo consultar Neo4j: %s", exc)

    return [
        {"kpi_name": "events_per_day", "kpi_value": float(events_today), "kpi_label": "eventos"},
        {"kpi_name": "daily_growth_pct", "kpi_value": round(growth, 2), "kpi_label": f"vs {d - timedelta(days=1)}"},
        {"kpi_name": "top_repo_connections", "kpi_value": float(top_degree), "kpi_label": top_repo},
        {"kpi_name": "avg_events_per_user", "kpi_value": round(avg_per_user, 3), "kpi_label": f"{unique_users} usuarios"},
        {"kpi_name": "push_share_pct", "kpi_value": round(push_share, 2), "kpi_label": f"{pushes_today} pushes"},
        {"kpi_name": "peak_hour", "kpi_value": float(peak_hour), "kpi_label": f"{by_hour[peak_hour]} eventos" if peak_hour >= 0 else ""},
    ]


def save_kpis(d: date, kpis: list[dict]):
    s = cassandra_session()
    ins = s.prepare("INSERT INTO kpis_by_date (event_date, kpi_name, kpi_value, kpi_label, computed_at) VALUES (?,?,?,?,?)")
    now = datetime.now(timezone.utc)
    for k in kpis:
        s.execute(ins, (d, k["kpi_name"], k["kpi_value"], k["kpi_label"], now))


def generate_kpis(neo_meta: dict) -> dict:
    d = datetime.fromisoformat(neo_meta["hour"]).date()
    kpis = compute_kpis(d)
    save_kpis(d, kpis)
    log.info("KPIs %s: %s", d, {k["kpi_name"]: k["kpi_value"] for k in kpis})
    return {**neo_meta, "kpis": kpis}
