# 구현 검증 결과

검증일: 2026-09-21. 범위는 개발 환경, 초기 slice, 턴 저장 순서와 AI 실패 처리다.
최종 제품 검증이 아니다. 서버 기동·유료 smoke 항목은 이전 실행 기록이며 이번 변경에서 재실행하지 않았다.

| 항목 | 결과 | 증거와 한계 |
|---|---|---|
| 현재 환경 | PASS | Python 3.12.3, uv 0.9.13, Node 22.22.1, npm 10.9.4 |
| 의존성 재설치 | PASS | 최초 설치 후 bootstrap의 uv sync --locked, npm ci 완료. 다른 OS의 깨끗한 환경은 미검증 |
| doctor | PASS | 도구 버전과 SQLite 3.45.1 메모리 SELECT 1 확인. 게임 저장 검증은 아님 |
| Python 정적 검사 | PASS | ruff check와 format --check 통과 |
| API/AI 테스트 | PASS | pytest 79 passed. 기존 플레이 검사와 Alembic 전환·snapshot 무결성 및 저장 목록 페이지/입력 범위/메타데이터 계약 확인 |
| TypeScript | PASS | next typegen + tsc --noEmit |
| production build | PASS | Next.js 16.3.5 build 완료 |
| 개발 서버 기동 | PASS | README의 backend/frontend 명령으로 8000/3000 기동 |
| 실제 연결 | PASS | health HTTP 200, 웹 SSR HTML에 API 연결: 정상 표시 |
| 실제 vertical slice | PASS | live HTTP에서 campaign 생성→은신 판정(hidden=true, v1)→동일 request 재전송 동일 결과 확인; 화면은 localStorage ID로 새로고침 복원 |
| OpenAI GPT-5.6 Luna smoke | PASS | `gpt-5.6-luna`로 실제 OpenAI endpoint 호출 성공; interpreter=luna, narrator=luna, state_version=1, hidden=true 확인 |
| API 중단 시 화면 | PASS | 백엔드 종료 후에도 웹 HTTP 200, 연결 대기 표시 |
| 종료 정리 | PASS | 이번에 실행한 두 서버 종료, 3000/8000 리스너 없음 |
| 독립 검토 | 수행 | read-only 검토로 코드/설정/문서 확인. 서사 복원·조건부 버전 갱신·migration 경합 지적을 반영 |

추가 독립 검증: Astra가 원본 대비 전체 요구사항을 감사했고 Sol이 이번 저장·AI 경계를
읽기 전용으로 재검증했다. Sol의 mock 전체 테스트는 21 passed이며 이번 변경의 차단 이슈는 없다.
pending 서사 자동 회복과 UI 재조회는 미완성으로 추적한다.

전투 확장 독립 검증: Sol이 RNG·반격·승패·멱등성을 검토했다. NPC 공격을 고블린으로
치환하던 mock 해석 오류를 수정한 뒤 전체 35 passed로 재검증했고 해당 차단은 해소됐다.
실서비스 모델의 모든 자연어 타겟 정확도를 증명하는 품질평가는 별도로 남아 있다.

모험 확장 독립 검증: Astra가 216개 도달 상태의 공개 행동 624건, 원본 상태 불변성,
단서·봉인 조건, 세 결말과 자정 경계를 검토했다. 이동 시 NPC 성향 보존과 409 서사 동기화
수정 후 관련 테스트 10개를 재확인했다. Chrome 자동화는 루트가 별도로 실행해 통과했다.

자유문장 context 확장: Sol 읽기 전용 검증에서 mock 전체 52개 통과, 추가 차단 없음.
이번 변경에서는 실제 공급자 호출을 하지 않았다. 현재 노출된 결말 명령에 대한 모델의 의도 오분류는
프롬프트만으로 완전히 막을 수 없으며, 명시적 결말 확인 흐름은 후속 보강 대상이다.

공개 응답 경계: Sol이 생성/조회/복원, 중복 턴 두 경로, 서사 저장 실패와 정상 완료의
projection 적용을 독립 확인했다. 임시 DB에서 내부 truth·NPC 기억 보존과 API 응답 제외를
재현했고 지정 테스트 14개가 통과했다. 구조적 필드 누출에 대한 추가 차단은 없다.

NPC 기억 확장: Astra가 관련 테스트 40개 및 임시 DB 동시 요청을 독립 검사했다.
같은 request_id는 200/200, 서로 다른 ID는 200/409이며 두 경우 모두 기만 주사위·event는 한 번이다.
이동 왕복 후 성향과 주장 보존, 다른 NPC의 장부 불변을 확인했다. 접촉 시각과 journal 시각 차이는
기록 순서를 맞추고 회귀 assertion으로 수정했다. 전체 테스트 62개와 브라우저 검사가 통과했다.

Phaser 탐험 지도: 전체 check 62 tests·TypeScript·production build 통과. Chrome에서 NPC 클릭,
여관↔시장 지도 이동, 모바일 창고→시장 클릭, 단일 canvas, 세 결말·반복복원을 확인했다.
초기 stale-ready 클릭 누락은 단일 게임 인스턴스와 현재 상태/렌더 상태 동일성 검사로 수정했다.
모바일 screenshot을 직접 확인했으며 Phaser MIT 고지를 보관했다. 전술 이동 검증은 아직 아니다.

Alembic/세이브 검증: Astra가 관련 테스트 42개와 4개 프로세스 동시 최초 전환,
중간 ALTER 실패 rollback, 미지원 revision, PK/FK/UNIQUE 오염 스키마 5종 거부를 확인했다.
프로세스 동시성·DDL 실패는 영구 회귀에도 추가했다. 전체 73개 검사 및 Chrome 플레이·복원 PASS.
모든 검증은 임시 DB에서 수행했고 사용자 플레이 DB를 직접 이관하지 않았다.

저장 목록: 메타데이터 페이지 목록과 선택 복원 구현. Chrome에서 두 저장본 선택,
localStorage 초기화 후 서버 저장 복구, 초기 캠페인 응답 지연 중 복원 비활성화 확인.
Astra 검토에서 발견한 초기화/복원 경합과 SQLite offset 정수 초과 오류를 수정했다.

첫 검사에서 ruff의 app 모듈 분류를 명시하도록 수정했다.
TestClient 경로의 의존성 deprecation 경고는 httpx ASGITransport 기반 테스트로 변경하여 해소했다.
수정 후 전체 check를 재실행했고 pytest 경고 없이 통과했다.

Next.js 개발 서버가 생성한 frontend/AGENTS.md와 CLAUDE.md는 도구 안내 파일이다.
사용자가 제공한 원본 기획서는 수정하지 않았다. 현재 SHA-256:
`d919d3646b16a6b8e6f92a3505c8fb441147e43d2f7e25150fd6e3cbfa6d6b03`.

## 미실행·미구현

- Chrome 브라우저 자동화: 세 결말 실제 버튼 완주·새로고침·같은 저장 3회 복원·390px 폭 넘침 없음·JS 오류 없음 확인. 접근성 전체/시각 품질/30분 플레이 평가는 아직 미실행이다.
- Alembic 전환과 snapshot 무결성/버전 검사, 서버 저장 목록/선택 복원 구현. 전체 규칙은 미완성이다.
- GPT-5.6 Luna/JEV 유료 품질 평가: smoke는 통과했으며 장시간 품질 평가는 별도 실행. API 호출은 비용이 발생할 수 있어 자동화 테스트에서 mock으로 격리한다.
- 공급자 설정: OpenAI GPT-5.6 Luna를 우선 사용하고 DeepSeek/mock으로 fallback한다. 자동화 테스트는 비용 방지를 위해 GM_PROVIDER=mock으로 격리한다.
- Phaser 탐험 지도·NPC/출구 클릭: Chrome 데스크톱·모바일 클릭 검사 통과. Tiled/전술 이동·SRD/게임 에셋 반입·30분 플레이·100개 회귀는 후속 구현/검증이다.
- GitHub Actions 원격 실행·Docker 실행·외부 배포·의존성 취약점/라이선스 전체 감사: 미실행.

판정: 현재 머신에서 P0~P3 mock vertical slice와 상세 계획 준비 완료.
전체 게임은 미완성이다. [완료 추적표](completion-tracker.md)의 규칙·모험·지도·기억·장시간 플레이 검증을 계속 진행한다.
