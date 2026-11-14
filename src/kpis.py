"""Etapa 6 - GENERACIÓN AUTOMÁTICA DE INDICADORES (KPIs)
Cinco KPIs; cada uno tiene definición, fórmula e interpretación (requisito del informe) y
cada base de datos de la arquitectura aporta al menos uno:
  * Cassandra (series temporales / agregados): KPI 1, 2 y 3.
  * MongoDB  (documento original, campo `payload.action`): KPI 4.
  * Neo4j    (grafo usuario->repo): KPI 5.
Los resultados se guardan en Cassandra (kpis_by_date) y los lee el dashboard.

KPI 1  events_per_day        Nº de eventos procesados en el día.                       [Cassandra]
       Fórmula: SUM(events_by_hour.event_count) WHERE event_date = D
       Interpretación: volumen de actividad ingerido; base de los demás KPIs. La etiqueta guarda además
       el volumen de tipos estables (sin Push/Create/Delete, que GH Archive 2026 entrega de forma
       intermitente) y las horas con Push, para comparar días con distinta cobertura del feed.

KPI 2  daily_growth_pct      Crecimiento diario de eventos.                            [Cassandra]
       Fórmula: (S_H(D) - S_H(D-1)) / S_H(D-1) * 100, donde S cuenta solo los tipos ESTABLES
       (todos menos Push/Create/Delete, que el feed entrega de forma intermitente) y H son las
       horas cargadas en AMBOS días: así un hueco del feed no se lee como caída o subida de
       actividad. Sin datos de D-1 el KPI queda nulo (no 0 %).
       Interpretación: >0 la actividad crece respecto al día anterior.

KPI 3  avg_events_per_user   Promedio de actividad por usuario.                        [Cassandra]
       Fórmula: events(D) / daily_totals.unique_users(D)
       Interpretación: intensidad de uso; valores altos indican usuarios muy activos o bots.

KPI 4  pr_merge_rate_pct     Tasa de fusión de pull requests.                          [MongoDB]
       Fórmula: merged(D) / (merged(D) + closed(D)) * 100, donde merged/closed son los
       PullRequestEvent del día con payload.action = 'merged' / 'closed' (cerrado sin fusionar).
       Interpretación: de los PRs que se resolvieron en el día, qué porcentaje fue aceptado.
       Solo puede calcularse desde el documento original: Cassandra no guarda `payload.action`.

KPI 5  top_repo_connections  Repositorio con mayor número de usuarios distintos conectados. [Neo4j]
       Fórmula: MATCH (u:User)-[x]->(r:Repo) WHERE x.first_seen < fin(D)
                RETURN r, count(DISTINCT u) ORDER BY desc LIMIT 1   (grafo acumulado hasta el día D)
       Interpretación: el proyecto que más comunidad concentra; candidato a "trending"
       (o a actividad automatizada si el grado es anómalo).
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from config import cassandra_session, mongo_db, neo4j_driver, NEO4J_DATABASE

log = logging.getLogger(__name__)

KPI_SOURCE = {
    "events_per_day": "Cassandra",
    "daily_growth_pct": "Cassandra",
    "avg_events_per_user": "Cassandra",
    "pr_merge_rate_pct": "MongoDB",
    "top_repo_connections": "Neo4j",
}


# Tipos que el feed de GH Archive 2026 entrega de forma intermitente (aparecen y desaparecen juntos)
INTERMITTENT_TYPES = frozenset({"PushEvent", "CreateEvent", "DeleteEvent"})


def push_hours(counts: Counter) -> set[int]:
    return {h for (h, t), n in counts.items() if t == "PushEvent" and n}


def stable_by_hour(counts: Counter) -> Counter:
    """Eventos por hora sin los tipos intermitentes: la serie comparable entre días."""
    out = Counter({h: 0 for (h, t) in counts})
    for (h, t), n in counts.items():
        if t not in INTERMITTENT_TYPES:
            out[h] += n
    return out


def _day_counts(s, d: date) -> Counter:
    c = Counter()
    for r in s.execute("SELECT event_hour, event_type, event_count FROM events_by_hour WHERE event_date=%s", (d,)):
        c[(r.event_hour, r.event_type)] = r.event_count
    return c


def pr_actions_from_mongo(d: date) -> Counter:
    """Conteo de PullRequestEvent por payload.action en el día D (índice ix_type_date)."""
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    pipeline = [
        {"$match": {"type": "PullRequestEvent", "created_at": {"$gte": start, "$lt": start + timedelta(days=1)}}},
        {"$group": {"_id": "$payload.action", "n": {"$sum": 1}}},
    ]
    return Counter({(r["_id"] or "unknown"): r["n"] for r in mongo_db().events.aggregate(pipeline)})


def growth_kpi(s, d: date, today: Counter | None = None) -> dict:
    today = today if today is not None else _day_counts(s, d)
    prev = d - timedelta(days=1)
    st, sy = stable_by_hour(today), stable_by_hour(_day_counts(s, prev))
    common = sorted(set(st) & set(sy))
    events_today = sum(st[h] for h in common)
    events_yesterday = sum(sy[h] for h in common)
    if not events_yesterday:
        return {"kpi_name": "daily_growth_pct", "kpi_value": None, "kpi_label": f"sin datos de {prev}"}
    contiguous = common[-1] - common[0] + 1 == len(common)
    span = (f"hora {common[0]}" if len(common) == 1 else f"horas {common[0]}–{common[-1]}" if contiguous
            else f"{len(common)} horas comunes")
    growth = (events_today - events_yesterday) / events_yesterday * 100
    return {"kpi_name": "daily_growth_pct", "kpi_value": round(growth, 2), "kpi_label": f"vs {prev} ({span}, tipos estables)"}


def compute_kpis(d: date) -> list[dict]:
    s = cassandra_session()
    today = _day_counts(s, d)

    # --- Cassandra
    events_today = sum(today.values())
    stable = sum(n for (h, t), n in today.items() if t not in INTERMITTENT_TYPES)
    hours = {h for (h, t) in today}
    growth = growth_kpi(s, d, today)
    row = s.execute("SELECT unique_users FROM daily_totals WHERE year=%s AND event_date=%s", (d.year, d)).one()
    unique_users = row.unique_users if row else 0
    avg_per_user = events_today / unique_users if unique_users else 0.0

    # --- MongoDB
    merged = closed = 0
    try:
        acts = pr_actions_from_mongo(d)
        merged, closed = acts.get("merged", 0), acts.get("closed", 0)
    except Exception as exc:  # un KPI no debe tumbar la etapa
        log.warning("No se pudo consultar MongoDB: %s", exc)
    merge_rate = merged / (merged + closed) * 100 if (merged + closed) else 0.0

    # --- Neo4j: grafo acumulado hasta el final del día D (no el estado actual del grafo)
    top_repo, top_degree = "n/a", 0
    end = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)
    try:
        with neo4j_driver() as driver:
            rec = driver.execute_query(
                "MATCH (u:User)-[x]->(r:Repo) WHERE x.first_seen < datetime($end) "
                "RETURN r.name AS repo, count(DISTINCT u) AS degree ORDER BY degree DESC, repo LIMIT 1",
                end=end.isoformat(), database_=NEO4J_DATABASE).records
            if rec:
                top_repo, top_degree = rec[0]["repo"], rec[0]["degree"]
    except Exception as exc:
        log.warning("No se pudo consultar Neo4j: %s", exc)

    return [
        {"kpi_name": "events_per_day", "kpi_value": float(events_today),
         "kpi_label": f"eventos; {stable} estables; Push en {len(push_hours(today))}/{len(hours)} h"},
        growth,
        {"kpi_name": "avg_events_per_user", "kpi_value": round(avg_per_user, 3), "kpi_label": f"{unique_users} usuarios"},
        {"kpi_name": "pr_merge_rate_pct", "kpi_value": round(merge_rate, 2), "kpi_label": f"{merged} merged / {closed} cerrados sin fusionar"},
        {"kpi_name": "top_repo_connections", "kpi_value": float(top_degree), "kpi_label": top_repo},
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
