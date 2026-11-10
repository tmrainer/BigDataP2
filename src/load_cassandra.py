"""Etapa 4 - TRANSFORMACIÓN Y CARGA EN CASSANDRA
Agrega el lote horario en las tablas orientadas a consulta:
  events_by_hour, repo_activity_by_day, user_activity_by_day, daily_totals.
Las tablas diarias se actualizan con read-modify-write (sumar al valor
existente) para que las corridas horarias acumulen el día completo.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from config import cassandra_session

log = logging.getLogger(__name__)

TYPE_TO_COL = {
    "PushEvent": "pushes",
    "WatchEvent": "stars",
    "ForkEvent": "forks",
    "IssuesEvent": "issues",
    "PullRequestEvent": "pull_requests",
}


def aggregate(events: list[dict]) -> dict:
    by_hour = Counter()                       # (date, hour, type) -> n
    by_repo = defaultdict(Counter)            # (date, repo) -> Counter(col)
    by_user = Counter()                       # (date, login) -> n
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
    return {"by_hour": by_hour, "by_repo": by_repo, "by_user": by_user,
            "users_by_day": users_by_day, "repos_by_day": repos_by_day}


def write_aggregates(agg: dict) -> dict:
    s = cassandra_session()
    counts = Counter()

    # events_by_hour: una hora se procesa una sola vez -> sobrescribir es seguro
    ins_hour = s.prepare("INSERT INTO events_by_hour (event_date, event_hour, event_type, event_count) VALUES (?,?,?,?)")
    for (d, h, t), n in agg["by_hour"].items():
        s.execute(ins_hour, (d, h, t, n))
        counts["events_by_hour"] += 1

    # repo_activity_by_day: acumular sobre lo existente
    sel_repo = s.prepare("SELECT pushes, stars, forks, issues, pull_requests, total_events FROM repo_activity_by_day WHERE event_date=? AND repo_name=?")
    ins_repo = s.prepare("INSERT INTO repo_activity_by_day (event_date, repo_name, pushes, stars, forks, issues, pull_requests, total_events) VALUES (?,?,?,?,?,?,?,?)")
    cols = ["pushes", "stars", "forks", "issues", "pull_requests", "total_events"]
    for (d, repo), c in agg["by_repo"].items():
        row = s.execute(sel_repo, (d, repo)).one()
        prev = {k: (getattr(row, k) or 0) for k in cols} if row else {k: 0 for k in cols}
        s.execute(ins_repo, (d, repo, *[prev[k] + c.get(k, 0) for k in cols]))
        counts["repo_activity_by_day"] += 1

    # user_activity_by_day
    sel_user = s.prepare("SELECT event_count FROM user_activity_by_day WHERE event_date=? AND actor_login=?")
    ins_user = s.prepare("INSERT INTO user_activity_by_day (event_date, actor_login, event_count) VALUES (?,?,?)")
    for (d, user), n in agg["by_user"].items():
        row = s.execute(sel_user, (d, user)).one()
        s.execute(ins_user, (d, user, (row.event_count if row else 0) + n))
        counts["user_activity_by_day"] += 1

    # daily_totals: recalcular desde las tablas del día (exacto, no aproximado)
    ins_day = s.prepare("INSERT INTO daily_totals (year, event_date, total_events, unique_users, unique_repos) VALUES (?,?,?,?,?)")
    for d in agg["users_by_day"]:
        total = sum(r.event_count for r in s.execute("SELECT event_count FROM events_by_hour WHERE event_date=%s", (d,)))
        n_users = sum(1 for _ in s.execute("SELECT actor_login FROM user_activity_by_day WHERE event_date=%s", (d,)))
        n_repos = sum(1 for _ in s.execute("SELECT repo_name FROM repo_activity_by_day WHERE event_date=%s", (d,)))
        s.execute(ins_day, (d.year, d, total, n_users, n_repos))
        counts["daily_totals"] += 1
    return dict(counts)


def log_pipeline_run(meta: dict, loaded_neo4j: int = 0):
    s = cassandra_session()
    hour = datetime.fromisoformat(meta["hour"])
    s.execute(
        "INSERT INTO pipeline_runs (run_date, run_hour, source_file, raw_count, clean_count, loaded_mongo, loaded_neo4j, finished_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (hour.date(), hour.hour, meta["source_file"], meta["stats"]["raw"], meta["stats"]["clean"],
         meta.get("mongo", {}).get("inserted", 0), loaded_neo4j, datetime.now(timezone.utc)),
    )


def load_cassandra(mongo_meta: dict) -> dict:
    from clean import read_processed
    events = read_processed(Path(mongo_meta["processed_path"]))
    agg = aggregate(events)
    written = write_aggregates(agg)
    log_pipeline_run(mongo_meta)
    log.info("Cassandra: %s", written)
    return {**mongo_meta, "cassandra": written}
