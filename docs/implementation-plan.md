# 구현 상세 계획

작성 기준: 2026-09-21. 원본: `gpt56_luna_jev_ai_trpg_webapp_detailed_plan_FINAL.md`.
절 번호는 원본 기준이다. 아래 설계는 구현 계약이며 P0~P3 일부가 현재 구현되어 있다.

## 최종 목표와 진행 범위

2026-09-21 추가 작업 패킷: [망루 원정](expedition.md). 재접속 복구 이후 콘텐츠를 확장한다.
순서는 독립 원정 규칙/단위 검사 → 세계 이동·공개 context·API 명시 선택·성장 연결 → 화면/지도 →
세 봉인 분기에서 새 원정 완주·저장복원·실패 경로 검사 → 독립 읽기 전용 검토·전체 check다.
기존 결말은 원정의 통행증/소개장/피난로 도움에 영향을 주며, 준비·시간에 따라 구조 결과가 달라진다.
완료조건은 단계 건너뛰기 차단, 무자원 진행, 완료 작업까지 포함한 기한 판정,
최종 선택의 모델 오분류 차단, 보상/재송신 중복 없음, 보고받은 NPC만 결과 기억,
5장소 지도와 모바일 조작, 귀환 후 두 번째 성장이다. 이 패킷 완료와 실제 플레이 분량 검증은 구분한다.

최종 목표는 자연어 행동을 규칙과 지속 상태에 연결하는 개인용 웹 TRPG이다.
30~40분짜리 캠페인 하나를 끝까지 플레이하고, 저장 후 재시작해도 사실과 NPC 지식이 유지되어야 한다.
2시간 기억 일관성(§79), 지속 세계와 검증된 동적 콘텐츠까지 최종 완료조건에 포함한다.
현재 구현 증거와 미완성 기능은 [완료 추적표](completion-tracker.md)에서 관리한다.

환경 준비와 초기 API/UI는 구현되어 있다. 현재는 서버 주사위와 기본 전투, 제한된 AI adapter,
저장 기능을 실제 규칙·모험·지도·장기 기억으로 확장 중이다. 원본은 보존한다.
Python/TypeScript 검사와 build는 각 변경의 회귀 확인이며 최종 플레이 품질 검증을 대체하지 않는다.

## 확정한 구현 선택

| 결정 | 선택과 이유 | 원문 |
|---|---|---|
| 백엔드 | Python 3.12, FastAPI, Pydantic 2 | §3~4 |
| 저장소 | SQLAlchemy 2 직접 사용, SQLite, Alembic. ORM 선택지를 하나로 줄임 | §3, 62 |
| 프런트 | Next.js App Router, React, TypeScript. Node 22 | §3, 32 |
| 초기 UI | CSS로 P0 구성, 본 게임 UI 단계에서 Tailwind/shadcn 도입 | §46 |
| 상태 구분 | TanStack Query는 서버 상태, Zustand는 선택/패널/모드만 담당 | §32 |
| 지도 | 텍스트 루프 완료 뒤 Phaser/Tiled, 16px 정적 장면부터 | §5~9, 47 |
| AI 개발 | mock → GM adapter → JEV adapter. escalation 기본 off | §27.3, 85.3 |
| Git/배포 | 현재 폴더에서 준비. 원격·외부 배포·별도 branch 생성 없음 | §64~65 |
| 규칙 | SRD 5.2.1 부분집합 + 명시적인 자체 규칙 | §30, 56 |

P0에는 실제 사용하는 웹 패키지만 설치했다. SQLAlchemy/Alembic은 다음 P1의 기반 의존성으로
설치했으나 아직 DB 모델과 migration은 없다. Phaser, UI 라이브러리, Playwright,
모델 SDK는 해당 티켓에서 lockfile과 함께 추가한다.

## 원문의 충돌 해소

1. §41~45의 장 순서 대신 부록 A의 상태→규칙→AI 우선순위로 실행한다.
2. §11.5.2의 one-shot도 상태 변경을 포함하면 validate→commit→narrate를 통과한다.
   모델 호출 1회 결과의 서사는 commit 후 일치 검증을 통과해야 표시한다.
3. §12.2의 `targets`와 §52의 `target_ids`는 `target_ids`로,
   `difficulty`/`difficulty_band`는 `difficulty_band`로 통일한다.
4. 관계 수치는 내부 0~1, 화면은 0~100%로 표현한다.
5. DB 경로는 루트 기준 `data/luna_realms.db` 하나로 통일한다.
6. 첫 텍스트 시연은 NPC 2명, 최종 MVP는 NPC 3명 이상·장소 3개·퀘스트 1개·전투 1개다.
7. §82의 은신 DC 14 및 §16의 DC 17은 설명 예시다. 카테고리 기본 DC와
   충돌할 때 실제 시나리오의 버전 있는 engine 설정을 따른다. 모델은 숫자를 결정하지 않는다.
8. 기본 repair는 최초 1회 + 최대 2회 수정 호출이다. 전체 deadline/예산이 먼저 만료되면 중단한다.
9. §58/58.2의 엔진 없는 A/B 실험은 격리 평가에서만 수행한다.
   실제 캠페인은 JEV 사용 여부와 관계없이 엔진을 거친다.

## 실행 순서와 작업 패킷

작업량은 1인 개발의 집중 작업일 추정이며 모델 접속 대기·콘텐츠 제작·UX 반복에 따라 변한다.
전체 MVP는 약 30~47 작업일 + 실제 플레이 검증 여유를 잡는다. 일정 확약이 아니다.

| 단계 | 티켓 / 의존성 | 주요 파일과 구현 작업 | 통과 기준 | 예상 |
|---|---|---|---|---|
| P0 | ENV-001 / 없음 | 현재 서버·웹 골격, lockfile, 검사 CLI, 문서 | 재설치·서버 연결·검사/build | 완료 |
| P1 | STATE-001 / P0 | `backend/app/storage.py`, `backend/app/api.py`의 migration/transaction | 원자 commit, rollback, 중복 키, stale version, FK, 재시작 복원 | 완료(초기 schema) |
| P2 | RULES-001 / P1 | `backend/app/game.py`, 고정 mock RNG fixture | 은신 DC 경계와 잘못된 장면 거부 | 완료(은신 subset) |
| P3 | VERTICAL-001A / P2 | `backend/app/api.py`, `frontend/app/campaign.tsx` | mock 은신 1턴, commit 후 서사, API 복원, 중복 요청 1회 반영 | 완료 |
| P4a | AI-001 / P3 + 실제 접속 사양 | `backend/app/ai.py`의 Luna/DeepSeek 호환 adapter, 이후 `ai/context.py`, `ai/prompts/` | adapter·JSON schema·timeout·fallback 골격 및 GPT-5.6 Luna smoke 완료; 품질 평가 잔여 | 3~5일 |
| P4b | JEV-001 / P4a + JEV 사양 | `backend/app/ai.py` 선택적 JEV route, 이후 평가 trace | no-op/fallback 골격 완료; 실제 endpoint batch 분류와 고정 코퍼스 비교 잔여 | 2~3일 |
| P5a | VERTICAL-002 / P4a | `memory/`, `world/knowledge.py`, `game/quests.py`, social commands | Harlan에게 거짓말, belief/truth 분리, 관계·퀘스트 검증 | 3~5일 |
| P5b | VERTICAL-003 / P2,P3 | `game/{combat,movement,inventory,conditions}.py`, 전투 API/UI | initiative, 이동, 기본 공격/피해, 종료, 저장 후 전투 재개 | 3~5일 |
| P5c | UI-001 / P3,P5a,P5b | story/character/quest/npc/debug 컴포넌트, Query/Zustand, SSE | pending/오류/재연결, 모바일 입력, 공개 debug trace | 3~4일 |
| P6 | MAP-001 / P5c | `frontend/game/phaser/`, Tiled map, 에셋 대장 | client-only mount/cleanup, 은신 표시, 서버 좌표, 전투 grid | 3~5일 |
| P7 | MVP-001 / P4b~P6 | 캠페인 seed, save/load, 기억 요약, replay, 평가 시나리오 | 30~40분 엔딩·재시작·JEV off·회귀 100개 | 5~8일 |
| 이후 | WORLD-001 / MVP | 시간 tick, 파벌, world planner, 장기 기억 확장 | 2시간 사실 유지·tick 중복 방지·후보 event 검증 | 별도 산정 |

P5a와 P5b는 인터페이스 고정 후 read/write 경계가 겹치지 않는 파일만 병렬화할 수 있다.
턴 서비스·공유 스키마·migration은 단일 writer가 소유한다.
루트가 계약·통합·최종 검사를 맡고 상태/영속성 변경은 read-only verifier가 독립 검토한다.

## 다음 착수 티켓: STATE-001

목표: AI 없이 캠페인을 만들고 검증된 상태 변경 하나를 저장·복원한다.

1. Pydantic `CampaignState`, `CommandEnvelope`, `DomainEvent`에 schema/ruleset version을 둔다.
2. Alembic 최초 migration에 campaigns, turns, events, snapshots를 만든다.
3. campaign version 조건부 UPDATE와 events INSERT, turns 완료 기록을 같은 transaction으로 묶는다.
4. `campaign_id + request_id` UNIQUE 및 정규화 요청 hash로 멱등성을 보장한다.
5. 기존 동일 요청은 이전 결과를 반환하고 같은 키의 다른 본문은 409로 거부한다.
6. `expected_state_version` 불일치 409, 없는 campaign 404, 형식 오류 422를 구분한다.
7. 파일 SQLite에서 migration→쓰기→연결 종료→재연결→조회 검증을 한다.
8. 실패 주입 rollback, 동시 요청, 중복 재시도 테스트 후 독립 리뷰를 받는다.

완료 증거: migration 로그, 테스트 출력, 이벤트 수/상태 version, 재시작 후 동일 state hash.
메모리 SQLite 테스트만으로 영속성 완료를 선언하지 않는다.

## VERTICAL-001의 세부 수용 기준

입력: “나는 문 옆 그림자에 숨어 경비병이 지나가기를 기다린다.”
장소 Greyhaven Inn, 플레이어 1명, NPC Harlan/Mira. 본문에 숨김 사실을 섞지 않는다.

- VERTICAL-001A: deterministic fixture GM이 구조화된 은신 proposal을 반환한다.
- 엔진이 위치·대상·skill을 검증하고 fixture d20=11, bonus=5로 판정한다.
  시나리오 DC=14를 명시한 fixture에서는 total=16, hidden=true다.
- state version 증가와 event log가 원자적으로 저장된다. 응답에 turn ID와 outcome이 있다.
- 실패 주사위 fixture에서는 실패 결과만 서술하며 hidden=true로 바꾸지 않는다.
- Narrator가 죽거나 timeout 나도 이미 commit된 턴을 재실행하지 않는다.
- 브라우저 새로고침/백엔드 재시작 후 같은 상태와 턴 결과를 읽는다.
- VERTICAL-001B(P4a): fixture 대신 실제 Luna adapter로 자유문장과 변형 표현을 검증한다.
- VERTICAL-001C(P6): Phaser의 은신 아이콘과 위치가 서버 상태를 반영한다.

mock 통과, 실제 모델 통과, 지도 통합 통과를 별도로 기록한다.

## 품질 게이트

| 영역 | 필수 실패/경계 사례 | 완료 증거 |
|---|---|---|
| 상태 | 중복 입력, 다른 본문/동일 키, 다중 탭, commit 중 오류, 재시작 | SQL constraint + integration tests |
| 규칙 | total=DC/AC, 자연 1/20의 판정 종류 차이, 음수 HP 방지, 이동 불가, 자원 부족 | 결정적 단위/불변식 검사 |
| AI | invalid JSON, extra 필드, 미등록 대상, dead NPC, repair 초과, timeout | mock transport 및 실제 모델 별도 평가 |
| 비밀 | 다른 NPC memory, GM truth, 숨긴 event가 API/context/debug/SSE에 섞임 | canary fact를 넣은 view/응답 검사 |
| 서사 | success 뒤집기, 새 아이템/피해/사실, 감정·다음 행동 강제 | 자동 검사 + 수동 주석, fallback 로그 |
| 저장 | save 후 행동, load 후 분기, schema 불일치, 손상 세이브, WAL 백업 | 파일 DB 복원 및 state hash 비교 |
| UI | 연속 전송, commit 후 네트워크 끊김, SSE reconnect, 좁은 화면 | Playwright + 수동 플레이 |
| 지도 | SSR 접근, 중복 mount, 오래된 좌표, 숨겨진 NPC 표시 | 브라우저 통합 검사 |

P7의 회귀 100개 목표 구성: 규칙 25, 중복/복구 15, 해석 20, 서사 15, 지식/메모리 15,
UI/지도 10. 테스트 파일 개수보다 시나리오와 assertion의 의미를 기준으로 센다.
치명 상태 위반·정답 fixture의 비밀 누출은 허용 0건이다. 실제 생성 문장 전체의 무누출을
테스트 몇 개로 보증하지 않으며 수동 평가와 공개 정보 입력 제한을 함께 사용한다.
해석 정확도 95%는 초기 목표값으로 두고 100개 코퍼스 확정 후 난이도별로 재평가한다.

성능/비용은 P4에서 call_type별 p50/p95, token, 재시도, fallback, 관측 가능한 비용을 기록한다.
공급자·모델·가격이 미확정이므로 지금 임의 비용이나 SLA를 PASS 기준으로 만들지 않는다.
첫 실연동 전 턴/세션 비용 한도와 timeout을 설정하고 20턴 계측으로 UX 기준을 정한다.

## 미확정 외부 입력과 진행 경계

| 항목 | 필요한 확인 | 확인 전 가능한 일 |
|---|---|---|
| Luna | OpenAI 공식 문서의 `gpt-5.6-luna` model ID, 인증 방식, structured output/stream 지원 | GM protocol, fixture, engine, mock 회귀 |
| JEV | SDK/HTTP 문서, endpoint, 인증, schema, batch, confidence 의미, quota | no-op router/fallback, 평가 인터페이스 |
| 비용 | 사용자 허용 세션 예산, 공급자 가격 | token/latency 기록 구조 |
| 규칙 | SRD 5.2.1 원본과 변환 데이터 검증 | 자체 테스트용 능력치/스킬 fixture |
| 자산 | 실제 에셋 원문 라이선스와 attribution | 도형 placeholder, 지도 schema |

OpenAI 공식 모델 문서에서 `gpt-5.6-luna`를 공개 API model ID로 확인했다.
실제 계정 권한·quota에 따라 호출이 거절될 수 있으므로 `GM_PROVIDER=auto`의 DeepSeek fallback을 유지한다.
JEV를 특정 공급자의 서비스라고 추측하여 endpoint를 만들지 않는다.
외부 입력은 P4 실연동 전 필요하며 P0~P3 진행을 막지 않는다.

## MVP 밖 범위

멀티플레이, 계정/로그인, 공개 배포, 음성/3D, 전체 클래스·주문,
거대 오픈월드, 자동 픽셀 생성, 경제/제작 시뮬레이션은 제외한다(§73).
개인 로컬 실행이 기본이다. 외부 접속은 인증·권한·TLS·debug 제한 설계 후 별도 작업이다.
