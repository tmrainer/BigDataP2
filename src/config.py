"""config central: variables de entorno y conexiones a las 3 bases."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[1] / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.environ.get("MONGO_DB", "github_events")

CASSANDRA_HOST = os.environ.get("CASSANDRA_HOST", "localhost")
CASSANDRA_KEYSPACE = os.environ.get("CASSANDRA_KEYSPACE", "github_metrics")

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "bigdata2026")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

MAX_EVENTS_PER_RUN = int(os.environ.get("MAX_EVENTS_PER_RUN", "60000"))
GHARCHIVE_LAG_HOURS = int(os.environ.get("GHARCHIVE_LAG_HOURS", "2"))
# horas faltantes: ventana a revisar y maximo por corrida (0 = desactivada)
RECOVERY_WINDOW_HOURS = int(os.environ.get("RECOVERY_WINDOW_HOURS", "72"))
RECOVERY_MAX_HOURS = int(os.environ.get("RECOVERY_MAX_HOURS", "6"))

# retencion en mongodb por created_at, en horas (0 = nunca borra)
MONGO_RETENTION_HOURS = int(os.environ.get("MONGO_RETENTION_HOURS", "0"))
# poda del grafo: usuarios inactivos hace n horas (0 = nunca)
NEO4J_RETENTION_HOURS = int(os.environ.get("NEO4J_RETENTION_HOURS", "0"))
# tope de repos y usuarios por lote que entran al grafo
NEO4J_TOP_REPOS = int(os.environ.get("NEO4J_TOP_REPOS", "10000"))
NEO4J_TOP_USERS = int(os.environ.get("NEO4J_TOP_USERS", "20000"))

RELATION_BY_TYPE = {
    "PushEvent": "PUSHED",
    "WatchEvent": "STARRED",
    "ForkEvent": "FORKED",
    "IssuesEvent": "OPENED_ISSUE",
    "PullRequestEvent": "OPENED_PR",
}


def mongo_client():
    from pymongo import MongoClient
    return MongoClient(MONGO_URI, serverSelectionTimeoutMS=20000, tz_aware=True)


def mongo_db():
    return mongo_client()[MONGO_DB]


@lru_cache(maxsize=1)
def cassandra_session():
    from cassandra.cluster import Cluster
    cluster = Cluster([CASSANDRA_HOST], port=9042, protocol_version=4)
    session = cluster.connect()
    session.execute(
        f"CREATE KEYSPACE IF NOT EXISTS {CASSANDRA_KEYSPACE} "
        "WITH replication = {'class':'SimpleStrategy','replication_factor':1}"
    )
    session.set_keyspace(CASSANDRA_KEYSPACE)
    return session


def neo4j_driver():
    from neo4j import GraphDatabase
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
