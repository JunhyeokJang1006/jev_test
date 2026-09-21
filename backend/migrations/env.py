"""기존 파일 DB와 새 DB 모두 하나의 SQLite 쓰기 트랜잭션으로 갱신한다."""

import os
from pathlib import Path

from alembic import context
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

root = Path(__file__).resolve().parents[2]
path = (
    context.config.attributes.get("database_path")
    or os.getenv("DATABASE_PATH")
    or root / "data/luna_realms.db"
)
Path(path).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    URL.create("sqlite", database=str(path)), poolclass=NullPool, connect_args={"timeout": 5}
)
try:
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        context.configure(connection=connection, transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()
finally:
    engine.dispose()
