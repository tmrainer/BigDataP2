"""etapa 6: calcula los 5 kpis del dia y los guarda en cassandra (kpis_by_date).

events_per_day        eventos del dia                                   cassandra
daily_growth_pct      variacion vs dia previo (tipos estables)          cassandra
avg_events_per_user   eventos / usuarios unicos                         cassandra
pr_merge_rate_pct     merged / (merged + closed) * 100                  mongodb
top_repo_connections  repo con mas usuarios distintos conectados        neo4j
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


# tipos que gh archive 2026 entrega de forma intermitente
INTERMITTENT_TYPES = frozenset({"PushEvent", "CreateEvent", "DeleteEvent"})


def push_hours(counts: Counter) -> set[int]:
    return {h for (h, t), n in counts.items() if t == "PushEvent" and n}


def stable_by_hour(counts: Counter) -> Counter:
    """eventos por hora sin los tipos intermitentes."""
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
    """conteo de PullRequestEvent por payload.action en el dia."""
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

    events_today = sum(today.values())
    stable = sum(n for (h, t), n in today.items() if t not in INTERMITTENT_TYPES)
    hours = {h for (h, t) in today}
    growth = growth_kpi(s, d, today)
    row = s.execute("SELECT unique_users FROM daily_totals WHERE year=%s AND event_date=%s", (d.year, d)).one()
    unique_users = row.unique_users if row else 0
    avg_per_user = events_today / unique_users if unique_users else 0.0

    merged = closed = 0
    try:
        acts = pr_actions_from_mongo(d)
        merged, closed = acts.get("merged", 0), acts.get("closed", 0)
    except Exception as exc:  # un kpi no debe tumbar la etapa
        log.warning("No se pudo consultar MongoDB: %s", exc)
    merge_rate = merged / (merged + closed) * 100 if (merged + closed) else 0.0

    # neo4j: grafo acumulado hasta el fin del dia
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
