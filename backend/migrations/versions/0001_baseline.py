"""기존 v1/v2 저장소를 손실 없이 수용하는 초기 Alembic revision."""

from alembic import op
from sqlalchemy import inspect

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "schema_migrations" in inspect(bind).get_table_names():
        legacy = bind.exec_driver_sql(
            "SELECT COALESCE(MAX(version),0) FROM schema_migrations"
        ).scalar()
        if legacy not in (0, 1, 2):
            raise RuntimeError("지원하지 않는 기존 저장소 버전입니다.")
    definitions = {
        "campaigns": """id TEXT PRIMARY KEY, name TEXT NOT NULL, ruleset_version TEXT NOT NULL,
            state_schema_version INTEGER NOT NULL, state_version INTEGER NOT NULL,
            state_json TEXT NOT NULL, created_at TEXT NOT NULL""",
        "turns": """id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
            request_id TEXT NOT NULL, request_hash TEXT NOT NULL,
            expected_state_version INTEGER NOT NULL, resulting_state_version INTEGER,
            status TEXT NOT NULL, outcome_json TEXT, created_at TEXT NOT NULL,
            UNIQUE(campaign_id, request_id)""",
        "events": """id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
            turn_id TEXT NOT NULL REFERENCES turns(id), sequence INTEGER NOT NULL,
            event_schema_version INTEGER NOT NULL, type TEXT NOT NULL, payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL, UNIQUE(campaign_id, sequence)""",
        "snapshots": """id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
            source_state_version INTEGER NOT NULL, state_json TEXT NOT NULL,
            state_hash TEXT NOT NULL, created_at TEXT NOT NULL""",
    }
    expected = {
        "campaigns": "id name ruleset_version state_schema_version "
        "state_version state_json created_at",
        "turns": "id campaign_id request_id request_hash expected_state_version "
        "resulting_state_version status outcome_json created_at",
        "events": "id campaign_id turn_id sequence event_schema_version "
        "type payload_json created_at",
        "snapshots": "id campaign_id source_state_version state_json state_hash created_at",
    }
    for table, definition in definitions.items():
        bind.exec_driver_sql(f"CREATE TABLE IF NOT EXISTS {table} ({definition})")
        columns = {column["name"] for column in inspect(bind).get_columns(table)}
        if not set(expected[table].split()) <= columns:
            raise RuntimeError(f"기존 {table} 테이블 구조가 예상과 다릅니다.")
        inspector = inspect(bind)
        if inspector.get_pk_constraint(table)["constrained_columns"] != ["id"]:
            raise RuntimeError(f"기존 {table} 기본키가 예상과 다릅니다.")
        if table in {"turns", "events", "snapshots"}:
            foreign_keys = {
                (
                    tuple(item["constrained_columns"]),
                    item["referred_table"],
                    tuple(item["referred_columns"]),
                )
                for item in inspector.get_foreign_keys(table)
            }
            if (("campaign_id",), "campaigns", ("id",)) not in foreign_keys:
                raise RuntimeError(f"기존 {table} 캠페인 참조가 누락됐습니다.")
            if table == "events" and (("turn_id",), "turns", ("id",)) not in foreign_keys:
                raise RuntimeError("기존 이벤트의 턴 참조가 누락됐습니다.")
        if table in {"turns", "events"}:
            unique = {
                tuple(item["column_names"]) for item in inspector.get_unique_constraints(table)
            }
            required = ("campaign_id", "request_id" if table == "turns" else "sequence")
            if required not in unique:
                raise RuntimeError(f"기존 {table} 중복 방지 제약이 누락됐습니다.")


def downgrade():
    raise RuntimeError("저장 데이터를 삭제하는 downgrade는 지원하지 않습니다.")
