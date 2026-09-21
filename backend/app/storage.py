"""SQLite 저장소와 Alembic migration 진입점."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "luna_realms.db"
MIGRATION_HEAD = "0002"
MIGRATION_LOCK = RLock()


def database_path() -> Path:
    value = os.getenv("DATABASE_PATH")
    path = Path(value) if value else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(path or database_path(), timeout=5, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    if connection.in_transaction:
        raise RuntimeError("migration은 게임 트랜잭션 밖에서 실행해야 합니다.")
    # Alembic의 context proxy는 프로세스 내 직렬화가 필요하다.
    # 별도 프로세스와의 경합은 env.py의 BEGIN IMMEDIATE가 직렬화한다.
    with MIGRATION_LOCK:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if table:
            versions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
            if len(versions) == 1 and versions[0][0] == MIGRATION_HEAD:
                return
        path = connection.execute("PRAGMA database_list").fetchone()[2]
        if not path:
            raise RuntimeError("게임 migration에는 파일 기반 SQLite가 필요합니다.")
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["database_path"] = path
        command.upgrade(config, "head")


def json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_campaign(connection: sqlite3.Connection, campaign_id: str) -> dict[str, Any] | None:
    row = connection.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if row is None:
        return None
    result = dict(row)
    result["state"] = json.loads(result.pop("state_json"))
    latest = connection.execute(
        "SELECT outcome_json FROM turns WHERE campaign_id = ? ORDER BY created_at DESC LIMIT 1",
        (campaign_id,),
    ).fetchone()
    result["latest_turn"] = json.loads(latest["outcome_json"]) if latest else None
    return result
