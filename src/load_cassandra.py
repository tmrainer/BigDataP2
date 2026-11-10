"""Etapa 4 - TRANSFORMACIÓN Y CARGA EN CASSANDRA
Fuente de datos: **MongoDB** (colección `events`, capa de documentos originales). Se leen los
eventos cuyo `created_at` cae dentro de la hora procesada y se agregan en las tablas
orientadas a consulta:
  events_by_hour, repo_activity_by_day, user_activity_by_day, daily_totals,
  user_repo_interactions_by_hour (pares usuario->repo por hora; de aquí se alimenta Neo4j).
Las tablas diarias se actualizan con read-modify-write (sumar al valor
existente) para que las corridas horarias acumulen el día completo.

Idempotencia: la tabla `pipeline_runs` actúa como registro de horas ya
procesadas. Si la hora ya tiene fila, la etapa se omite (un retry de Airflow o
un trigger manual no vuelve a sumar). Limitación: si la escritura falla a mitad
(antes de registrar la fila) el retry puede sumar dos veces la parte que alcanzó
a escribirse; para datos exactos en ese caso, borrar el día y recargarlo.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from cassandra.concurrent import execute_concurrent_with_args
from cassandra.query import UNSET_VALUE

from config import cassandra_session, mongo_db

log = logging.getLogger(__name__)

TYPE_TO_COL = {
    "PushEvent": "pushes",
    "WatchEvent": "stars",
    "ForkEvent": "forks",
    "IssuesEvent": "issues",
    "PullRequestEvent": "pull_requests",
}


# ------------------------------------------------------------ fuente: MongoDB
def read_events_from_mongo(hour: datetime) -> list[dict]:
    """Eventos de la hora [hour, hour+1h) leídos de MongoDB (índice ix_created_at).
    Solo se proyectan los campos que necesitan los agregados y el grafo."""
    if hour.tzinfo is None:
        hour = hour.replace(tzinfo=timezone.utc)
    cur = mongo_db().events.find(
        {"created_at": {"$gte": hour, "$lt": hour + timedelta(hours=1)}},
        {"type": 1, "actor.login": 1, "repo.name": 1, "org.login": 1, "created_at": 1},
    )
    events = []
    for e in cur:
        ts = e["created_at"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        e["created_at"] = ts
        events.append(e)
    return events


# ------------------------------------------------------------ registro de corridas
def get_pipeline_run(hour: datetime):
    """Fila de pipeline_runs para la hora, o None si nunca se procesó."""
    s = cassandra_session()
    return s.execute("SELECT * FROM pipeline_runs WHERE run_date=%s AND run_hour=%s",
                     (hour.date(), hour.hour)).one()


def log_pipeline_run(meta: dict, loaded_neo4j: int = 0):
    s = cassandra_session()
    hour = datetime.fromisoformat(meta["hour"])
    s.execute(
        "INSERT INTO pipeline_runs (run_date, run_hour, source_file, raw_count, clean_count, loaded_mongo, loaded_neo4j, finished_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (hour.date(), hour.hour, meta["source_file"], meta["stats"]["raw"], meta["stats"]["clean"],
         meta.get("mongo", {}).get("inserted", 0), loaded_neo4j, datetime.now(timezone.utc)),
    )


def mark_neo4j_loaded(hour: datetime, n_edges: int):
    s = cassandra_session()
    s.execute("UPDATE pipeline_runs SET loaded_neo4j=%s WHERE run_date=%s AND run_hour=%s",
              (n_edges, hour.date(), hour.hour))


# ------------------------------------------------------------ agregación
def aggregate(events: list[dict]) -> dict:
    by_hour = Counter()                       # (date, hour, type) -> n
    by_repo = defaultdict(Counter)            # (date, repo) -> Counter(col)
    by_user = Counter()                       # (date, login) -> n
    interactions = Counter()                  # (date, hour, login, repo, type) -> n
    inter_meta: dict = {}                     # misma clave -> (org_login, first_seen)
    users_by_day = defaultdict(set)
    repos_by_day = defaultdict(set)
    for e in events:
        d = e["created_at"].date()
        h = e["created_at"].hour
        t = e["type"]
        repo = e["repo"]["name"]
        user = e["actor"]["login"]
        by_hour[(d, h, t)] += 1
        by_repo[(d, repo)]["total_events"] += 1
        if t in TYPE_TO_COL:
            by_repo[(d, repo)][TYPE_TO_COL[t]] += 1
        by_user[(d, user)] += 1
        users_by_day[d].add(user)
        repos_by_day[d].add(repo)
        key = (d, h, user, repo, t)
        interactions[key] += 1
        if key not in inter_meta:
            inter_meta[key] = ((e.get("org") or {}).get("login"), e["created_at"])
    return {"by_hour": by_hour, "by_repo": by_repo, "by_user": by_user,
            "interactions": interactions, "inter_meta": inter_meta,
            "users_by_day": users_by_day, "repos_by_day": repos_by_day}


CONCURRENCY = 64   # peticiones en vuelo hacia Cassandra (60k eventos/h -> segundos en vez de minutos)


def _run_concurrent(session, stmt, params: list) -> list:
    """Ejecuta `stmt` para cada tupla de `params` en paralelo; devuelve resultados en el mismo orden."""
    out = []
    for ok, res in execute_concurrent_with_args(session, stmt, params, concurrency=CONCURRENCY):
        if not ok:
            raise res
        out.append(res)
    return out


def write_interactions(agg: dict) -> int:
    """user_repo_interactions_by_hour: una hora se procesa una sola vez -> INSERT directo."""
    s = cassandra_session()
    ins = s.prepare("INSERT INTO user_repo_interactions_by_hour "
                    "(event_date, event_hour, actor_login, repo_name, event_type, event_count, org_login, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?)")
    params = []
    for (d, h, user, repo, t), n in agg["interactions"].items():
        org, ts = agg["inter_meta"][(d, h, user, repo, t)]
        # UNSET_VALUE en vez de None: Cassandra no escribe tombstones por columnas ausentes
        params.append((d, h, user, repo, t, n, org or UNSET_VALUE, ts))
    _run_concurrent(s, ins, params)
    return len(params)


def write_aggregates(agg: dict) -> dict:
    s = cassandra_session()
    counts = Counter()

    # events_by_hour: una hora se procesa una sola vez -> sobrescribir es seguro
    ins_hour = s.prepare("INSERT INTO events_by_hour (event_date, event_hour, event_type, event_count) VALUES (?,?,?,?)")
    _run_concurrent(s, ins_hour, [(d, h, t, n) for (d, h, t), n in agg["by_hour"].items()])
    counts["events_by_hour"] = len(agg["by_hour"])

    # repo_activity_by_day: acumular sobre lo existente (lectura concurrente -> suma -> escritura concurrente)
    sel_repo = s.prepare("SELECT pushes, stars, forks, issues, pull_requests, total_events FROM repo_activity_by_day WHERE event_date=? AND repo_name=?")
    ins_repo = s.prepare("INSERT INTO repo_activity_by_day (event_date, repo_name, pushes, stars, forks, issues, pull_requests, total_events) VALUES (?,?,?,?,?,?,?,?)")
    cols = ["pushes", "stars", "forks", "issues", "pull_requests", "total_events"]
    repo_keys = list(agg["by_repo"].keys())
    prev_rows = _run_concurrent(s, sel_repo, repo_keys)
    ins_params = []
    for (d, repo), res in zip(repo_keys, prev_rows):
        row = res.one()
        prev = {k: (getattr(row, k) or 0) for k in cols} if row else {k: 0 for k in cols}
        c = agg["by_repo"][(d, repo)]
        ins_params.append((d, repo, *[prev[k] + c.get(k, 0) for k in cols]))
    _run_concurrent(s, ins_repo, ins_params)
    counts["repo_activity_by_day"] = len(ins_params)

    # user_activity_by_day
    sel_user = s.prepare("SELECT event_count FROM user_activity_by_day WHERE event_date=? AND actor_login=?")
    ins_user = s.prepare("INSERT INTO user_activity_by_day (event_date, actor_login, event_count) VALUES (?,?,?)")
    user_keys = list(agg["by_user"].keys())
    prev_rows = _run_concurrent(s, sel_user, user_keys)
    ins_params = []
    for (d, user), res in zip(user_keys, prev_rows):
        row = res.one()
        ins_params.append((d, user, (row.event_count if row else 0) + agg["by_user"][(d, user)]))
    _run_concurrent(s, ins_user, ins_params)
    counts["user_activity_by_day"] = len(ins_params)

    # user_repo_interactions_by_hour (fuente de la etapa 5 / Neo4j)
    counts["user_repo_interactions_by_hour"] = write_interactions(agg)

    # daily_totals: recalcular desde las tablas del día (exacto, no aproximado)
    ins_day = s.prepare("INSERT INTO daily_totals (year, event_date, total_events, unique_users, unique_repos) VALUES (?,?,?,?,?)")
    for d in agg["users_by_day"]:
        total = sum(r.event_count for r in s.execute("SELECT event_count FROM events_by_hour WHERE event_date=%s", (d,)))
        n_users = sum(1 for _ in s.execute("SELECT actor_login FROM user_activity_by_day WHERE event_date=%s", (d,)))
        n_repos = sum(1 for _ in s.execute("SELECT repo_name FROM repo_activity_by_day WHERE event_date=%s", (d,)))
        s.execute(ins_day, (d.year, d, total, n_users, n_repos))
        counts["daily_totals"] += 1
    return dict(counts)


def load_cassandra(mongo_meta: dict) -> dict:
    hour = datetime.fromisoformat(mongo_meta["hour"])
    if get_pipeline_run(hour) is not None:
        log.warning("Hora %s ya está en pipeline_runs: se omite la agregación para no duplicar conteos", hour)
        return {**mongo_meta, "cassandra": {"skipped": True}}
    events = read_events_from_mongo(hour)
    log.info("Cassandra: %d eventos leídos de MongoDB para la hora %s", len(events), hour)
    agg = aggregate(events)
    written = write_aggregates(agg)
    written["source_mongo_events"] = len(events)
    log_pipeline_run(mongo_meta)
    log.info("Cassandra: %s", written)
    return {**mongo_meta, "cassandra": written}
