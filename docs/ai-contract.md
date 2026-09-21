# AI와 API 구현 계약

아래는 최종 설계 계약이다. 현재 OpenAPI에는 health, campaign, game/turn, save/load가 있다.
현재 interpreter schema는 intent/action_type/target_ids/skill/difficulty_band의 strict 검증이며,
아래 확장 schema 전체와 자동 TypeScript 생성은 아직 구현되지 않았다.
Pydantic schema→OpenAPI→TypeScript 생성을 단일 기준으로 삼는다.

## 현재 턴 저장과 서사 상태

결말 선택은 별도 확인 계약을 적용한다. 가능한 `finish_quest` 제안은
HTTP 409의 `detail.code=ending_confirmation_required`와 공개 command/ending/consequence를 반환한다.
이 단계는 turn/event/state를 저장하지 않는다. 사용자가 확인하면 canonical command와
`confirmed_ending`(law/mercy/exile), 원래 campaign_id/expected_state_version을 전송한다.
명령/확인값 불일치는 422, 사이에 상태가 바뀐 요청은 409로 거부한다.
확인값은 멱등 해시에 포함되며 취소는 서버 상태를 바꾸지 않는다.
봉인 사건의 확정 선택에 대한 안전장치다. 확정 뒤 별도의 후속 사건을 시작할 수 있다.

후속 사건은 공개 `followup`(id/title/status/objective/branch/evidence/resolution) 객체로 관리한다.
원래 `quest.ending`은 보존한다. 기존 저장에 followup이 없어도 확정 선택에서 후속 사건을 시작한다.
후속 사건 활성 시 서버가 허용하는 이동·대화·증거·해결 명령만 실행하며 과거 봉인 명령은 거부한다.
결과의 공개 세계 변화와 직접 참여 NPC의 기억은 같은 턴에 저장한다. 부재 NPC에게 자동 전파하지 않는다.
`followup_check`는 서버 d20 판정이며 단서당 1회만 허용한다. `attempts`에 공개 판정 수치,
`complications`에 실패 결과를 저장한다. 이미 시도한 명령은 공개 행동과 모델 context에서 함께 제외한다.
기존 저장의 누락된 attempts는 빈 이력으로 취급하되 이미 확보한 evidence는 다시 판정하지 않는다.
정식 확보 15분, 판정 성공 2분/실패 5분, 실패 후 정식 확보 25분의 자체 시나리오 규칙이다.

규칙 판정·event·state를 한 transaction으로 commit한 후 서사를 생성한다.
commit 시점에는 기본 문장과 `narrative_status=pending`이 저장되고,
완료 후 `completed`, 공급자 실패 후 `failed`와 안전한 기본 문장을 저장한다.
동일 request_id는 기계 판정을 반복하지 않는다. 생성 중 중복 조회는 pending 결과를,
생성 완료 후 조회는 갱신된 문장을 반환할 수 있다. 이는 서사 표시 상태의 변경이며
turn_id/state_version/event/dice/state는 동일하다. UI의 pending 재조회 흐름은 후속 구현이다.
프로세스 중단 시 committed 결과는 보존되지만 pending 서사 자동 재생성은 아직 미구현이다.

## 공급자 경계

현재 interpreter는 `context.py`에서 공개 필드만 선택해 장소·이웃 장소·주변 NPC·발견 단서·
소지품·최근 공개 모험 기록 6개(항목별 최대 500자)·사용 가능한 world 명령을 전달받는다.
NPC private knowledge, 숨겨진 퀘스트 필드, 임의 최상위 필드는 전달하지 않는다.
자유문장 world proposal은 현재 명령의 intent/target 쌍과 대조하며 불일치 시 fallback한다.
이후 commit 직전 엔진이 위치·단서·아이템·종료 조건을 재검증한다.
`projection.py`의 공개 필드 규칙을 API campaign/latest_turn/turn/duplicate/load와 interpreter
context에 공유한다. narrator에도 공개 event payload만 전달한다. NPC 내부 기억·관계 저장용
필드는 DB와 snapshot에 유지하지만 API state에는 반환하지 않는다. 새 필드는 명시적으로
등록하기 전까지 공개되지 않는다. NPC actor별 지식 조회와 생성된 문장의 의미 검증은 별도 구현 대상이다.

GMModel은 interpret_action, narrate_outcome, generate_npc_response를 제공한다.
JudgmentRouter.evaluate는 일괄 분류하고 JEV off/실패 시 unknown을 반환한다.
mock/실제 GM을 교체할 수 있게 하며 mock은 고정 fixture라고 표시한다.
economy/default/cinematic은 context/호출 정책이고 provider와 별개다.
초기 default, escalation=false. JEV confidence만으로 규칙/비밀 조회를 허용하지 않는다.

## ActionProposal v1

```json
{
  "schema_version": 1,
  "intent": "hide_beside_door",
  "action_type": "exploration",
  "target_ids": ["door_inn"],
  "steps": ["hide"],
  "proposed_check": {"skill": "stealth", "difficulty_band": "moderate"},
  "requested_state_reads": []
}
```

Pydantic extra=forbid, 열거형, 문자열/배열 상한으로 검사한다.
actor/campaign은 신뢰된 서버 context에서 결정한다.
hp/dice/damage/SQL/임의 patch 등 직접 상태 변경 필드는 거부한다.
구조 검사 후 engine이 대상 존재·동일 campaign·거리·생사·자원·허용 command를 검사한다.
requested_state_reads는 허용 목록과 호출 역할의 권한으로 제한한다.

수정 호출은 최대2회이며 전체 deadline/비용 예산이 우선한다.
의도를 확정하지 못하면 상태를 바꾸지 않고 확인을 요청한다.
실패했다고 임의 판정이나 플레이어 행동을 생성하지 않는다.
사용자 입력·NPC 발언·검색 문서는 명령이 아닌 비신뢰 데이터다.

## NarrationResult v1

turn_id, outcome_id, text, referenced_event_ids를 반환한다.
참조ID, 공개 entity 여부, 확정 결과/수치와 모순을 검사한다.
prompt만으로 모든 모순/비밀 누출을 막는다고 가정하지 않는다.
초기에는 전체 생성문을 검사한 뒤 공개하며 실패하면 공개 outcome의 고정 템플릿을 사용한다.
후속 SSE도 검사한 텍스트를 분할 전달한다. 미검증 token 공개는 누출 후 회수가 불가능하므로
별도의 품질 판단을 거쳐야 한다.

## HTTP 계약안

| API | 입력/출력과 의미 |
|---|---|
| POST /api/campaign | seed_id로 생성, campaign ID와 PlayerView 반환 |
| GET /api/campaign/{id} | 공개 state/state_version. hidden truth 제외 |
| POST /api/game/turn | campaign_id, request_id(UUID), expected_state_version, input(1~4000자) |
| GET /api/game/turn/{id} | 저장한 outcome/narrative 상태 조회. 재판정 없음 |
| GET /api/game/turn/{id}/stream | P5c에서 SSE 도입. 재접속해도 재판정 없음 |
| POST /api/campaign/{id}/save | snapshot ID 반환 |
| POST /api/campaign/{id}/load | snapshot에서 새 campaign 생성, 새 ID 반환 |
| GET /api/debug/turn/{id} | 공개 trace/시각/단계/state diff. raw 모델 입출력 제외 |

버튼 command도 같은 request/version envelope를 사용한다.
성공 응답은 turn_id, state_version, narrative_status, narrative, 공개 events, dice, scene이다.
404 대상 없음,409 version/멱등 키 충돌,422 형식 오류,503 처리 불가를 구분한다.
commit 후 서술 실패는 outcome/fallback으로 반환하여 상태 변경을 재요청하지 않게 한다.
통신 오류는 같은 request_id로 조회/재송신하고 본문이 바뀌면 새 ID를 발급한다.

SSE는 committed→narrative_chunk→completed/fallback 순서다. turn_id와 연번을 붙인다.
Last-Event-ID에서 저장한 내용을 재전송하고 알 수 없는 ID는 GET으로 전체 결과를 조회한다.
전송 메시지와 DB domain event를 구분하며 재전송이 상태를 바꾸지 않는다.

## 평가와 운영

call_type, provider/model, prompt/schema/ruleset version, latency, token, repair 횟수,
fallback 이유, 입력 hash, context에 채택한 event ID를 추적한다.
키와 비밀 원문은 표준 로그에 남기지 않는다. 가격 확인 후에만 비용을 계산한다.
동일 fixture/ruleset으로 JEV 유무를 비교하며 실제 campaign에서 engine을 제거하지 않는다.
