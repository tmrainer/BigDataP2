"""Etapa 1 - EXTRACCIÓN
Descarga el archivo horario de GH Archive (https://www.gharchive.org/):
    https://data.gharchive.org/YYYY-MM-DD-H.json.gz   (H sin cero a la izquierda: 0..23)
Cada archivo contiene todos los eventos públicos de GitHub de esa hora (~4k líneas
JSON en 2026; 100k+ hasta 2025). Esto es la "actualización incremental": cada corrida del DAG
procesa UNA hora nueva.
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
    """Hora (UTC, truncada) que se debe extraer. GH Archive publica cada archivo
    con cierta demora, por eso se resta `lag_hours`."""
    ref = reference or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref - timedelta(hours=lag_hours)).replace(minute=0, second=0, microsecond=0)


def archive_name(hour: datetime) -> str:
    return f"{hour:%Y-%m-%d}-{hour.hour}.json.gz"


def download_hour(hour: datetime, dest_dir: Path = RAW_DIR, force: bool = False) -> Path:
    """Descarga el .json.gz de la hora indicada a dest_dir. Idempotente."""
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
    """Itera los eventos (uno por línea) de un archivo .json.gz sin cargarlo entero en RAM."""
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
    """Punto de entrada para el DAG. Devuelve metadatos para XCom."""
    path = download_hour(hour)
    return {"source_file": path.name, "path": str(path), "hour": hour.isoformat()}
