"""모든 검사에서 사용자 저장소와 외부 공급자를 격리한다."""

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "isolated.db"))
    monkeypatch.setenv("GM_PROVIDER", "mock")
    monkeypatch.setenv("JEV_ENABLED", "false")
