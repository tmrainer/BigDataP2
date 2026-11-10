"""Crea constraints en Neo4j AuraDB leyendo scripts/init_neo4j.cypher.
Uso: docker compose exec jupyter python scripts/init_neo4j.py
"""
import os
import pathlib
from neo4j import GraphDatabase

uri = os.environ["NEO4J_URI"]
auth = (os.environ.get("NEO4J_USER", "neo4j"), os.environ["NEO4J_PASSWORD"])
db = os.environ.get("NEO4J_DATABASE", "neo4j")

cypher = pathlib.Path(__file__).with_name("init_neo4j.cypher").read_text(encoding="utf-8")
statements = [s.strip() for s in cypher.split(";") if s.strip() and not s.strip().startswith("//")]
# quitar líneas de comentario dentro de cada bloque
statements = ["\n".join(l for l in s.splitlines() if not l.strip().startswith("//")).strip() for s in statements]
statements = [s for s in statements if s]

with GraphDatabase.driver(uri, auth=auth) as driver:
    driver.verify_connectivity()
    for stmt in statements:
        driver.execute_query(stmt, database_=db)
        print("OK:", stmt.splitlines()[0][:80])
print("Neo4j inicializado")
