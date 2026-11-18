"""etapa 5: convierte las interacciones de cassandra en aristas (usuario)-[tipo]->(repo) de neo4j.
una hora ya cargada (pipeline_runs.loaded_neo4j > 0) se omite.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from config import (cassandra_session, neo4j_driver, NEO4J_DATABASE, RELATION_BY_TYPE,
                    NEO4J_TOP_REPOS, NEO4J_TOP_USERS, NEO4J_RETENTION_HOURS)

log = logging.getLogger(__name__)

TOP_REPOS = NEO4J_TOP_REPOS
TOP_USERS = NEO4J_TOP_USERS
BATCH = 1000

MERGE_EDGES = """
UNWIND $rows AS row
MERGE (u:User {login: row.user})
MERGE (r:Repo {name: row.repo})
  ON CREATE SET r.owner = split(row.repo, '/')[0]
MERGE (u)-[rel:%s]->(r)
  ON CREATE SET rel.count = row.n, rel.first_seen = datetime(row.ts), rel.last_seen = datetime(row.ts)
  ON MATCH  SET rel.count = coalesce(rel.count, 0) + row.n,
                rel.first_seen = CASE WHEN rel.first_seen IS NULL OR datetime(row.ts) < rel.first_seen
                                      THEN datetime(row.ts) ELSE rel.first_seen END,
                rel.last_seen = CASE WHEN datetime(row.ts) > coalesce(rel.last_seen, rel.first_seen)
                                     THEN datetime(row.ts) ELSE coalesce(rel.last_seen, rel.first_seen) END
"""

MERGE_ORGS = """
UNWIND $rows AS row
MERGE (o:Org {login: row.org})
WITH o, row
MATCH (r:Repo {name: row.repo})
MERGE (r)-[:BELONGS_TO]->(o)
"""

# corren en sesion auto-commit (CALL ... IN TRANSACTIONS lo exige)
PRUNE_USERS = """
MATCH (u:User)
WHERE NOT EXISTS {
  MATCH (u)-[r]->(:Repo) WHERE coalesce(r.last_seen, r.first_seen) >= datetime($cutoff)
}
CALL { WITH u DETACH DELETE u } IN TRANSACTIONS OF 2000 ROWS
"""
PRUNE_REPOS = """
MATCH (r:Repo) WHERE NOT (r)<-[]-(:User)
CALL { WITH r DETACH DELETE r } IN TRANSACTIONS OF 2000 ROWS
"""
PRUNE_ORGS = """
MATCH (o:Org) WHERE NOT (o)<-[:BELONGS_TO]-()
CALL { WITH o DETACH DELETE o } IN TRANSACTIONS OF 2000 ROWS
"""
COUNT_NODES = "MATCH (n) RETURN count(n) AS nodes"


# --- fuente: cassandra
def read_interactions(hour: datetime) -> list[dict]:
    """filas de user_repo_interactions_by_hour de la hora."""
    s = cassandra_session()
    rows = s.execute(
        "SELECT actor_login, repo_name, event_type, event_count, org_login, first_seen "
        "FROM user_repo_interactions_by_hour WHERE event_date=%s AND event_hour=%s",
        (hour.date(), hour.hour))
    out = []
    for r in rows:
        ts = r.first_seen
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        out.append({"user": r.actor_login, "repo": r.repo_name, "type": r.event_type,
                    "n": r.event_count or 0, "org": r.org_login,
                    "ts": (ts or hour).isoformat()})
    return out


def build_edges(interactions: list[dict]) -> tuple[dict, list[dict]]:
    """devuelve {rel_type: [rows]} y las filas de organizaciones."""
    repo_act = Counter()
    user_act = Counter()
    for i in interactions:
        repo_act[i["repo"]] += i["n"]
        user_act[i["user"]] += i["n"]
    top_repos = {r for r, _ in repo_act.most_common(TOP_REPOS)}
    top_users = {u for u, _ in user_act.most_common(TOP_USERS)}

    edges: Counter = Counter()
    first_ts: dict = {}
    orgs: dict = {}
    for i in interactions:
        rel = RELATION_BY_TYPE.get(i["type"])
        repo, user = i["repo"], i["user"]
        if rel is None or repo not in top_repos or user not in top_users:
            continue
        key = (rel, user, repo)
        edges[key] += i["n"]
        if key not in first_ts or i["ts"] < first_ts[key]:
            first_ts[key] = i["ts"]
        if i.get("org"):
            orgs[repo] = i["org"]

    by_rel: dict[str, list[dict]] = {}
    for (rel, user, repo), n in edges.items():
        by_rel.setdefault(rel, []).append({"user": user, "repo": repo, "n": n, "ts": first_ts[(rel, user, repo)]})
    org_rows = [{"repo": r, "org": o} for r, o in orgs.items()]
    return by_rel, org_rows


def write_graph(by_rel: dict, org_rows: list[dict]) -> int:
    total = 0
    with neo4j_driver() as driver:
        driver.verify_connectivity()
        for rel, rows in by_rel.items():
            q = MERGE_EDGES % rel
            for i in range(0, len(rows), BATCH):
                driver.execute_query(q, rows=rows[i:i + BATCH], database_=NEO4J_DATABASE)
                total += len(rows[i:i + BATCH])
        for i in range(0, len(org_rows), BATCH):
            driver.execute_query(MERGE_ORGS, rows=org_rows[i:i + BATCH], database_=NEO4J_DATABASE)
    return total


def prune_graph(reference_hour: datetime, retention_hours: int = NEO4J_RETENTION_HOURS) -> dict:
    """borra usuarios inactivos desde reference_hour - retention_hours y nodos huerfanos."""
    if retention_hours <= 0:
        return {}
    cutoff = (reference_hour - timedelta(hours=retention_hours)).isoformat()
    deleted = {}
    with neo4j_driver() as driver, driver.session(database=NEO4J_DATABASE) as sess:
        for name, q in (("users", PRUNE_USERS), ("repos", PRUNE_REPOS), ("orgs", PRUNE_ORGS)):
            deleted[name] = sess.run(q, cutoff=cutoff).consume().counters.nodes_deleted
        deleted["nodes_total"] = sess.run(COUNT_NODES).single()["nodes"]
    log.info("Poda Neo4j (cutoff %s): %s", cutoff, deleted)
    return deleted


def load_neo4j(cass_meta: dict) -> dict:
    from load_cassandra import get_pipeline_run, mark_neo4j_loaded
    hour = datetime.fromisoformat(cass_meta["hour"])
    run = get_pipeline_run(hour)
    if run is not None and (run.loaded_neo4j or 0) > 0:
        log.warning("Hora %s ya cargada en Neo4j (%d aristas): se omite", hour, run.loaded_neo4j)
        return {**cass_meta, "neo4j": {"skipped": True, "edges": run.loaded_neo4j}}
    interactions = read_interactions(hour)
    log.info("Neo4j: %d interacciones leídas de Cassandra para la hora %s", len(interactions), hour)
    by_rel, org_rows = build_edges(interactions)
    n = write_graph(by_rel, org_rows)
    mark_neo4j_loaded(hour, n)
    pruned = prune_graph(hour)
    log.info("Neo4j: %d relaciones mergeadas (%s)", n, {k: len(v) for k, v in by_rel.items()})
    return {**cass_meta, "neo4j": {"edges": n, "source_cassandra_rows": len(interactions), "pruned": pruned}}
