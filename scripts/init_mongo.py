"""crea colecciones, validador de esquema e indices en mongodb.
uso: docker compose exec jupyter python scripts/init_mongo.py
"""
import os
from pymongo import MongoClient, ASCENDING, DESCENDING

client = MongoClient(os.environ["MONGO_URI"])
db = client[os.environ.get("MONGO_DB", "github_events")]

# coleccion principal: solo se valida la cabecera comun
if "events" not in db.list_collection_names():
    db.create_collection(
        "events",
        validator={
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["_id", "type", "actor", "repo", "created_at"],
                "properties": {
                    "_id": {"bsonType": "string", "description": "id del evento en GitHub"},
                    "type": {"bsonType": "string"},
                    "actor": {"bsonType": "object", "required": ["login"]},
                    "repo": {"bsonType": "object", "required": ["name"]},
                    "created_at": {"bsonType": "date"},
                    "payload": {"bsonType": "object"},
                },
            }
        },
        validationLevel="moderate",
    )

ev = db.events
ev.create_index([("created_at", DESCENDING)], name="ix_created_at")
ev.create_index([("type", ASCENDING), ("created_at", DESCENDING)], name="ix_type_date")
ev.create_index([("repo.name", ASCENDING)], name="ix_repo")
ev.create_index([("actor.login", ASCENDING)], name="ix_actor")

db.ingestion_log.create_index([("source_file", ASCENDING)], unique=True, name="ux_source_file")

print("MongoDB inicializado en", db.name, "| colecciones:", db.list_collection_names())
