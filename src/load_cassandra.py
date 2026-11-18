"""etapa 4: agrega los eventos de la hora (leidos de mongodb) en las tablas de cassandra.
todas las escrituras son valores absolutos: repetir una hora no duplica.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

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


# --- fuente: mongodb
def read_events_from_mongo(hour: datetime) -> list[dict]:
    """eventos de [hour, hour+1h) en mongodb, solo los campos necesarios."""
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


# --- registro de corridas
def get_pipeline_run(hour: datetime):
    """fila de pipeline_runs de la hora, o None."""
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


# --- agregacion
def aggregate(events: list[dict]) -> dict:
    by_hour = Counter()                       # (date, hour, type) -> n
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
        users_by_day[d].add(user)
        repos_by_day[d].add(repo)
        key = (d, h, user, repo, t)
        interactions[key] += 1
        if key not in inter_meta:
            inter_meta[key] = ((e.get("org") or {}).get("login"), e["created_at"])
    return {"by_hour": by_hour, "interactions": interactions, "inter_meta": inter_meta,
            "users_by_day": users_by_day, "repos_by_day": repos_by_day}


def day_activity_from_mongo(d: date, repos: list[str], users: list[str]) -> tuple[dict, dict]:
    """totales del dia en mongodb para esos repos y usuarios: ({repo: {col: n}}, {login: n})."""
    start = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    in_day = {"created_at": {"$gte": start, "$lt": start + timedelta(days=1)}}
    group = {"_id": "$repo.name", "total_events": {"$sum": 1}}
    for t, col in TYPE_TO_COL.items():
        group[col] = {"$sum": {"$cond": [{"$eq": ["$type", t]}, 1, 0]}}
    ev = mongo_db().events
    # hint: recorre solo el dia por ix_created_at
    opts = {"hint": "ix_created_at", "allowDiskUse": True}
    by_repo = {r["_id"]: r for r in ev.aggregate(
        [{"$match": {**in_day, "repo.name": {"$in": repos}}}, {"$group": group}], **opts)}
    by_user = {r["_id"]: r["n"] for r in ev.aggregate(
        [{"$match": {**in_day, "actor.login": {"$in": users}}},
         {"$group": {"_id": "$actor.login", "n": {"$sum": 1}}}], **opts)}
    return by_repo, by_user


CONCURRENCY = 64   # peticiones en vuelo hacia cassandra


def _run_concurrent(session, stmt, params: list) -> list:
    """ejecuta stmt por cada tupla en paralelo; resultados en el mismo orden."""
    out = []
    for ok, res in execute_concurrent_with_args(session, stmt, params, concurrency=CONCURRENCY):
        if not ok:
            raise res
        out.append(res)
    return out


def write_interactions(agg: dict) -> int:
    """escribe user_repo_interactions_by_hour."""
    s = cassandra_session()
    ins = s.prepare("INSERT INTO user_repo_interactions_by_hour "
                    "(event_date, event_hour, actor_login, repo_name, event_type, event_count, org_login, first_seen) "
                    "VALUES (?,?,?,?,?,?,?,?)")
    params = []
    for (d, h, user, repo, t), n in agg["interactions"].items():
        org, ts = agg["inter_meta"][(d, h, user, repo, t)]
        # UNSET_VALUE en vez de None: evita tombstones
        params.append((d, h, user, repo, t, n, org or UNSET_VALUE, ts))
    _run_concurrent(s, ins, params)
    return len(params)


def write_aggregates(agg: dict) -> dict:
    s = cassandra_session()
    counts = Counter()

    # events_by_hour: la clave incluye la hora -> sobrescribir es seguro
    ins_hour = s.prepare("INSERT INTO events_by_hour (event_date, event_hour, event_type, event_count) VALUES (?,?,?,?)")
    _run_concurrent(s, ins_hour, [(d, h, t, n) for (d, h, t), n in agg["by_hour"].items()])
    counts["events_by_hour"] = len(agg["by_hour"])

    # tablas diarias: total del dia recalculado en mongodb (valor absoluto)
    ins_repo = s.prepare("INSERT INTO repo_activity_by_day (event_date, repo_name, pushes, stars, forks, issues, pull_requests, total_events) VALUES (?,?,?,?,?,?,?,?)")
    ins_user = s.prepare("INSERT INTO user_activity_by_day (event_date, actor_login, event_count) VALUES (?,?,?)")
    cols = ["pushes", "stars", "forks", "issues", "pull_requests", "total_events"]
    for d in agg["users_by_day"]:
        repos, users = day_activity_from_mongo(d, list(agg["repos_by_day"][d]), list(agg["users_by_day"][d]))
        _run_concurrent(s, ins_repo, [(d, repo, *[r[k] for k in cols]) for repo, r in repos.items()])
        _run_concurrent(s, ins_user, [(d, user, n) for user, n in users.items()])
        counts["repo_activity_by_day"] += len(repos)
        counts["user_activity_by_day"] += len(users)

    # user_repo_interactions_by_hour: fuente de la etapa 5
    counts["user_repo_interactions_by_hour"] = write_interactions(agg)

    # daily_totals: recalculado desde las tablas del dia
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
        log.warning("Hora %s ya está en pipeline_runs: se omite la agregación", hour)
        return {**mongo_meta, "cassandra": {"skipped": True}}
    events = read_events_from_mongo(hour)
    log.info("Cassandra: %d eventos leídos de MongoDB para la hora %s", len(events), hour)
    agg = aggregate(events)
    written = write_aggregates(agg)
    written["source_mongo_events"] = len(events)
    log_pipeline_run(mongo_meta)
    log.info("Cassandra: %s", written)
    return {**mongo_meta, "cassandra": written}
