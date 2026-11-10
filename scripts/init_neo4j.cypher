// =====================================================================
//  Neo4j: constraints e índices del grafo
//  Ejecutar en Neo4j Browser (console.neo4j.io -> Open) o con:
//      python scripts/init_neo4j.py
//
//  Modelo:
//    (:User {login})  -[:PUSHED {count}]->       (:Repo {name})
//    (:User)          -[:STARRED {count}]->      (:Repo)
//    (:User)          -[:FORKED {count}]->       (:Repo)
//    (:User)          -[:OPENED_ISSUE {count}]-> (:Repo)
//    (:User)          -[:OPENED_PR {count}]->    (:Repo)
//    (:Repo)          -[:BELONGS_TO]->           (:Org {login})
//
//  Justificación: preguntas como "repositorio con más usuarios distintos
//  conectados" o "usuarios que colaboran en los mismos repos" son
//  recorridos de grafo; en SQL serían self-joins recursivos.
// =====================================================================

CREATE CONSTRAINT user_login IF NOT EXISTS FOR (u:User) REQUIRE u.login IS UNIQUE;
CREATE CONSTRAINT repo_name  IF NOT EXISTS FOR (r:Repo) REQUIRE r.name  IS UNIQUE;
CREATE CONSTRAINT org_login  IF NOT EXISTS FOR (o:Org)  REQUIRE o.login IS UNIQUE;
