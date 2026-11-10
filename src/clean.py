"""Etapa 2 - VALIDACIÓN Y LIMPIEZA
Reglas:
  * Campos obligatorios: id, type, actor.login, repo.name, created_at.
  * created_at debe parsear a datetime (ISO-8601 'Z').
  * Deduplicación por id dentro del lote.
  * Se recorta `payload` a lo relevante por tipo de evento (Atlas Free = 0.5 GB).
  * Se limita a MAX_EVENTS_PER_RUN eventos por corrida.
Salida: archivo JSONL en data/processed/ + estadísticas de calidad.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from config import PROCESSED_DIR, MAX_EVENTS_PER_RUN

log = logging.getLogger(__name__)

REQUIRED_TOP = ("id", "type", "actor", "repo", "created_at")


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def trim_payload(event_type: str, payload: dict | None) -> dict:
    """Conserva solo los campos del payload que usan los KPIs / el grafo."""
    p = payload or {}
    if event_type == "PushEvent":
        return {
            "ref": p.get("ref"),
            "size": p.get("size"),
            "distinct_size": p.get("distinct_size"),
            "commit_messages": [c.get("message", "")[:200] for c in (p.get("commits") or [])[:5]],
        }
    if event_type == "IssuesEvent":
        issue = p.get("issue") or {}
        return {"action": p.get("action"), "number": issue.get("number"), "title": (issue.get("title") or "")[:200]}
    if event_type == "PullRequestEvent":
        pr = p.get("pull_request") or {}
        return {"action": p.get("action"), "number": p.get("number"), "title": (pr.get("title") or "")[:200],
                "merged": pr.get("merged")}
    if event_type == "ForkEvent":
        forkee = p.get("forkee") or {}
        return {"forkee": forkee.get("full_name")}
    if event_type == "CreateEvent":
        return {"ref_type": p.get("ref_type"), "ref": p.get("ref")}
    if event_type == "IssueCommentEvent":
        return {"action": p.get("action"), "issue_number": (p.get("issue") or {}).get("number")}
    return {"action": p.get("action")} if "action" in p else {}


def validate_event(raw: dict) -> tuple[dict | None, str | None]:
    """Devuelve (evento_limpio, None) o (None, motivo_rechazo)."""
    for k in REQUIRED_TOP:
        if k not in raw or raw[k] in (None, ""):
            return None, f"missing_{k}"
    actor = raw["actor"] if isinstance(raw["actor"], dict) else {}
    repo = raw["repo"] if isinstance(raw["repo"], dict) else {}
    if not actor.get("login"):
        return None, "missing_actor_login"
    if not repo.get("name"):
        return None, "missing_repo_name"
    ts = parse_ts(raw["created_at"])
    if ts is None:
        return None, "bad_created_at"

    org = raw.get("org") or {}
    clean = {
        "_id": str(raw["id"]),
        "type": raw["type"],
        "actor": {"id": actor.get("id"), "login": actor["login"]},
        "repo": {"id": repo.get("id"), "name": repo["name"]},
        "org": {"id": org.get("id"), "login": org.get("login")} if org.get("login") else None,
        "public": bool(raw.get("public", True)),
        "created_at": ts,
        "payload": trim_payload(raw["type"], raw.get("payload")),
    }
    if clean["org"] is None:
        del clean["org"]
    return clean, None


def clean_events(events: Iterable[dict], max_events: int = MAX_EVENTS_PER_RUN) -> tuple[list[dict], dict]:
    seen: set[str] = set()
    out: list[dict] = []
    stats = {"raw": 0, "clean": 0, "duplicates": 0, "rejected": 0, "reject_reasons": {}, "truncated": False}
    for raw in events:
        stats["raw"] += 1
        ev, reason = validate_event(raw)
        if ev is None:
            stats["rejected"] += 1
            stats["reject_reasons"][reason] = stats["reject_reasons"].get(reason, 0) + 1
            continue
        if ev["_id"] in seen:
            stats["duplicates"] += 1
            continue
        seen.add(ev["_id"])
        out.append(ev)
        if len(out) >= max_events:
            stats["truncated"] = True
            break
    stats["clean"] = len(out)
    return out, stats


def write_processed(events: list[dict], source_file: str, dest_dir: Path = PROCESSED_DIR) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / source_file.replace(".json.gz", ".clean.jsonl")
    with open(dest, "w", encoding="utf-8") as f:
        for ev in events:
            row = dict(ev)
            row["created_at"] = row["created_at"].isoformat()
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return dest


def read_processed(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            row["created_at"] = datetime.fromisoformat(row["created_at"])
            rows.append(row)
    return rows


def clean(extract_meta: dict) -> dict:
    """Punto de entrada para el DAG."""
    from extract import iter_events
    events, stats = clean_events(iter_events(Path(extract_meta["path"])))
    dest = write_processed(events, extract_meta["source_file"])
    log.info("Limpieza %s: %s", extract_meta["source_file"], stats)
    return {**extract_meta, "processed_path": str(dest), "stats": stats}
