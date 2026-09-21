# 아키텍처와 상태 설계

P1 이후 구현 목표다. 현재는 `/api/health`와 연결 확인 페이지만 구현되어 있다.

## 권한과 모듈

```text
Next.js → FastAPI → TurnService → Context Builder → JEV(선택) → GM proposal
                         ↓ 검증된 command
                  GameEngine + Rules
                         ↓ 원자적 저장
                  SQLite: events + state + turn
                         ↓ 공개 outcome
                  Narrator → UI / Phaser
```

`api/`는 HTTP, `game/`은 규칙/턴, `storage/`는 transaction, `ai/`는 공급자 호출/검증,
`memory/`는 검색/요약, `world/`는 NPC 지식과 세계 tick을 담당한다.
engine은 FastAPI/모델 SDK를 import하지 않는다. ORM 객체는 API에 직접 반환하지 않는다.

## 데이터와 트랜잭션

| 테이블 | 핵심 필드 | 도입 |
|---|---|---|
| campaigns | id, ruleset_version, state_schema_version, state_version, state_json | P1 |
| turns | id, campaign_id, request_id, request_hash, expected_version, outcome_json, narrative_status | P1 |
| events | id, campaign_id, turn_id, sequence, event_schema_version, type, payload | P1 |
| snapshots | id, campaign_id, last_sequence, schema_version, state_json, state_hash | P1/P7 |
| entities | id, campaign_id, kind, mechanical fields | P5. 초기에는 state_json 내부 |
| knowledge | holder_id, claim, source_event_ids, belief, visibility, valid_from/to | P5 |
| quests | campaign_id, quest_id, state, allowed transitions | P5 |
| ai_calls | turn_id, call_type, provider/model/prompt version, latency, token, status | P4 |

turns(campaign_id, request_id), events(campaign_id, sequence)에 UNIQUE를 두고 FK를 활성화한다.
초기 state_json은 단일 현재 상태이며 entity 테이블로 분리할 때 migration과 이벤트 재적용을 함께 구현한다.

모델/JEV 호출은 DB write transaction 밖에서 실행한다. 조회한 state_version을 commit 때 재검증한다.
campaign version의 조건부 UPDATE로 오래된 요청을409로 거부하고 메모리 lock만 믿지 않는다.
SQLite 연결에 foreign_keys=ON, busy_timeout을 설정하고 파일DB에서 WAL을 확인한다.
busy는 제한 시간 후 명시 오류로 반환한다. 초기 백엔드는1 worker다.

확정 결과·event append·현재 상태 갱신을 한 transaction으로 commit하고 중간 실패는 모두 rollback한다.
event에는 변경 내용, roll 생값/보정, rule version, 참조 entity, before/after version을 기록한다.
모델 초안과 임시 주장을 확정 event로 기록하지 않는다.

## 중단과 리플레이

처리 상태는 received → interpreting → validated → committed → narrating → completed다.
commit 전 실패는 상태 변경 없음, commit 후 서술 실패는 narrative_failed로 구분한다.
후자는 공개 outcome의 고정 템플릿으로 응답하며 재시도는 결과 조회 또는 서술만 수행한다.
재시작 시 committed에서 중단된 turn을 회수한다.

리플레이는 저장한 event/roll을 순서대로 적용해 snapshot+후속 event의 state hash를 비교한다.
AI 재호출 평가는 별도 run ID와 격리 상태를 사용하며 실제 campaign을 바꾸지 않는다.
RNG seed만 저장하지 않고 실제 roll과 규칙 version을 기록한다.

수동 save는 변경 불가능한 snapshot과 last_sequence를 저장한다.
load는 새 campaign ID로 분기하고 origin snapshot/campaign을 보관한다.
브라우저는 새 ID로 이동하며 기존 campaign을 유지한다. Git branch 생성과는 무관하다.
알 수 없는 schema는 거부하고 지원 migration이 있는 경우에만 변환한다.
SQLite backup API로 일관된 복제본을 만든다. WAL 사용 중 .db 단독 복사에 의존하지 않는다.

## 정보와 화면

PlayerView, NPCContext, GMContext를 각각 생성한다. NPC는 자신의 belief와 관측만 받고
Narrator는 플레이어에게 공개 가능한 확정 outcome만 받는다.
debug API도 공개 view를 사용하며 raw prompt/response와 GM 비밀을 브라우저로 보내지 않는다.
개인 로컬 실행에서도 공개 debug와 개발자 기록을 구분한다.

Phaser 좌표·alpha·아이콘은 PlayerView를 표현한다. 클릭은 command 요청이며 확정 좌표는 서버를 따른다.
TanStack Query는 서버 상태, Zustand는 패널 열림 등 일시적 UI 상태를 담당한다.

## 기억과 확장

최근 관련 event20개와 현재 장소/NPC/quest 구조화 검색으로 시작한다.
전체 로그/전체 SRD를 넣지 않으며 context 예산 초과 시 관련성이 낮은 과거 정보를 먼저 제외한다.
요약은 source_event_ids가 있는 파생 데이터이며 원본을 대체하지 않는다.
정적 설명/규칙만 캐시하고 현재 행동 해석/NPC 반응은 캐시하지 않는다.
world tick은 게임 시간과 tick ID로 중복을 막고 planner 후보도 engine 검증을 통과한다.
