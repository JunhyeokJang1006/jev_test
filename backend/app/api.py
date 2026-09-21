"""캠페인과 플레이어 턴 API."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .ai import interpret_action, jev_route, with_narration
from .game import resolve_action
from .projection import public_state, public_turn
from .storage import connect, json_hash, migrate, read_campaign
from .world import COMMANDS, available_actions, prepare

router = APIRouter(prefix="/api")


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Greyhaven의 첫 밤", min_length=1, max_length=120)


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str
    request_id: UUID = Field(default_factory=uuid.uuid4)
    expected_state_version: int = Field(ge=0)
    input: str = Field(min_length=1, max_length=4000)
    confirmed_ending: Literal["law", "mercy", "exile"] | None = None


class LoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=1, max_length=80)


def now() -> str:
    return datetime.now(UTC).isoformat()


def public_campaign(campaign: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": campaign["id"],
        "name": campaign["name"],
        "state_version": campaign["state_version"],
        "state": public_state(campaign["state"]),
        "latest_turn": public_turn(campaign["latest_turn"])
        if campaign.get("latest_turn")
        else None,
        "actions": available_actions(campaign["state"]),
    }


@router.post("/campaign", status_code=201)
def create_campaign(request: CampaignCreate) -> dict[str, Any]:
    campaign_id = str(uuid.uuid4())
    state = {
        "location_id": "greyhaven_inn",
        "location_name": "Greyhaven Inn",
        "day": 1,
        "time": "21:36",
        "hidden": False,
        "player": {
            "id": "player_001",
            "name": "Kael",
            "hp": 31,
            "max_hp": 37,
            "ac": 17,
            "stealth_bonus": 5,
        },
        "nearby_object_ids": ["door_inn"],
        "encounter_enemy_id": "goblin_001",
        "npcs": [
            {"id": "npc_harlan", "name": "Harlan", "disposition": "suspicious"},
            {"id": "npc_mira", "name": "Mira", "disposition": "neutral"},
        ],
    }
    state = prepare(state)
    connection = connect()
    try:
        migrate(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO campaigns (id, name, ruleset_version, state_schema_version, "
            "state_version, state_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                campaign_id,
                request.name,
                "srd-5.2.1-subset-v1",
                1,
                0,
                json.dumps(state, ensure_ascii=False),
                now(),
            ),
        )
        connection.commit()
    finally:
        connection.close()
    return public_campaign(
        {
            "id": campaign_id,
            "name": request.name,
            "state_version": 0,
            "state": state,
            "latest_turn": None,
        }
    )


@router.get("/campaign/{campaign_id}")
def get_campaign(campaign_id: str) -> dict[str, Any]:
    connection = connect()
    try:
        migrate(connection)
        campaign = read_campaign(connection, campaign_id)
    finally:
        connection.close()
    if campaign is None:
        raise HTTPException(404, "campaign_not_found")
    return public_campaign(campaign)


@router.get("/saves")
def list_saves(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
) -> dict[str, Any]:
    """로컬 단일 사용자 저장 목록. 내부 상태/지식은 반환하지 않는다."""
    connection = connect()
    try:
        migrate(connection)
        connection.execute("BEGIN")
        total = connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        rows = connection.execute(
            "SELECT s.id AS snapshot_id, s.campaign_id, c.name AS campaign_name, "
            "s.source_state_version AS state_version, s.created_at "
            "FROM snapshots s JOIN campaigns c ON c.id=s.campaign_id "
            "ORDER BY s.created_at DESC, s.id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return {"snapshots": [dict(row) for row in rows], "total": total}
    finally:
        connection.close()


@router.post("/campaign/{campaign_id}/save", status_code=201)
def save_campaign(campaign_id: str) -> dict[str, Any]:
    connection = connect()
    snapshot_id = str(uuid.uuid4())
    try:
        migrate(connection)
        connection.execute("BEGIN IMMEDIATE")
        campaign = read_campaign(connection, campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign_not_found")
        state_json = json.dumps(campaign["state"], ensure_ascii=False, sort_keys=True)
        connection.execute(
            "INSERT INTO snapshots (id, campaign_id, source_state_version, state_json, "
            "state_hash, created_at, ruleset_version, state_schema_version, last_sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot_id,
                campaign_id,
                campaign["state_version"],
                state_json,
                json_hash(campaign["state"]),
                now(),
                campaign["ruleset_version"],
                campaign["state_schema_version"],
                connection.execute(
                    "SELECT COALESCE(MAX(sequence),0) FROM events WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchone()[0],
            ),
        )
        connection.commit()
        return {
            "snapshot_id": snapshot_id,
            "campaign_id": campaign_id,
            "state_version": campaign["state_version"],
        }
    except HTTPException:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.post("/campaign/{campaign_id}/load", status_code=201)
def load_campaign(campaign_id: str, request: LoadRequest) -> dict[str, Any]:
    connection = connect()
    try:
        migrate(connection)
        connection.execute("BEGIN IMMEDIATE")
        snapshot = connection.execute(
            "SELECT * FROM snapshots WHERE id = ? AND campaign_id = ?",
            (request.snapshot_id, campaign_id),
        ).fetchone()
        if snapshot is None:
            raise HTTPException(404, "snapshot_not_found")
        try:
            restored_state = json.loads(snapshot["state_json"])
        except (ValueError, TypeError) as error:
            raise HTTPException(409, "snapshot_corrupted") from error
        if (
            not isinstance(restored_state, dict)
            or json_hash(restored_state) != snapshot["state_hash"]
        ):
            raise HTTPException(409, "snapshot_corrupted")
        if (
            snapshot["state_schema_version"] != 1
            or snapshot["ruleset_version"] != "srd-5.2.1-subset-v1"
        ):
            raise HTTPException(409, "snapshot_version_unsupported")
        source = connection.execute(
            "SELECT name FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if source is None:
            raise HTTPException(404, "campaign_not_found")
        new_id = str(uuid.uuid4())
        name = f"{source['name']} · 복원"
        connection.execute(
            "INSERT INTO campaigns (id, name, ruleset_version, state_schema_version, "
            "state_version, state_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                new_id,
                name,
                snapshot["ruleset_version"],
                snapshot["state_schema_version"],
                0,
                snapshot["state_json"],
                now(),
            ),
        )
        connection.commit()
        return public_campaign(
            {
                "id": new_id,
                "name": name,
                "state_version": 0,
                "state": restored_state,
                "latest_turn": None,
            }
        )
    except HTTPException:
        connection.rollback()
        raise
    finally:
        connection.close()


@router.post("/game/turn")
def play_turn(request: TurnRequest) -> dict[str, Any]:
    request_id = str(request.request_id)
    request_body = {
        "campaign_id": request.campaign_id,
        "input": request.input,
        "expected_state_version": request.expected_state_version,
    }
    if request.confirmed_ending is not None:
        request_body["confirmed_ending"] = request.confirmed_ending
        if COMMANDS.get(request.input.strip()) != ("finish_quest", request.confirmed_ending):
            raise HTTPException(422, "ending_confirmation_mismatch")
    request_hash = json_hash(request_body)
    connection = connect()
    turn_id = str(uuid.uuid4())
    try:
        migrate(connection)
        campaign = read_campaign(connection, request.campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign_not_found")
        existing = connection.execute(
            "SELECT * FROM turns WHERE campaign_id = ? AND request_id = ?",
            (request.campaign_id, request_id),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "request_id_reused_with_different_body")
            outcome = json.loads(existing["outcome_json"])
            connection.rollback()
            return public_turn(outcome)
        if campaign["state_version"] != request.expected_state_version:
            raise HTTPException(409, "stale_state_version")
        jev = jev_route(request.input)
        proposal, provider = interpret_action(request.input, campaign["state"])
        connection.execute("BEGIN IMMEDIATE")
        campaign = read_campaign(connection, request.campaign_id)
        if campaign is None:
            raise HTTPException(404, "campaign_not_found")
        existing = connection.execute(
            "SELECT * FROM turns WHERE campaign_id = ? AND request_id = ?",
            (request.campaign_id, request_id),
        ).fetchone()
        if existing is not None:
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "request_id_reused_with_different_body")
            return public_turn(json.loads(existing["outcome_json"]))
        if campaign["state_version"] != request.expected_state_version:
            raise HTTPException(409, "stale_state_version")
        if proposal.intent == "finish_quest":
            command = (
                next(
                    (
                        label
                        for label in available_actions(campaign["state"])
                        if COMMANDS.get(label) == ("finish_quest", proposal.target_ids[0])
                    ),
                    None,
                )
                if len(proposal.target_ids) == 1
                else None
            )
            if command is None:
                raise HTTPException(422, "ending_not_available")
            if request.confirmed_ending != proposal.target_ids[0]:
                consequences = {
                    "law": "봉인을 하를란에게 넘기고 경비대의 신뢰를 얻습니다.",
                    "mercy": "봉인을 미라에게 넘기고 그녀의 약속을 믿기로 합니다.",
                    "exile": "봉인을 소지한 채 도시를 떠납니다.",
                }
                raise HTTPException(
                    409,
                    {
                        "code": "ending_confirmation_required",
                        "ending": proposal.target_ids[0],
                        "command": command,
                        "consequence": consequences[proposal.target_ids[0]]
                        + " 현재 모험은 종료됩니다. 다른 선택은 이전 저장에서 진행할 수 있습니다.",
                    },
                )
        try:
            resolved = resolve_action(campaign["state"], proposal)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE campaign_id = ?",
            (request.campaign_id,),
        ).fetchone()[0]
        outcome = {
            "turn_id": turn_id,
            "state_version": campaign["state_version"] + 1,
            "narrative": resolved.narrative,
            "dice": resolved.dice,
            "event": {"type": resolved.event_type, "payload": resolved.event_payload},
            "state": resolved.state,
            "actions": available_actions(resolved.state),
            "ai": {"interpreter": provider, "narrator": "mock"},
            "narrative_status": "pending",
            "jev": jev,
        }
        connection.execute(
            "INSERT INTO turns (id, campaign_id, request_id, request_hash, "
            "expected_state_version, resulting_state_version, status, outcome_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn_id,
                request.campaign_id,
                request_id,
                request_hash,
                request.expected_state_version,
                campaign["state_version"] + 1,
                "committed",
                json.dumps(outcome, ensure_ascii=False),
                now(),
            ),
        )
        updated = connection.execute(
            "UPDATE campaigns SET state_version = ?, state_json = ? "
            "WHERE id = ? AND state_version = ?",
            (
                campaign["state_version"] + 1,
                json.dumps(resolved.state, ensure_ascii=False),
                request.campaign_id,
                request.expected_state_version,
            ),
        )
        if updated.rowcount != 1:
            raise HTTPException(409, "stale_state_version")
        connection.execute(
            "INSERT INTO events (id, campaign_id, turn_id, sequence, event_schema_version, "
            "type, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                request.campaign_id,
                turn_id,
                sequence,
                1,
                resolved.event_type,
                json.dumps(resolved.event_payload, ensure_ascii=False),
                now(),
            ),
        )
        connection.commit()
        # 판정은 이미 영속화됐다. 서사 오류는 확정된 턴을 되돌리지 않는다.
        try:
            narrated, narration_provider = with_narration(request.input, resolved, provider)
            completed = {
                **outcome,
                "narrative": narrated.narrative,
                "ai": {"interpreter": provider, "narrator": narration_provider},
                "narrative_status": (
                    "failed" if provider != "mock" and narration_provider == "mock" else "completed"
                ),
            }
        except Exception:
            completed = {**outcome, "narrative_status": "failed"}
        try:
            connection.execute(
                "UPDATE turns SET outcome_json = ?, status = ? WHERE id = ? AND status = ?",
                (
                    json.dumps(completed, ensure_ascii=False),
                    "narrative_failed"
                    if completed["narrative_status"] == "failed"
                    else "completed",
                    turn_id,
                    "committed",
                ),
            )
        except sqlite3.Error:
            # 저장 실패 시 재조회와 동일한 commit 시점의 안전한 결과를 반환한다.
            return public_turn(outcome)
        return public_turn(completed)
    except HTTPException:
        connection.rollback()
        raise
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise HTTPException(409, "turn_conflict") from error
    except sqlite3.OperationalError as error:
        connection.rollback()
        raise HTTPException(503, "database_busy_or_unavailable") from error
    finally:
        connection.close()
