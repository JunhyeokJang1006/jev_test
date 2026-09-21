"""세이브의 규칙/상태 버전과 이벤트 경계를 보존한다."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE snapshots ADD COLUMN ruleset_version TEXT NOT NULL "
        "DEFAULT 'srd-5.2.1-subset-v1'"
    )
    op.execute("ALTER TABLE snapshots ADD COLUMN state_schema_version INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE snapshots ADD COLUMN last_sequence INTEGER NOT NULL DEFAULT 0")
    op.execute("""UPDATE snapshots SET
        ruleset_version = (SELECT ruleset_version FROM campaigns WHERE id=snapshots.campaign_id),
        state_schema_version = (SELECT state_schema_version FROM campaigns
                                WHERE id=snapshots.campaign_id),
        last_sequence = (SELECT COALESCE(MAX(e.sequence),0)
                         FROM events e JOIN turns t ON e.turn_id=t.id
                         WHERE e.campaign_id=snapshots.campaign_id
                         AND t.resulting_state_version <= snapshots.source_state_version)
    """)


def downgrade():
    raise RuntimeError("세이브 메타데이터를 삭제하는 downgrade는 지원하지 않습니다.")
