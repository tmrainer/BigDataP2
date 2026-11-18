// neo4j: constraints del grafo
// uso: python scripts/init_neo4j.py
// modelo: (:User)-[:PUSHED|STARRED|FORKED|OPENED_ISSUE|OPENED_PR {count}]->(:Repo)-[:BELONGS_TO]->(:Org)

CREATE CONSTRAINT user_login IF NOT EXISTS FOR (u:User) REQUIRE u.login IS UNIQUE;
CREATE CONSTRAINT repo_name  IF NOT EXISTS FOR (r:Repo) REQUIRE r.name  IS UNIQUE;
CREATE CONSTRAINT org_login  IF NOT EXISTS FOR (o:Org)  REQUIRE o.login IS UNIQUE;
