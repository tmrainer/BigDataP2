"""Etapa 5 - CONSTRUCCIÓN DE RELACIONES Y CARGA EN NEO4J (AuraDB)
Del lote horario se derivan aristas (usuario)-[TIPO]->(repo) con un contador.
Se usa MERGE + UNWIND por lotes para ser idempotente y eficiente.
AuraDB Free: 200k nodos / 400k relaciones -> se limita a los repos y usuarios
con más actividad del lote (TOP_REPOS, TOP_USERS) para no saturar.
"""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

from config import neo4j_driver, NEO4J_DATABASE, RELATION_BY_TYPE

log = logging.getLogger(__name__)

TOP_REPOS = 3000     # repos más activos del lote que entran al grafo
TOP_USERS = 5000     # usuarios más activos del lote
BATCH = 1000

MERGE_EDGES = """
UNWIND $rows AS row
MERGE (u:User {login: row.user})
MERGE (r:Repo {name: row.repo})
  ON CREATE SET r.owner = split(row.repo, '/')[0]
MERGE (u)-[rel:%s]->(r)
  ON CREATE SET rel.count = row.n, rel.first_seen = datetime(row.ts)
  ON MATCH  SET rel.count = coalesce(rel.count, 0) + row.n
"""

MERGE_ORGS = """
UNWIND $rows AS row
MERGE (o:Org {login: row.org})
WITH o, row
MATCH (r:Repo {name: row.repo})
MERGE (r)-[:BELONGS_TO]->(o)
"""


def build_edges(events: list[dict]) -> tuple[dict, list[dict]]:
    """Devuelve {rel_type: [rows]} y filas de organizaciones."""
    repo_act = Counter(e["repo"]["name"] for e in events)
    user_act = Counter(e["actor"]["login"] for e in events)
    top_repos = {r for r, _ in repo_act.most_common(TOP_REPOS)}
    top_users = {u for u, _ in user_act.most_common(TOP_USERS)}

    edges: Counter = Counter()
    first_ts: dict = {}
    orgs: dict = {}
    for e in events:
        rel = RELATION_BY_TYPE.get(e["type"])
        repo, user = e["repo"]["name"], e["actor"]["login"]
        if rel is None or repo not in top_repos or user not in top_users:
            continue
        key = (rel, user, repo)
        edges[key] += 1
        first_ts.setdefault(key, e["created_at"].isoformat())
        if e.get("org", {}).get("login"):
            orgs[repo] = e["org"]["login"]

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


def load_neo4j(cass_meta: dict) -> dict:
    from clean import read_processed
    events = read_processed(Path(cass_meta["processed_path"]))
    by_rel, org_rows = build_edges(events)
    n = write_graph(by_rel, org_rows)
    log.info("Neo4j: %d relaciones mergeadas (%s)", n, {k: len(v) for k, v in by_rel.items()})
    return {**cass_meta, "neo4j": {"edges": n}}
