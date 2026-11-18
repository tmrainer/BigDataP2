"""etapa 3: upsert de los eventos limpios en mongodb (_id = id del evento)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pymongo import UpdateOne
from pymongo.errors import BulkWriteError

from config import mongo_db, MONGO_RETENTION_HOURS

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


def purge_old_events(reference_hour: datetime, retention_hours: int = MONGO_RETENTION_HOURS) -> int:
    """borra documentos anteriores a reference_hour - retention_hours; devuelve cuantos."""
    if retention_hours <= 0:
        return 0
    # no recorta el dia en curso: la etapa 4 lo relee
    cutoff = min(reference_hour - timedelta(hours=retention_hours),
                 reference_hour.replace(hour=0, minute=0, second=0, microsecond=0))
    res = mongo_db().events.delete_many({"created_at": {"$lt": cutoff}})
    if res.deleted_count:
        log.info("Retención Mongo: %d documentos anteriores a %s eliminados", res.deleted_count, cutoff.isoformat())
    return res.deleted_count


def load_mongo(clean_meta: dict) -> dict:
    from clean import read_processed
    events = read_processed(Path(clean_meta["processed_path"]))
    result = upsert_events(events)
    result["purged"] = purge_old_events(datetime.fromisoformat(clean_meta["hour"]))
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
