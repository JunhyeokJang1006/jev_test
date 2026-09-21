# 개발 환경과 운영

## 기준 환경

Python3.12 / uv0.9.13, Node22 / npm을 기준으로 한다.
확인한 로컬 환경은 Python3.12.3, Node22.22.1, npm10.9.4다.
Docker Compose는 설치되어 있지만 P0에 필요하지 않다.
Next.js16.3.5 / React19.3.0을 npm registry에서 확인해 고정했다.
TypeScript는5.9 계열을 선택했다. 새 major 전환은 별도 호환성 검증 후 진행한다.
정확한 직접/간접 의존성은 lockfile이 기준이다.

```bash
python3 scripts/project.py bootstrap
uv run --locked python scripts/project.py doctor
python3 scripts/project.py check
```

bootstrap은 환경/의존성만 준비하고 기존.env와 데이터를 변경하지 않는다.
부족한 도구가 있으면 실패한다. Python/Node를 전역에 덮어쓰지 않는다.
의존성 업데이트는 manifest 변경→uv lock/npm install→check→lock 차이 확인 순서다.

## 서버

README의2단말 방식을 사용하고 각 단말에서 Ctrl-C로 종료한다.
포트가 겹치면 다른 포트로 실행하고 frontend/.env.local의 BACKEND_URL을 맞춘다.
기존 프로세스를 종료하지 않는다.

```bash
uv run --locked uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8001
```

프런트 직접 실행은 frontend 디렉터리에서 npm run dev다.
backend 디렉터리에서는 uv run --project .. uvicorn app.main:app --reload로 실행할 수 있다.
P0의 API 조회는 Next.js 서버에서 수행하므로 브라우저용 CORS가 필요하지 않다.
게임 API 단계에서 동일 origin proxy 또는 허용 origin 정책을 선택한다.

## 설정과 DB/AI

루트 `.env.example`은 이름과 빈 값만 보관한다. 실제 키는 Git에 포함되지 않는 `.env`에서만 읽는다.
`GM_PROVIDER=auto`는 OpenAI의 GPT Luna 모델 → DeepSeek → mock 순서이며,
OpenAI 인증은 `OPENAI_API_KEY`를 사용한다. 저장소는 현재 `DATABASE_PATH`를 읽는다.
실제 호출은 서버에서만 일어나고 프런트로 키를 전달하지 않는다.
비밀값에 NEXT_PUBLIC_를 붙이지 않는다. health는 생존 확인이지 DB/AI 준비 검사가 아니다.
P1에서 DB readiness를 추가하며 health를 위해 유료 모델을 호출하지 않는다.

Alembic 설정은 루트 alembic.ini와 backend/migrations에 있다.
게임 요청 시 최신 버전을 확인하며, 명시적 전환은 아래 명령으로 실행한다.

```bash
DATABASE_PATH=data/luna_realms.db uv run --locked alembic upgrade head
```

테스트는 임시DB를 사용하고 사용자campaign DB를 대상으로 하지 않는다.
기존 데이터 이관과 복원 검증 정책은 [저장소 전환](migrations.md)을 참고한다.
Docker Compose는 필요시 영속volume, localhost 공개, healthcheck, migration 실행 주체,
키 주입을 설계한 후 도입한다. 현재 Docker 실행/이미지 생성/외부 배포는 하지 않았다.

## 공식 확인 자료

2026-09-21 공식 자료를 참조했다. 실제 AI 공급자의 접속 사양은 아직 미확정이다.

- Next.js: https://nextjs.org/docs/app/getting-started/installation
- FastAPI/Uvicorn: https://fastapi.tiangolo.com/deployment/manually/
- uv 프로젝트/lock: https://docs.astral.sh/uv/guides/projects/
- SQLite/SQLAlchemy: https://docs.sqlalchemy.org/en/20/dialects/sqlite.html
- Alembic: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- SRD: https://www.dndbeyond.com/srd

업데이트 시 공식 문서와 실제 build/test로 호환성을 확인한다.
