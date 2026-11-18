"""etapa 1: descarga el archivo horario de gh archive.
url: https://data.gharchive.org/YYYY-MM-DD-H.json.gz (H sin cero a la izquierda)
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import requests

from config import RAW_DIR, GHARCHIVE_LAG_HOURS

log = logging.getLogger(__name__)
BASE_URL = "https://data.gharchive.org"


def hour_to_process(reference: datetime | None = None, lag_hours: int = GHARCHIVE_LAG_HOURS) -> datetime:
    """hora utc a extraer; resta lag_hours por la demora de publicacion."""
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref - timedelta(hours=lag_hours)).replace(minute=0, second=0, microsecond=0)


def archive_name(hour: datetime) -> str:
    return f"{hour:%Y-%m-%d}-{hour.hour}.json.gz"


def download_hour(hour: datetime, dest_dir: Path = RAW_DIR, force: bool = False) -> Path:
    """descarga el .json.gz de la hora; no repite si ya existe."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = archive_name(hour)
    dest = dest_dir / name
    if dest.exists() and not force:
        log.info("Archivo ya descargado: %s", dest)
        return dest
    url = f"{BASE_URL}/{name}"
    log.info("Descargando %s", url)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    log.info("Guardado %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    return dest


def iter_events(path: Path) -> Iterator[dict]:
    """itera los eventos del .json.gz linea por linea."""
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                log.warning("Línea JSON inválida omitida")


def extract(hour: datetime) -> dict:
    """entrada del dag; devuelve metadatos para xcom."""
    path = download_hour(hour)
    return {"source_file": path.name, "path": str(path), "hour": hour.isoformat()}
