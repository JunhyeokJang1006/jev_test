import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations

from app.storage import ROOT, connect, json_hash, migrate

from .helpers import request


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_schema_upgrade_preserves_rows_and_snapshot_metadata(tmp_path, version):
    path = tmp_path / "legacy.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_path"] = str(path)
    command.upgrade(config, "0001")
    db = connect(path)
    try:
        db.execute("DROP TABLE alembic_version")
        db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO schema_migrations VALUES (?)", (version,))
        state = {"player": {"hp": 7}, "hidden_truth": "test-private"}
        raw = json.dumps(state)
        db.execute(
            "INSERT INTO campaigns VALUES ('c','legacy','srd-5.2.1-subset-v1',1,1,?,'today')",
            (raw,),
        )
        db.execute("INSERT INTO turns VALUES ('t','c','r','h',0,1,'completed','{}','today')")
        db.execute("INSERT INTO events VALUES ('e','c','t',1,1,'TEST','{}','today')")
        if version == 1:
            db.execute("DROP TABLE snapshots")
        else:
            db.execute(
                "INSERT INTO snapshots VALUES ('s','c',1,?,?,'today')", (raw, json_hash(state))
            )
        migrate(db)
        migrate(db)
        assert db.execute("SELECT state_json FROM campaigns").fetchone()[0] == raw
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002"
        if version == 2:
            snapshot = db.execute("SELECT * FROM snapshots").fetchone()
            assert snapshot["last_sequence"] == 1
            assert snapshot["state_hash"] == json_hash(state)
            assert snapshot["ruleset_version"] == "srd-5.2.1-subset-v1"
    finally:
        db.close()


def test_parallel_first_migration_is_serialized(tmp_path):
    path = tmp_path / "parallel.db"
    connect(path).close()

    def upgrade(_):
        db = connect(path)
        try:
            migrate(db)
            return db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(upgrade, range(4))) == ["0002"] * 4


def test_separate_processes_can_migrate_same_empty_database(tmp_path):
    path = tmp_path / "processes.db"
    connect(path).close()
    environment = {
        **os.environ,
        "DATABASE_PATH": str(path),
        "PYTHONPATH": str(ROOT / "backend"),
        "PYTHON_DOTENV_DISABLED": "1",
    }
    code = "from app.storage import connect,migrate; db=connect(); migrate(db); db.close()"
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(4)
    ]
    try:
        for process in processes:
            _, errors = process.communicate(timeout=20)
            assert process.returncode == 0, errors.decode()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    db = connect(path)
    try:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0002"
    finally:
        db.close()


def test_interrupted_ddl_rolls_back_columns_and_revision(monkeypatch, tmp_path):
    path = tmp_path / "ddl-failure.db"
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_path"] = str(path)
    command.upgrade(config, "0001")
    execute = Operations.execute

    def fail_second_alter(self, sqltext, **kwargs):
        if "ADD COLUMN state_schema_version" in str(sqltext):
            raise RuntimeError("injected DDL failure")
        return execute(self, sqltext, **kwargs)

    monkeypatch.setattr(Operations, "execute", fail_second_alter)
    db = connect(path)
    try:
        with pytest.raises(RuntimeError, match="injected"):
            migrate(db)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0001"
        assert "ruleset_version" not in {
            row[1] for row in db.execute("PRAGMA table_info(snapshots)")
        }
    finally:
        db.close()


def test_unknown_legacy_version_rolls_back_without_changing_data(tmp_path):
    db = connect(tmp_path / "future.db")
    try:
        db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO schema_migrations VALUES (99)")
        with pytest.raises(RuntimeError, match="지원하지"):
            migrate(db)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"schema_migrations"}
        assert db.execute("SELECT version FROM schema_migrations").fetchone()[0] == 99
    finally:
        db.close()


def test_existing_columns_without_primary_key_are_not_silently_adopted(tmp_path):
    db = connect(tmp_path / "invalid-constraints.db")
    try:
        db.execute(
            "CREATE TABLE campaigns (id TEXT, name TEXT, ruleset_version TEXT, "
            "state_schema_version INTEGER, state_version INTEGER, state_json TEXT, created_at TEXT)"
        )
        db.execute("INSERT INTO campaigns VALUES ('c','keep','v1',1,0,'{}','today')")
        with pytest.raises(RuntimeError, match="기본키"):
            migrate(db)
        assert db.execute("SELECT name FROM campaigns").fetchone()[0] == "keep"
        assert (
            db.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='alembic_version'"
            ).fetchone()[0]
            == 0
        )
    finally:
        db.close()


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("state_json='{}'", "snapshot_corrupted"),
        ("state_json='not-json'", "snapshot_corrupted"),
        ("state_schema_version=99", "snapshot_version_unsupported"),
        ("ruleset_version='future'", "snapshot_version_unsupported"),
    ],
)
def test_invalid_snapshot_does_not_create_campaign(mutation, error):
    campaign = request("POST", "/api/campaign", json={}).json()
    saved = request("POST", f"/api/campaign/{campaign['id']}/save").json()
    db = connect()
    try:
        db.execute(f"UPDATE snapshots SET {mutation}")
        response = request(
            "POST",
            f"/api/campaign/{campaign['id']}/load",
            json={"snapshot_id": saved["snapshot_id"]},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == error
        assert db.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0] == 1
    finally:
        db.close()
