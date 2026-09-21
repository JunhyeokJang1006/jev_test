"""격리 DB/mock AI로 실제 브라우저에서 세 결말과 저장 복원을 검증한다."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def verify_turn_recovery(browser) -> None:
    """Actual mock-server commits survive response loss without a second turn."""
    context = browser.new_context()
    page = context.new_page()
    page.goto("http://127.0.0.1:3000")
    send = page.get_by_role("button", name="행동 보내기", exact=True)
    retry = page.get_by_role("button", name="같은 행동 재시도", exact=True)
    expect(send).to_be_enabled()
    campaign_id = page.evaluate("localStorage.getItem('luna-realms-campaign-id')")
    campaign_url = f"http://127.0.0.1:8000/api/campaign/{campaign_id}"
    outbox = "luna-realms-turn-outbox"

    for mode in ("before_send", "after_commit", "malformed", "server_error", "proxy_timeout"):
        before = httpx.get(campaign_url).json()["state_version"]
        sent = []

        def lose_response(route, *, sent=sent, mode=mode):
            sent.append(route.request.post_data)
            assert page.evaluate("key => localStorage.getItem(key)", outbox) == sent[0]
            if mode == "before_send":
                route.abort()
                return
            response = route.fetch()
            assert response.ok
            if mode == "after_commit":
                route.abort()
            elif mode == "malformed":
                route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
            elif mode == "server_error":
                route.fulfill(
                    status=503, content_type="application/json", body='{"detail":"unavailable"}'
                )
            else:
                route.fulfill(
                    status=408, content_type="application/json", body='{"detail":"timeout"}'
                )

        page.route("**/api/game/turn", lose_response)
        page.get_by_label("행동", exact=True).fill("주변 조사")
        send.click()
        expect(retry).to_be_enabled()
        expect(send).to_be_disabled()
        expect(page.get_by_role("button", name="세이브", exact=True)).to_be_disabled()
        expect(page.get_by_role("button", name="복원", exact=True)).to_be_disabled()
        assert len(sent) == 1
        recorded = sent[0]
        assert json.loads(recorded)["expected_state_version"] == before
        assert httpx.get(campaign_url).json()["state_version"] == before + (mode != "before_send")
        if mode == "after_commit":
            later = httpx.post(
                "http://127.0.0.1:8000/api/game/turn",
                json={
                    "campaign_id": campaign_id,
                    "request_id": str(uuid4()),
                    "expected_state_version": before + 1,
                    "input": "하를란과 대화",
                },
            )
            assert later.status_code == 200
        page.unroute("**/api/game/turn", lose_response)
        # Another tab sees the same unresolved envelope and cannot start a new turn.
        other = page.context.new_page()
        other.goto("http://127.0.0.1:3000")
        expect(other.get_by_role("button", name="같은 행동 재시도", exact=True)).to_be_enabled()
        expect(other.get_by_role("button", name="행동 보내기", exact=True)).to_be_disabled()
        other.close()

        if mode == "after_commit":
            # Recovery must remain available even when initialization GET fails.
            page.route("**/api/campaign/*", lambda route: route.abort())
        page.reload()
        expect(retry).to_be_enabled()
        assert page.evaluate("key => localStorage.getItem(key)", outbox) == recorded
        if mode == "after_commit":
            page.unroute("**/api/campaign/*")
        replayed = []

        def capture_retry(route, *, replayed=replayed):
            replayed.append(route.request.post_data)
            route.continue_()

        page.route("**/api/game/turn", capture_retry)
        retry.click()
        expect(send).to_be_enabled()
        assert replayed == [recorded]
        current = httpx.get(campaign_url).json()
        assert current["state_version"] == before + 1 + (mode == "after_commit")
        expect(page.locator(".narrative")).to_have_text(current["latest_turn"]["narrative"])
        assert page.evaluate("key => localStorage.getItem(key)", outbox) is None
        page.unroute("**/api/game/turn", capture_retry)

    # Corrupt recovery data is preserved, and no new action may replace it.
    page.evaluate("key => localStorage.setItem(key, '{broken')", outbox)
    page.reload()
    expect(page.locator(".campaign .error")).to_contain_text("복구 기록이 손상")
    expect(send).to_be_disabled()
    assert page.evaluate("key => localStorage.getItem(key)", outbox) == "{broken"
    page.evaluate("key => localStorage.removeItem(key)", outbox)
    page.reload()
    expect(send).to_be_enabled()

    # Quota/access failures must prevent the HTTP mutation altogether.
    before = httpx.get(campaign_url).json()["state_version"]
    page.evaluate("""() => {
        const original = Storage.prototype.setItem;
        Storage.prototype.setItem = function(key, value) {
            if (key === 'luna-realms-turn-outbox') {
                throw new DOMException('Quota exceeded', 'QuotaExceededError');
            }
            return original.call(this, key, value);
        };
    }""")
    page.get_by_label("행동", exact=True).fill("주변 조사")
    send.click()
    expect(page.locator(".campaign .error")).to_contain_text("Quota exceeded")
    assert httpx.get(campaign_url).json()["state_version"] == before
    context.close()


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
                    verify_turn_recovery(browser)
                    context = browser.new_context(viewport={"width": 1280, "height": 900})
                    page = context.new_page()
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
                        canvas.scroll_into_view_if_needed()
                        box = canvas.bounding_box()
                        assert box is not None
                        canvas.click(
                            position={"x": box["width"] * x / 640, "y": box["height"] * y / 320}
                        )

                    click("전투 시작")
                    expect(page.get_by_test_id("battlefield")).to_be_visible()
                    expect(page.get_by_label("적 상태").locator("li")).to_have_count(2)
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 3/3")
                    click("전투 중 치유 물약")
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text(
                        "보조 행동 사용 완료"
                    )
                    expect(page.get_by_label("회복과 보급")).to_contain_text("치유 물약 1")
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    )
                    click("방어 태세")
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text(
                        "주요 행동 사용 완료"
                    )
                    click("이동: (0, 2)")
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 2/3")
                    click("적 차례로 넘기기")
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 3/3")
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("주요 행동 1회")
                    click("전투에서 후퇴")
                    expect(page.get_by_test_id("battlefield")).to_have_count(0)
                    page.set_viewport_size({"width": 1280, "height": 900})
                    # 물약으로 이미 완전히 회복했다면 서버가 불필요한 휴식을 제공하지 않는다.
                    if page.get_by_role("button", name="여관에서 짧은 휴식", exact=True).count():
                        click("여관에서 짧은 휴식")
                    long_rest = page.get_by_role(
                        "button", name="여관에서 긴 휴식", exact=True
                    ).count()
                    if long_rest:
                        click("여관에서 긴 휴식")
                    expect(page.get_by_text("Kael · HP 37/37", exact=True)).to_be_visible()
                    expect(page.get_by_label("회복과 보급")).to_contain_text(
                        f"야영 보급품 {1 if long_rest else 2}"
                    )
                    map_click(260, 155)
                    expect(page.locator(".narrative")).to_contain_text("Harlan:")
                    map_click(568, 250)
                    expect(page.locator(".campaign-heading .eyebrow")).to_have_text("빗속의 시장")
                    click("치유 물약 구매 (8골드)")
                    click("야영 보급품 구매 (3골드)")
                    expect(page.get_by_label("회복과 보급")).to_contain_text("골드 9")
                    expect(page.get_by_label("회복과 보급")).to_contain_text("치유 물약 2")
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
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("경험치 125")
                        click("성장: 설득의 기술")
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("레벨 4")
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("설득 +5")
                        expect(page.get_by_label("도시 공고")).not_to_contain_text("공고까지")
                        if action == "하를란에게 봉인 반환":
                            click("시장으로 이동")
                        price = 6 if action == "하를란에게 봉인 반환" else 8 if exile else 10
                        click(f"치유 물약 구매 ({price}골드)")
                        expect(page.get_by_label("회복과 보급")).to_contain_text("치유 물약 3")
                        click("오렌과 대화")
                        page.reload()
                        expect(page.get_by_text("진행: 해결", exact=False)).to_be_visible()
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("레벨 4")
                        click("꺼진 망루의 전령 의뢰 수락")
                        expect(page.get_by_label("망루 원정")).to_contain_text("꺼진 망루의 전령")
                        click(
                            "경비대 통행증 확보"
                            if action == "하를란에게 봉인 반환"
                            else "피난로 경험으로 길 준비"
                            if exile
                            else "상인 소개장 확보"
                        )
                        click("야영 보급품 1개로 구조 로프 준비")
                        map_click(320, 250)
                        expect(page.locator(".campaign-heading .eyebrow")).to_have_text("동쪽 성문")
                        if action == "하를란에게 봉인 반환":
                            click("경비대 통행증으로 성문 통과")
                        else:
                            check = (
                                "성문으로 잠입 (DC 14, 한 번)"
                                if exile
                                else "성문 경비 설득 (DC 14, 한 번)"
                            )
                            click(check)
                            expect(page.get_by_label("최근 판정")).to_be_visible()
                            if page.get_by_role(
                                "button", name="성문 보수 작업을 돕고 통과 (20분)", exact=True
                            ).count():
                                click("성문 보수 작업을 돕고 통과 (20분)")
                        page.set_viewport_size({"width": 390, "height": 844})
                        map_click(568, 250)
                        expect(page.locator(".campaign-heading .eyebrow")).to_have_text("꺼진 망루")
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= window.innerWidth"
                        )
                        for command in [
                            "망루에서 전령 위치 조사 (5분)",
                            "망루에서 문서 위치 조사 (5분)",
                            "망루 계단 보강 (10분)",
                        ]:
                            click(command)
                        click(
                            "로프로 전령과 문서 모두 확보 확정 (5분)"
                            if action == "하를란에게 봉인 반환"
                            else "문서 확보 우선 확정 (전령 구조 포기, 5분)"
                            if exile
                            else "전령 구조 우선 확정 (문서 포기, 5분)"
                        )
                        expect(page.get_by_label("망루 원정")).to_contain_text("현장 해결")
                        click("동쪽 성문으로 이동")
                        click("시장으로 이동")
                        click("오렌에게 망루 결과 보고 (25골드)")
                        expect(page.get_by_label("망루 원정")).to_contain_text("보고 완료")
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("경험치 250")
                        click("성장: 전투 숙련")
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("레벨 5")
                        page.reload()
                        expect(page.get_by_label("망루 원정")).to_contain_text("보고 완료")
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("레벨 5")
                        page.set_viewport_size({"width": 1280, "height": 900})
                        click("복원")
                        expect(page.get_by_text("소지품: 왕실 봉인", exact=True)).to_be_visible()
                    observer = context.new_page()
                    observer.goto("http://127.0.0.1:3000")
                    expect(
                        observer.get_by_role("button", name="행동 보내기", exact=True)
                    ).to_be_enabled()
                    click("복원")
                    expect(
                        observer.get_by_role("button", name="행동 보내기", exact=True)
                    ).to_be_disabled()
                    expect(
                        observer.get_by_text("다른 탭에서 캠페인이 변경되었습니다.", exact=False)
                    ).to_be_visible()
                    observer.reload()
                    expect(
                        observer.get_by_role("button", name="행동 보내기", exact=True)
                    ).to_be_enabled()
                    observer.close()
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
                    "브라우저 PASS: 지도 NPC/출구 클릭, 3개 선택과 후속 사건·망루 원정 완주, "
                    "구조/문서/동시 확보·귀환 보고·레벨5 성장, "
                    "새로고침, 반복 복원, "
                    "전송 전·서버 반영 후 응답 유실/오류의 동일 요청 복구, "
                    "다중 탭·저장소 실패 차단, "
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
