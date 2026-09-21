"""루트 기준으로 설치/진단/검사/서버 명령을 실행하는 개발 도구."""

import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def run(command: list[str], cwd: Path = ROOT) -> None:
    print(f"실행: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def doctor() -> None:
    failed = False
    for executable in ("uv", "node", "npm"):
        if not shutil.which(executable):
            print(f"FAIL: {executable} 설치 필요")
            failed = True
        else:
            run([executable, "--version"])
    if shutil.which("node"):
        version = subprocess.check_output(["node", "--version"], text=True).strip()
        if version.split(".")[0] != "v22":
            print("FAIL: 이 프로젝트는 Node 22를 기준으로 검사합니다 (.nvmrc).")
            failed = True
    print(f"Python {sys.version.split()[0]} / SQLite {sqlite3.sqlite_version}")
    if sys.version_info[:2] != (3, 12):
        print("FAIL: uv run --locked python scripts/project.py doctor 로 Python 3.12에서 재실행")
        failed = True
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    print("SQLite 메모리 연결 확인 (저장/복구 검증 아님)")
    if failed:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bootstrap", "doctor", "check", "backend", "frontend"])
    command = parser.parse_args().command
    if command == "bootstrap":
        run(["uv", "sync", "--locked"])
        run(["npm", "ci", "--no-audit", "--no-fund"], FRONTEND)
    elif command == "doctor":
        doctor()
    elif command == "check":
        run(["uv", "run", "--locked", "ruff", "check", "backend", "scripts"])
        run(["uv", "run", "--locked", "ruff", "format", "--check", "backend", "scripts"])
        run(["uv", "run", "--locked", "pytest", "-q"])
        run(["npm", "run", "typecheck"], FRONTEND)
        run(["npm", "run", "build"], FRONTEND)
    elif command == "backend":
        run(
            [
                "uv",
                "run",
                "--locked",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--reload",
            ]
        )
    else:
        run(["npm", "run", "dev"], FRONTEND)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(error.returncode) from error
    except FileNotFoundError as error:
        print(f"실행 도구를 찾을 수 없습니다: {error.filename}", file=sys.stderr)
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        raise SystemExit(130) from None
