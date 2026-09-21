# Luna Realms

GPT-5.6 Luna/JEV 기반 1인용 AI TRPG의 개발 준비 프로젝트입니다.
기획 원본은 [상세 기획서](gpt56_luna_jev_ai_trpg_webapp_detailed_plan_FINAL.md)이며,
현재 구현은 SQLite 캠페인·이벤트 저장, GPT-5.6 Luna/DeepSeek/mock GM,
실제 주사위·반격 전투와 3장소·3NPC·봉인 회수·3결말의 짧은 모험입니다.
Phaser 탐험 지도에서 NPC와 출구를 클릭할 수 있습니다.
JEV 고급 라우팅, 장기 기억, 타일 기반 전술 이동과 충분한 플레이 분량은 구현 중입니다.

## 실행

Python 3.12, uv, Node 22, npm이 필요합니다. 프로젝트 루트에서 실행합니다.

```bash
python3 scripts/project.py bootstrap
uv run --locked python scripts/project.py doctor
```

터미널 두 개에서 각각 실행합니다.

```bash
python3 scripts/project.py backend
```

```bash
python3 scripts/project.py frontend
```

화면: http://127.0.0.1:3000 · API: http://127.0.0.1:8000/api/health
· API 문서: http://127.0.0.1:8000/docs

백엔드가 켜져 있으면 화면에 `API 연결: 정상`이 표시됩니다.
AI를 연결하려면 `.env.example`을 `.env`로 복사한 뒤 새로 발급한 키를 입력합니다.
`GM_PROVIDER=auto`는 OpenAI의 GPT Luna 모델을 먼저 시도하고 실패하면 DeepSeek, 마지막으로 mock으로 내려갑니다.
OpenAI 인증 변수는 `OPENAI_API_KEY`이며 공식 모델 ID는
[`gpt-5.6-luna`](https://developers.openai.com/api/docs/models/gpt-5.6-luna)입니다.
키는 절대 `.env.example`, 프런트 환경변수, Git, 로그에 넣지 않습니다.
프런트 서버 주소 변경이 필요하면 `frontend/.env.example`을 참고하여
`frontend/.env.local`에 `BACKEND_URL`을 지정합니다. 현재 연결 조회는 Next.js 서버에서 수행합니다.

## 검사와 문서

```bash
python3 scripts/project.py check
```

Python lint/format 검사, API 테스트, TypeScript 검사, Next.js production build를 실행합니다.
의존성은 `uv.lock`과 `frontend/package-lock.json`으로 고정합니다.

- [구현 상세 계획·티켓·완료조건](docs/implementation-plan.md)
- [제품 성공 기준: 발더스 게이트 수준의 플레이 흐름](docs/product-success.md)
- [아키텍처·저장·복구 설계](docs/architecture.md)
- [Alembic 전환·세이브 무결성](docs/migrations.md)
- [AI·API 계약 설계](docs/ai-contract.md)
- [규칙 범위와 판정 정책](docs/rules.md)
- [개발 환경과 운영 절차](docs/development.md)
- [준비 단계 검증 결과](docs/verification.md)
- [외부 자산 반입대장](THIRD_PARTY_LICENSES.md)

현재 화면에서 캠페인을 만들고 은신·공격 행동을 전송할 수 있습니다. OpenAI 호환 GPT-5.6 Luna
adapter와 DeepSeek fallback은 연결되어 있으며, JEV endpoint를 설정하면 선택적으로 라우팅합니다.

가능한 행동 버튼으로 하를란/미라 대화 → 시장의 오렌 → 강변 창고 조사 → 봉인 회수를 진행합니다.
회수 후 저장하면 하를란 반환·미라 전달·도시 떠나기 결말을 같은 저장에서 각각 시도할 수 있습니다.
`저장 선택`에서 서버 저장본을 골라 복원합니다. 브라우저 저장 정보가 없어져도 목록을 조회할 수 있고,
복원은 원본을 덮어쓰지 않고 새 캠페인 분기를 만듭니다. 목록은 50개씩 더 불러올 수 있습니다.
현재 서버는 로컬 단일 사용자용이며 저장 목록에 계정별 접근 제어는 없습니다. 외부 공개 배포하지 마세요.
이 고정 행동들은 서버가 직접 처리합니다. 자유문장은 현재 장면의 가능한 행동·주변 인물·발견한 단서를
모델에 전달해 해석하며 서버가 다시 검증합니다. 지원 명령 밖의 행동과 복합 행동은 아직 확장 중입니다.

실제 Chrome이 설치된 환경에서는 `uv run --locked python scripts/browser_smoke.py`로
격리 DB/mock 공급자를 사용하는 세 결말·새로고침·반복 복원·모바일 폭 검사를 실행합니다.
8000/3000 포트가 비어 있어야 하며 검사 후 테스트 서버는 종료됩니다.

프로젝트 저장소: [JunhyeokJang1006/jev_test](https://github.com/JunhyeokJang1006/jev_test).
`main`을 기준으로 관리하며 push/PR 시 GitHub Actions에서 검사를 실행합니다.
실제 `.env`, 플레이 DB, 가상환경과 빌드 산출물은 버전 관리에서 제외합니다.
