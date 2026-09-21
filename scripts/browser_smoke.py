"""격리 DB/mock AI로 실제 브라우저에서 세 결말과 저장 복원을 검증한다."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from collections import deque
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


def verify_narration_recovery(browser) -> None:
    """Inject stale UI status; recovery calls the real idempotent mock-server endpoint."""
    context = browser.new_context()
    page = context.new_page()
    page.goto("http://127.0.0.1:3000")
    send = page.get_by_role("button", name="행동 보내기", exact=True)
    expect(send).to_be_enabled()
    send.click()
    expect(send).to_be_enabled()
    campaign_id = page.evaluate("localStorage.getItem('luna-realms-campaign-id')")
    campaign_url = f"http://127.0.0.1:8000/api/campaign/{campaign_id}"
    committed = httpx.get(campaign_url).json()
    repair_url = f"{campaign_url}/turn/{committed['latest_turn']['turn_id']}/narration"

    def stale_status(status):
        def intercept(route):
            body = json.loads(json.dumps(committed))
            body["latest_turn"]["narrative_status"] = status
            route.fulfill(status=200, json=body)

        page.route(campaign_url, intercept)
        page.reload()
        expect(page.get_by_role("button", name="서사만 다시 생성", exact=True)).to_be_enabled()
        page.unroute(campaign_url, intercept)

    stale_status("pending")
    page.get_by_role("button", name="서사 상태 새로고침", exact=True).click()
    expect(page.get_by_role("region", name="서사 복구", exact=True)).to_have_count(0)
    assert httpx.get(campaign_url).json() == committed

    stale_status("failed")
    expect(page.get_by_role("region", name="서사 복구")).to_contain_text("판정 원문")

    def lose_repair_response(route):
        assert route.fetch().status == 200
        route.abort()

    page.route(repair_url, lose_repair_response)
    page.get_by_role("button", name="서사만 다시 생성", exact=True).click()
    expect(page.locator(".campaign .error")).to_contain_text("서사 복구 결과를 확인하지 못했습니다")
    assert page.evaluate("localStorage.getItem('luna-realms-turn-outbox')") is None
    assert httpx.get(campaign_url).json() == committed
    page.unroute(repair_url, lose_repair_response)

    # A repaired old turn must never overwrite the newer campaign displayed afterward.
    later = httpx.post(
        "http://127.0.0.1:8000/api/game/turn",
        json={
            "campaign_id": campaign_id,
            "expected_state_version": committed["state_version"],
            "input": "하를란과 대화",
        },
    )
    assert later.status_code == 200
    latest = httpx.get(campaign_url).json()
    page.get_by_role("button", name="서사만 다시 생성", exact=True).click()
    expect(page.get_by_role("region", name="서사 복구", exact=True)).to_have_count(0)
    expect(page.locator(".campaign .narrative")).to_have_text(latest["latest_turn"]["narrative"])
    assert httpx.get(campaign_url).json() == latest
    context.close()


def verify_defeat_recovery(browser) -> None:
    """Lose a real mock-server fight, save while down, and continue via all care choices."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    page.goto("http://127.0.0.1:3000")
    send = page.get_by_role("button", name="행동 보내기", exact=True)
    expect(send).to_be_enabled()

    def current():
        campaign_id = page.evaluate("localStorage.getItem('luna-realms-campaign-id')")
        return httpx.get(f"http://127.0.0.1:8000/api/campaign/{campaign_id}").json()

    page.get_by_role("button", name="전투 시작", exact=True).click()
    expect(send).to_be_enabled()
    for _ in range(60):
        if current()["state"]["player"]["hp"] == 0:
            break
        page.get_by_role("button", name="적 차례로 넘기기", exact=True).click()
        expect(send).to_be_enabled()
    fallen = current()["state"]
    assert fallen["player"]["hp"] == 0
    assert fallen["combat"]["result"] == "defeat"
    expect(page.get_by_role("region", name="패배 후 진행")).to_contain_text("모험은 이어집니다")
    save = page.get_by_role("button", name="세이브", exact=True)
    expect(save).to_be_enabled()
    save.click()
    expect(page.locator(".campaign .note").filter(has_text="세이브 완료")).to_be_visible()
    snapshot = page.evaluate("localStorage.getItem('luna-realms-snapshot-id')")
    page.reload()
    expect(page.get_by_role("button", name="도움을 기다리기 (8시간)", exact=True)).to_be_enabled()

    choices = [
        ("도움을 기다리기 (8시간)", 480, 0, 0),
        ("응급 치료 받기 (10골드, 1시간)", 60, 10, 0),
        ("보급품으로 치료하기 (보급품 1개, 4시간)", 240, 0, 1),
    ]
    for index, (label, minutes, gold, supplies) in enumerate(choices):
        if index:
            page.get_by_label("저장 선택", exact=False).select_option(snapshot)
            page.get_by_role("button", name="복원", exact=True).click()
            expect(page.get_by_role("button", name=label, exact=True)).to_be_enabled()
        page.get_by_role("button", name=label, exact=True).click()
        expect(send).to_be_enabled()
        recovered = current()["state"]
        assert recovered["player"]["hp"] == max(1, fallen["player"]["max_hp"] // 2)
        assert recovered["elapsed_minutes"] == fallen["elapsed_minutes"] + minutes
        assert recovered["resources"] == {
            **fallen["resources"],
            "gold": fallen["resources"]["gold"] - gold,
            "camp_supplies": fallen["resources"]["camp_supplies"] - supplies,
        }
        for field in ("quest", "inventory", "progression", "combat"):
            assert recovered[field] == fallen[field]
        expect(page.get_by_label("패배의 대가", exact=True)).to_contain_text(f"{minutes}분")
        expect(page.get_by_role("region", name="패배 후 진행")).to_have_count(0)
        expect(page.get_by_role("button", name="전투 시작", exact=True)).to_have_count(0)
        page.reload()
        expect(page.get_by_role("button", name="시장으로 이동", exact=True)).to_be_enabled()
        page.get_by_role("button", name="시장으로 이동", exact=True).click()
        expect(send).to_be_enabled()
        assert current()["state"]["location_id"] == "market"
    context.close()


def verify_tactical_options(browser) -> None:
    """Real server action budgets and conditional skill outcomes; no forced dice."""
    for mode in ("dash", "shove", "feint"):
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        page.goto("http://127.0.0.1:3000")
        send = page.get_by_role("button", name="행동 보내기", exact=True)
        expect(send).to_be_enabled()
        campaign_id = page.evaluate("localStorage.getItem('luna-realms-campaign-id')")
        campaign_url = f"http://127.0.0.1:8000/api/campaign/{campaign_id}"

        def click(label, *, page=page, send=send):
            page.get_by_role("button", name=label, exact=True).click()
            expect(send).to_be_enabled()

        def current(*, campaign_url=campaign_url):
            return httpx.get(campaign_url).json()

        click("전투 시작")
        before = current()["state"]["combat"]["elapsed_seconds"]
        if mode == "dash":
            click("전력 질주")
            expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 6칸")
            expect(page.get_by_label("남은 전투 행동")).to_contain_text("주요 행동 사용 완료")
            assert current()["state"]["combat"]["elapsed_seconds"] == before
            page.reload()
            expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 6칸")
            expect(page.get_by_role("button", name="전력 질주", exact=True)).to_have_count(0)
            click("전투 이동: 왼쪽")
            click("전투에서 후퇴")
        else:
            for _ in range(2):
                if "고블린을 공격한다" in current()["actions"]:
                    break
                click("전투 이동: 오른쪽")
            label = "고블린 밀쳐 넘어뜨리기" if mode == "shove" else "고블린 교란하기"
            click(label)
            result = current()
            success = result["latest_turn"]["event"]["payload"]["success"]
            condition = "prone" if mode == "shove" else "exposed"
            first = result["state"]["combat"]["enemies"][0]
            assert (condition in first["conditions"]) == success
            assert result["state"]["combat"]["elapsed_seconds"] == before
            page.reload()
            expect(send).to_be_enabled()
            assert current() == result
            if success:
                expect(page.get_by_label("적 상태")).to_contain_text(
                    "넘어짐" if mode == "shove" else "빈틈"
                )
            if mode == "shove":
                expect(page.get_by_label("남은 전투 행동")).to_contain_text("주요 행동 사용 완료")
                click("적 차례로 넘기기")
                latest = current()["latest_turn"]
                assert "prone" not in latest["state"]["combat"]["enemies"][0]["conditions"]
                if success:
                    assert latest["event"]["payload"]["enemy_attacks"][0]["stood_up"] is True
            else:
                expect(page.get_by_label("남은 전투 행동")).to_contain_text("보조 행동 사용 완료")
                expect(
                    page.get_by_role("button", name="전투 중 치유 물약", exact=True)
                ).to_have_count(0)
                click("고블린을 공격한다")
                latest = current()["latest_turn"]
                assert len(latest["event"]["payload"]["attack_rolls"]) == (2 if success else 1)
                assert "exposed" not in latest["state"]["combat"]["enemies"][0]["conditions"]
                if success:
                    expect(page.get_by_label("최근 판정")).to_contain_text("중 높은 값 선택")
        context.close()


def verify_watchtower_combat(page, click, *, retreat: bool) -> bool:
    """Continue an existing adventure through a second encounter, with real dice.

    The browser does not force victory: defeat must recover and converge via stairs.
    Deterministic backend tests separately cover each outcome and reward boundary.
    """
    campaign_id = page.evaluate("localStorage.getItem('luna-realms-campaign-id')")

    def current():
        response = httpx.get(f"http://127.0.0.1:8000/api/campaign/{campaign_id}")
        response.raise_for_status()
        return response.json()

    before = current()["state"]
    # The main adventure already fled the inn; travel may remove the old public board.
    assert not before.get("combat", {}).get("active")
    click("망루 매복자와 전투")
    expect(page.get_by_test_id("battlefield")).to_contain_text("망루 매복 전투")
    expect(page.get_by_label("적 상태").locator("li")).to_have_count(2)
    expect(page.get_by_role("button", name="망루 계단 보강 (10분)", exact=True)).to_have_count(0)
    started = current()
    assert started["state"]["combat"]["encounter_id"] == "watchtower_ambush"
    assert {enemy["id"] for enemy in started["state"]["combat"]["enemies"]} == {
        "bandit_001",
        "bandit_002",
    }
    assert started["state"]["elapsed_minutes"] >= before["elapsed_minutes"]
    page.reload()
    expect(page.get_by_test_id("battlefield")).to_contain_text("망루 매복 전투")
    assert current() == started
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    if retreat:
        click("이동: (0, 2)")
        click("전투에서 후퇴")
    else:
        # Choose legal movement from the public board and click the actual grid target.
        for _ in range(120):
            data = current()
            state, actions = data["state"], data["actions"]
            combat = state["combat"]
            if not combat["active"]:
                break
            if (
                "전투 중 치유 물약" in actions
                and state["player"]["hp"] <= state["player"]["max_hp"] - 8
            ):
                click("전투 중 치유 물약")
                continue
            attack = next((label for label in actions if "매복자를 공격한다" in label), None)
            if attack:
                enemy_id = "bandit_002" if attack.startswith("두 번째") else "bandit_001"
                feint = "두 번째 매복자 교란하기" if enemy_id == "bandit_002" else "매복자 교란하기"
                if feint in actions:
                    click(feint)
                enemy = next(enemy for enemy in combat["enemies"] if enemy["id"] == enemy_id)
                click(f"공격: {enemy['name']}")
                assert current()["latest_turn"]["event"]["payload"]["target_id"] == enemy_id
                continue
            move = None
            if combat["action_available"] and combat["movement_remaining"]:
                living = {(e["x"], e["y"]) for e in combat["enemies"] if e["hp"] > 0}
                blocked = living | {tuple(wall) for wall in combat["walls"]}
                origin = combat["player_x"], combat["player_y"]
                queue, seen = deque([(origin, [])]), {origin}
                while queue:
                    point, path = queue.popleft()
                    if path and any(abs(point[0] - x) + abs(point[1] - y) == 1 for x, y in living):
                        move = path[0]
                        break
                    for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                        neighbor = point[0] + dx, point[1] + dy
                        if (
                            0 <= neighbor[0] < combat["width"]
                            and 0 <= neighbor[1] < combat["height"]
                            and neighbor not in blocked | seen
                        ):
                            seen.add(neighbor)
                            queue.append((neighbor, [*path, neighbor]))
            click(f"이동: ({move[0]}, {move[1]})" if move else "적 차례로 넘기기")
        else:
            raise AssertionError("망루 전투가 120개 행동 안에 종료되지 않았습니다.")
    finished = current()["state"]
    result = finished["combat"]["result"]
    assert result == "fled" if retreat else result in {"victory", "defeat"}
    won = result == "victory"
    assert finished["progression"]["xp"] == before["progression"]["xp"] + (25 if won else 0)
    if result == "defeat":
        click("도움을 기다리기 (8시간)")
        assert current()["state"]["player"]["hp"] > 0
    expect(page.get_by_role("button", name="망루 매복자와 전투", exact=True)).to_have_count(0)
    if won:
        assert finished["expedition"]["approach"] == "combat"
        expect(page.get_by_label("망루 원정")).to_contain_text("매복자를 물리쳤습니다")
    else:
        click("망루 계단 보강 (10분)")
    print(f"망루 브라우저 실주사위 결과: {result}; 원정 선택으로 합류", flush=True)
    return won


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
                    verify_narration_recovery(browser)
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
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 3칸")
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
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 2칸")
                    click("적 차례로 넘기기")
                    expect(page.get_by_label("남은 전투 행동")).to_contain_text("이동 3칸")
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
                        ]:
                            click(command)
                        watchtower_victory = False
                        if action == "하를란에게 봉인 반환":
                            click("망루 계단 보강 (10분)")
                        else:
                            watchtower_victory = verify_watchtower_combat(
                                page, click, retreat=exile
                            )
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
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text(
                            f"경험치 {275 if watchtower_victory else 250}"
                        )
                        expect(page.get_by_role("region", name="지속 세계 사건")).to_contain_text(
                            "도시 보급 수송"
                        )
                        expect(page.get_by_label("파벌 상태").locator("li")).to_have_count(3)
                        if action == "미라에게 봉인 전달":
                            expect(
                                page.get_by_role(
                                    "button", name="보급 수송 호위 요청 (10분)", exact=True
                                )
                            ).to_have_count(0)
                            click("보급 수송 자원봉사 (30분)")
                            expect(
                                page.get_by_role("region", name="지속 세계 사건")
                            ).to_contain_text("준비한 지원: 자원봉사")
                        click("성장: 전투 숙련")
                        expect(page.get_by_label("캐릭터 성장")).to_contain_text("레벨 5")
                        # Training advances world time: supported/dual rescue arrives,
                        # while documents alone without intervention delays the convoy.
                        expect(page.get_by_label("현재 시장 상황")).to_contain_text(
                            "물자 부족" if exile else "지원 물자 도착"
                        )
                        for _ in range(6):
                            waiting = page.get_by_role(
                                "button", name="세계 사건 기다리기 (10분)", exact=True
                            )
                            if not waiting.count():
                                break
                            click("세계 사건 기다리기 (10분)")
                        expect(
                            page.get_by_role("button", name="세계 사건 기다리기 (10분)", exact=True)
                        ).to_have_count(0)
                        expect(page.get_by_label("현재 시장 상황")).to_contain_text(
                            "수송 재개" if exile else "지원 물자 도착"
                        )
                        page.reload()
                        expect(page.get_by_role("region", name="지속 세계 사건")).to_contain_text(
                            "시장 보급 정산"
                        )
                        expect(
                            page.get_by_role("button", name="세계 사건 기다리기 (10분)", exact=True)
                        ).to_have_count(0)
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
                    verify_defeat_recovery(browser)
                    verify_tactical_options(browser)
                    browser.close()
                print(
                    "브라우저 PASS: 지도 NPC/출구 클릭, 3개 선택과 후속 사건·망루 원정 완주, "
                    "구조/문서/동시 확보·귀환 보고·레벨5 성장, "
                    "여관 이후 망루 전투와 후퇴의 원정 합류(실주사위 결과는 위 별도 기록), "
                    "원정 후 지원/미개입에 따른 수송·파벌 복구·시장 가격 변화와 재접속, "
                    "새로고침, 반복 복원, "
                    "전송 전·서버 반영 후 응답 유실/오류의 동일 요청 복구, "
                    "서사 상태 갱신·복구 응답 유실·과거 턴 복구 후 최신 화면 유지, "
                    "전투 패배·쓰러진 저장 복원·3종 치료 후 탐험 재개, "
                    "질주·밀치기·교란의 예산/상태 표시·재접속 유지, "
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
