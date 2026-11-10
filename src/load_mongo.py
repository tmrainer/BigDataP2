"""Etapa 3 - CARGA EN MONGODB (Atlas)
Inserta los documentos limpios en la colección `events`. Idempotente: usa el id
del evento de GitHub como _id y upserts en lote (bulk_write), así re-ejecutar
una hora no duplica datos.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from config import mongo_db

log = logging.getLogger(__name__)
BATCH = 2000


def upsert_events(events: list[dict]) -> dict:
    db = mongo_db()
    col = db.events
    inserted = matched = 0
    for i in range(0, len(events), BATCH):
        ops = [UpdateOne({"_id": e["_id"]}, {"$setOnInsert": e}, upsert=True) for e in events[i:i + BATCH]]
        try:
            res = col.bulk_write(ops, ordered=False)
            inserted += res.upserted_count
            matched += res.matched_count
        except BulkWriteError as exc:
            log.warning("Errores parciales en bulk_write: %s", exc.details.get("writeErrors", [])[:3])
            inserted += exc.details.get("nUpserted", 0)
    return {"inserted": inserted, "already_present": matched}


def load_mongo(clean_meta: dict) -> dict:
    from clean import read_processed
    events = read_processed(Path(clean_meta["processed_path"]))
    result = upsert_events(events)
    db = mongo_db()
    db.ingestion_log.update_one(
        {"source_file": clean_meta["source_file"]},
        {"$set": {
            "source_file": clean_meta["source_file"],
            "hour": clean_meta["hour"],
            "stats": clean_meta["stats"],
            "mongo": result,
            "loaded_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    log.info("Mongo: %s", result)
    return {**clean_meta, "mongo": result}
