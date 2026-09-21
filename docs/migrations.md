# 저장소 전환과 세이브 무결성

실행 코드의 `storage.migrate`는 Alembic revision `0002`까지 적용한다.
이미 최신인 파일은 버전 조회만 수행한다. 게임 트랜잭션 안에서 migration을 호출하면 거부한다.
애플리케이션 내부에서는 Alembic context 실행을 RLock으로 직렬화하고, 별도 프로세스와의
경합은 SQLite BEGIN IMMEDIATE로 직렬화한다. DDL과 revision 갱신은 한 transaction이다.

- `0001`: 기존 v1/v2 campaign·turn·event·snapshot을 보존하며 Alembic baseline으로 수용한다.
  컬럼·PK·FK·UNIQUE를 검사한다. 기존 schema_migrations는 기록으로 남기며 더 이상 갱신하지 않는다.
- `0002`: snapshot에 ruleset_version/state_schema_version/last_sequence를 추가한다.
  이전 snapshot의 버전은 원본 campaign 메타데이터에서, 순번은 저장 당시 state_version까지의 event에서 이관한다.
  기존 JSON과 hash는 바꾸지 않는다.

파일 경로를 명시해 CLI로 실행할 수도 있다.

```bash
DATABASE_PATH=data/luna_realms.db uv run --locked alembic upgrade head
```

CLI는 `.env`를 자동으로 읽지 않으므로 다른 DB를 쓸 때는 DATABASE_PATH를 명시한다.
인메모리 DB는 게임 저장소 migration 대상이 아니다. 알 수 없는 버전·잘못된 기존 제약은
변경 없이 거부하며, 데이터를 삭제하는 downgrade는 제공하지 않는다.

저장 시 현재 rule/schema와 event 순번을 함께 기록한다. 복원은 JSON 파싱·state hash·지원 버전을
검사한 후 새 campaign을 생성한다. 실패하면 새 campaign이 남지 않는다.
이 hash는 우발적인 손상 검출용이며 DB를 직접 변경할 수 있는 사람에 대한 인증 수단은 아니다.

전체 테스트는 conftest의 임시 DB/mock 공급자 격리를 사용한다. 기존 v1/v2 행 보존, 병렬 thread/process
최초 전환, 중간 DDL 실패 rollback, 잘못된 제약·버전, 손상 snapshot 거부가 회귀 테스트에 포함된다.
이번 작업에서 사용자 플레이 DB에 직접 migration을 실행하지 않았다.
