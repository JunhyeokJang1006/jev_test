"""격리 DB/mock AI로 실제 브라우저에서 세 결말과 저장 복원을 검증한다."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def wait_for(url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 50
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("테스트 서버가 종료됐습니다.")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError("테스트 서버 준비 시간 초과")


def main() -> None:
    for port in (3000, 8000):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"포트 {port}가 사용 중입니다. 기존 서버는 종료하지 않습니다.")
    processes = []
    with tempfile.TemporaryDirectory(prefix="greyhaven-browser-") as directory:
        environment = {
            **os.environ,
            "GM_PROVIDER": "mock",
            "PYTHON_DOTENV_DISABLED": "1",
            "JEV_ENABLED": "false",
            "DATABASE_PATH": str(Path(directory) / "smoke.db"),
            "NEXT_PUBLIC_BACKEND_URL": "http://127.0.0.1:8000",
            "BACKEND_URL": "http://127.0.0.1:8000",
        }
        with (Path(directory) / "servers.log").open("w") as log:
            try:
                backend = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "app.main:app",
                        "--app-dir",
                        "backend",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "8000",
                    ],
                    cwd=ROOT,
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                processes.append(backend)
                # 직접 node를 실행해 npm 중간 프로세스 없이 서버를 정리한다.
                frontend = subprocess.Popen(
                    [
                        "node",
                        "node_modules/next/dist/bin/next",
                        "dev",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        "3000",
                    ],
                    cwd=ROOT / "frontend",
                    env=environment,
                    stdout=log,
                    stderr=log,
                )
                processes.append(frontend)
                wait_for("http://127.0.0.1:8000/api/health", backend)
                wait_for("http://127.0.0.1:3000", frontend)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    failures = []
                    page.on("pageerror", lambda error: failures.append(str(error)))
                    page.goto("http://127.0.0.1:3000")

                    def click(label: str) -> None:
                        page.get_by_role("button", name=label, exact=True).click()
                        expect(
                            page.get_by_role("button", name="행동 보내기", exact=True)
                        ).to_be_enabled()

                    def map_click(x: int, y: int) -> None:
                        host = page.get_by_test_id("pixel-scene")
                        expect(host).to_have_attribute("data-ready", "true")
                        canvas = host.locator("canvas")
                        expect(canvas).to_have_count(1)
                        box = canvas.bounding_box()
                        assert box is not None
                        canvas.click(
                            position={"x": box["width"] * x / 640, "y": box["height"] * y / 320}
                        )

                    click("여관에서 짧은 휴식")
                    click("여관에서 긴 휴식")
                    expect(page.get_by_text("Kael · HP 37/37", exact=True)).to_be_visible()
                    expect(page.get_by_label("회복과 보급")).to_contain_text("야영 보급품 1")
                    map_click(260, 155)
                    expect(page.locator(".narrative")).to_contain_text("Harlan:")
                    map_click(568, 250)
                    expect(page.locator(".campaign-heading .eyebrow")).to_have_text("빗속의 시장")
                    click("치유 물약 구매 (8골드)")
                    click("야영 보급품 구매 (3골드)")
                    expect(page.get_by_label("회복과 보급")).to_contain_text("골드 9")
                    expect(page.get_by_label("회복과 보급")).to_contain_text("치유 물약 3")
                    map_click(48, 250)
                    expect(page.locator(".campaign-heading .eyebrow")).to_have_text("Greyhaven Inn")

                    click("하를란에게 시장이 보냈다고 거짓말")

                    for action in [
                        "하를란과 대화",
                        "미라와 대화",
                        "시장으로 이동",
                        "오렌과 대화",
                        "창고로 이동",
                        "주변 조사",
                        "봉인 회수",
                    ]:
                        click(action)
                    expect(page.get_by_text("소지품: 왕실 봉인", exact=True)).to_be_visible()
                    click("세이브")
                    expect(page.get_by_text("세이브 완료", exact=False)).to_be_visible()
                    save_select = page.get_by_label("저장 선택", exact=False)
                    expect(save_select.locator("option")).to_have_count(1)
                    saved_snapshot = save_select.input_value()
                    click("세이브")
                    expect(save_select.locator("option")).to_have_count(2)
                    save_select.select_option(saved_snapshot)
                    for action, title in [
                        ("하를란에게 봉인 반환", "왕실의 신뢰"),
                        ("미라에게 봉인 전달", "새로운 약속"),
                        ("봉인을 가지고 도시 떠나기", "봉인의 방랑자"),
                    ]:
                        click("시장으로 이동")
                        if action != "봉인을 가지고 도시 떠나기":
                            click("여관으로 이동")
                        click(action)
                        expect(page.get_by_role("alert", name="결말 선택 확인")).to_be_visible()
                        expect(page.get_by_text("소지품: 왕실 봉인", exact=True)).to_be_visible()
                        click("선택 취소")
                        expect(page.get_by_role("alert", name="결말 선택 확인")).to_have_count(0)
                        click(action)
                        click("결말 확정")
                        expect(page.get_by_text(title, exact=True)).to_be_visible()
                        page.reload()
                        expect(page.get_by_text(title, exact=True)).to_be_visible()
                        click("후속 사건 시작")
                        if action != "봉인을 가지고 도시 떠나기":
                            click("시장으로 이동")
                        exile = action == "봉인을 가지고 도시 떠나기"
                        social = "오렌 설득해 피난로 확인" if exile else "오렌 설득해 증언 확보"
                        click(social)
                        expect(page.get_by_label("최근 판정")).to_be_visible()
                        expect(page.get_by_role("button", name=social, exact=True)).to_have_count(0)
                        safe_social = (
                            "오렌에게 안전한 피난로 확인" if exile else "오렌의 통행세 증언 기록"
                        )
                        if page.get_by_role("button", name=safe_social, exact=True).count():
                            click(safe_social)
                        click("창고로 이동")
                        stealth = "몰래 피난 보급품 확보" if exile else "몰래 통행세 장부 복사"
                        click(stealth)
                        expect(page.get_by_label("최근 판정")).to_be_visible()
                        expect(page.get_by_role("button", name=stealth, exact=True)).to_have_count(
                            0
                        )
                        safe_stealth = (
                            "창고에서 피난 보급품 확보" if exile else "창고의 통행세 장부 확보"
                        )
                        if page.get_by_role("button", name=safe_stealth, exact=True).count():
                            click(safe_stealth)
                        click("시장으로 이동")
                        if action == "하를란에게 봉인 반환":
                            click("여관으로 이동")
                            click("하를란에게 감사 증거 제출")
                        elif exile:
                            click("피난민과 함께 성문 통과")
                        else:
                            click("시장에서 통행세 증거 공개")
                        expect(page.get_by_text("진행: 해결", exact=False)).to_be_visible()
                        expect(page.get_by_label("세계 변화")).to_be_visible()
                        page.reload()
                        expect(page.get_by_text("진행: 해결", exact=False)).to_be_visible()
                        click("복원")
                        expect(page.get_by_text("소지품: 왕실 봉인", exact=True)).to_be_visible()
                    page.evaluate("localStorage.clear()")
                    delayed_start = []
                    page.route("**/api/campaign", lambda route: delayed_start.append(route))
                    page.reload()
                    expect(save_select.locator("option")).to_have_count(2)
                    save_select.select_option(saved_snapshot)
                    expect(page.get_by_role("button", name="복원", exact=True)).to_be_disabled()
                    assert len(delayed_start) == 1
                    delayed_start[0].continue_()
                    page.unroute("**/api/campaign")
                    click("복원")
                    expect(page.get_by_text("복원 완료", exact=True)).to_be_visible()
                    expect(page.get_by_text("소지품: 왕실 봉인", exact=True)).to_be_visible()
                    page.set_viewport_size({"width": 390, "height": 844})
                    expect(
                        page.get_by_role("button", name="시장으로 이동", exact=True)
                    ).to_be_visible()
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    map_click(568, 250)
                    expect(page.locator(".campaign-heading .eyebrow")).to_have_text("빗속의 시장")
                    if os.getenv("MAP_SCREENSHOT"):
                        page.screenshot(path=os.environ["MAP_SCREENSHOT"], full_page=True)
                    assert not failures, failures
                    browser.close()
                print(
                    "브라우저 PASS: 지도 NPC/출구 클릭, 3개 선택과 후속 사건 완주, "
                    "새로고침, 반복 복원, "
                    "서버 저장 선택·브라우저 저장 초기화 후 복원, 모바일 지도 클릭, JS 오류 없음"
                )
            finally:
                for process in reversed(processes):
                    process.terminate()
                for process in reversed(processes):
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    main()
