# 프로젝트 개발 지침

- 한국어로 보고하고 백엔드·개발 자동화는 Python을 우선한다.
- 원본 기획서를 보존한다. 구체적인 구현 순서와 결정은 `docs/implementation-plan.md`에 기록한다.
- 현재 구현 범위와 목표 설계를 구별한다. 준비 화면이나 mock 결과를 실제 게임/모델 검증으로 보고하지 않는다.
- Python 3.12 + uv, Node 22 + npm을 사용한다. 변경 시 lockfile을 함께 갱신한다.
- Python만 기계 상태를 변경한다. AI proposal, 서사, Phaser, 클라이언트 저장소는 권위 있는 상태가 아니다.
- 변경은 검증된 command → 단일 transaction의 events/state → narration 순서를 따른다.
- 플레이어/NPC/GM별 정보 경계를 먼저 정의하고 모델 context, API, debug 출력에 동일하게 적용한다.
- 후속 DB 구현은 Alembic migration을 사용한다. 자동 create_all로 migration을 우회하지 않는다.
- 완료 전 `python3 scripts/project.py check`와 변경 관련 검사를 실행한다.
- 상태·영속성·공유 계약·보안 또는 8개 이상 파일 변경은 구현 뒤 read-only verifier에게 독립 검토를 맡긴다.
- 기존 사용자 변경을 보존한다. 별도 worktree/branch/commit은 명시 요청 없이 만들지 않는다.
- 키·DB·플레이 기록을 출력/커밋하지 않는다. 외부 AI 유료 호출은 연결 정보와 실행 범위가 확인된 작업에서 수행한다.
- 전역 자동 위임 정책은 `/home/jain/.codex/AGENTS.md`를 따른다. 이 파일은 전역 정책의 미러가 아니다.
