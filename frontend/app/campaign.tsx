"use client";

import { useEffect, useRef, useState } from "react";
import PixelScene from "./pixel-scene";

type Campaign = { id: string; name: string; state_version: number; state: Record<string, any>; latest_turn?: Turn | null; actions?: string[] };
type Turn = { turn_id: string; state_version: number; narrative: string; dice: Record<string, any>; event: { type: string; payload: Record<string, any> }; state: Record<string, any> };
type Save = { snapshot_id: string; campaign_id: string; campaign_name: string; state_version: number; created_at: string };
type EndingChoice = { ending: "law" | "mercy" | "exile"; command: string; consequence: string; campaignId: string; version: number };

const apiBase = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export default function CampaignPanel() {
  const initialized = useRef(false);
  const pending = useRef(false);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [narrative, setNarrative] = useState("Greyhaven Inn의 문이 빗소리 너머로 흔들린다.");
  const [input, setInput] = useState("나는 문 옆 그림자에 숨어 경비병이 지나가기를 기다린다.");
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(true);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [endingChoice, setEndingChoice] = useState<EndingChoice | null>(null);
  const [saves, setSaves] = useState<Save[]>([]);
  const [selectedSave, setSelectedSave] = useState("");
  const [saveTotal, setSaveTotal] = useState(0);
  const [saveOffset, setSaveOffset] = useState(0);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState("");
  const listPending = useRef(false);

  async function refreshSaves(preferred?: string, append = false) {
    if (listPending.current) return;
    listPending.current = true; setListBusy(true); setListError("");
    try {
      const offset = append ? saveOffset : 0;
      const response = await fetch(`${apiBase}/api/saves?limit=50&offset=${offset}`, { cache: "no-store" });
      if (!response.ok) throw new Error("save_list_failed");
      const body: { snapshots: Save[]; total: number } = await response.json();
      const merged = append ? [...saves, ...body.snapshots.filter(item => !saves.some(old => old.snapshot_id === item.snapshot_id))] : body.snapshots;
      setSaves(merged); setSaveTotal(body.total);
      setSaveOffset(offset + body.snapshots.length);
      setSelectedSave(current => {
        const candidate = preferred ?? current;
        return merged.some(item => item.snapshot_id === candidate) ? candidate : (merged[0]?.snapshot_id ?? "");
      });
    } catch { setListError("저장 목록을 가져오지 못했습니다. 목록 새로고침으로 다시 시도해 주세요."); }
    finally { listPending.current = false; setListBusy(false); }
  }

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void refreshSaves();
    void (async () => {
      try {
      const savedId = window.localStorage.getItem("luna-realms-campaign-id");
      const response = savedId
        ? await fetch(`${apiBase}/api/campaign/${savedId}`)
        : await fetch(`${apiBase}/api/campaign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      if (!response.ok) { setError("캠페인을 시작할 수 없습니다."); return; }
      const created = await response.json();
      window.localStorage.setItem("luna-realms-campaign-id", created.id);
      setCampaign(created);
      if (created.latest_turn?.narrative) setNarrative(created.latest_turn.narrative);
      } catch { setError("서버에 연결할 수 없습니다. 연결을 확인한 뒤 새로고침해 주세요."); }
      finally { setStarting(false); }
    })();
  }, []);

  async function sendTurn(action = input, confirmation?: EndingChoice) {
    if (!campaign || pending.current || !action.trim()) return;
    if (confirmation && confirmation.campaignId !== campaign.id) { setEndingChoice(null); return; }
    pending.current = true;
    setEndingChoice(null);
    setBusy(true); setError("");
    try {
      const requestId = crypto.randomUUID();
      const response = await fetch(`${apiBase}/api/game/turn`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ campaign_id: campaign.id, request_id: requestId, expected_state_version: confirmation?.version ?? campaign.state_version, input: action, ...(confirmation ? { confirmed_ending: confirmation.ending } : {}) }) });
      const body = await response.json();
      if (!response.ok) {
        if (response.status === 409 && body.detail?.code === "ending_confirmation_required") {
          setEndingChoice({ ...body.detail, campaignId: campaign.id, version: campaign.state_version });
          return;
        }
        if (response.status === 409) {
          const refreshed = await fetch(`${apiBase}/api/campaign/${campaign.id}`);
          if (refreshed.ok) {
            const current = await refreshed.json();
            setCampaign(current);
            if (current.latest_turn?.narrative) setNarrative(current.latest_turn.narrative);
          }
        }
        throw new Error(body.detail ?? "턴을 처리할 수 없습니다.");
      }
      setNarrative(body.narrative); setCampaign({ ...campaign, state_version: body.state_version, state: body.state, actions: body.actions, latest_turn: body });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "알 수 없는 오류"); }
    finally { pending.current = false; setBusy(false); }
  }

  async function saveCampaign() {
    if (!campaign || pending.current || listPending.current) return;
    pending.current = true; setBusy(true);
    try {
    const response = await fetch(`${apiBase}/api/campaign/${campaign.id}/save`, { method: "POST" });
    const body = await response.json();
    if (response.ok) {
      window.localStorage.setItem("luna-realms-snapshot-id", body.snapshot_id);
      window.localStorage.setItem("luna-realms-snapshot-source", campaign.id);
      await refreshSaves(body.snapshot_id);
    }
    setSaveMessage(response.ok ? `세이브 완료 · ${body.snapshot_id.slice(0, 8)}` : "세이브 실패");
    } catch { setSaveMessage("연결 오류로 저장하지 못했습니다."); }
    finally { pending.current = false; setBusy(false); }
  }

  async function loadCampaign() {
    if (starting || pending.current || listPending.current) return;
    const snapshot = saves.find(item => item.snapshot_id === selectedSave);
    if (!snapshot) { setSaveMessage("복원할 저장을 선택해 주세요."); return; }
    pending.current = true; setBusy(true);
    try {
    const response = await fetch(`${apiBase}/api/campaign/${snapshot.campaign_id}/load`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ snapshot_id: snapshot.snapshot_id }) });
    if (!response.ok) { setSaveMessage("세이브를 불러올 수 없습니다."); return; }
    const restored = await response.json();
    window.localStorage.setItem("luna-realms-campaign-id", restored.id);
    setCampaign(restored);
    setEndingChoice(null);
    setError("");
    setNarrative("저장된 캠페인을 복원했습니다.");
    setSaveMessage("복원 완료");
    } catch { setSaveMessage("연결 오류로 복원하지 못했습니다."); }
    finally { pending.current = false; setBusy(false); }
  }

  return <section className="campaign" aria-label="Greyhaven 캠페인">
    <div className="campaign-heading"><div><p className="eyebrow">{campaign?.state.location_name ?? "GREYHAVEN"}</p><h2>{campaign?.name ?? "캠페인 준비 중"}</h2></div><span>{campaign?.state.day ?? 1}일 · {campaign?.state.time ?? "21:36"}</span></div>
    {campaign && <PixelScene state={campaign.state} actions={campaign.actions ?? []} busy={busy} onAction={action => void sendTurn(action)} />}
    <p className="narrative">{narrative}</p>
    <div className="facts"><span>Kael · HP {campaign?.state.player?.hp ?? 31}/{campaign?.state.player?.max_hp ?? 37}</span><span>{campaign?.state.hidden ? "은신 중" : "노출 상태"}</span>{campaign?.state.combat?.active && <span>전투 · Goblin HP {campaign.state.combat.enemy_hp}</span>}</div>
    <p>주변 인물: {(campaign?.state.npcs ?? []).map((npc: { name: string }) => npc.name).join(", ") || "없음"}</p>
    {campaign?.state.quest && <div aria-label="퀘스트">
      <h3>{campaign.state.quest.title}</h3>
      <p>{campaign.state.quest.ending_title ?? (campaign.state.quest.status === "recovered" ? "봉인을 회수했습니다. 누구에게 전달할까요?" : "도난당한 봉인의 행방을 조사하세요.")}</p>
      <p>소지품: {campaign.state.inventory?.includes("royal_seal") ? "왕실 봉인" : "없음"}</p>
    </div>}
    {campaign?.state.followup && <section aria-label="후속 사건">
      <h3>{campaign.state.followup.title}</h3>
      <p>{campaign.state.followup.resolution ?? campaign.state.followup.objective}</p>
      <p>진행: {campaign.state.followup.status === "completed" ? "해결" : "조사 중"} · 확보한 단서 {campaign.state.followup.evidence.length}/2</p>
      {campaign.state.followup.status === "active" && <p>정식 확보: 15분, 판정 없음. 설득·몰래 접근: DC 14, 단서마다 한 번. 성공 2분, 실패 5분이며 이후 정식 확보에 25분이 걸립니다.</p>}
      {(campaign.state.followup.complications ?? []).length > 0 && <p>발생한 문제: {campaign.state.followup.complications.map((item: string) => item === "oren_reluctant" ? "오렌의 경계" : "창고 경계 강화").join(", ")}</p>}
    </section>}
    {campaign?.latest_turn?.dice?.roll != null && <p aria-label="최근 판정">주사위 {campaign.latest_turn.dice.roll} + {campaign.latest_turn.dice.bonus ?? 0} = {campaign.latest_turn.dice.total ?? campaign.latest_turn.dice.roll} · {campaign.latest_turn.dice.dc != null ? `DC ${campaign.latest_turn.dice.dc}` : "전투 판정"} · {campaign.latest_turn.dice.outcome}</p>}
    {campaign?.state.world_consequences && <p aria-label="세계 변화">통행세: {({ suspended: "징수 잠정 중단", contested: "공개 분쟁", unchanged: "변화 없음" } as Record<string, string>)[campaign.state.world_consequences.tax_collection]} · 피난민: {campaign.state.world_consequences.refugees === "evacuated" ? "피난 완료" : "도시 잔류"}</p>}
    <nav aria-label="가능한 행동">{campaign?.actions?.map(action => <button className="secondary" key={action} type="button" disabled={busy} onClick={() => void sendTurn(action)}>{action}</button>)}</nav>
    <label htmlFor="action">행동</label><textarea id="action" value={input} onChange={(event) => setInput(event.target.value)} disabled={!campaign || busy} />
    <button type="button" onClick={() => void sendTurn()} disabled={!campaign || busy}>{busy ? "판정 중…" : "행동 보내기"}</button>
    {endingChoice && <section aria-label="결말 선택 확인" role="alert">
      <h3>{endingChoice.command} — 이 선택을 확정할까요?</h3>
      <p>{endingChoice.consequence}</p>
      <p>확정 전에는 상태가 바뀌지 않습니다. 필요하면 먼저 세이브하세요.</p>
      <button type="button" disabled={busy} onClick={() => void sendTurn(endingChoice.command, endingChoice)}>결말 확정</button>
      <button className="secondary" type="button" disabled={busy} onClick={() => setEndingChoice(null)}>선택 취소</button>
    </section>}
    <button className="secondary" type="button" onClick={() => void saveCampaign()} disabled={!campaign || busy || listBusy}>세이브</button>
    <label htmlFor="save-slot">저장 선택 ({saveTotal})</label>
    <select id="save-slot" style={{ width: "100%", minWidth: 0 }} value={selectedSave} onChange={event => setSelectedSave(event.target.value)} disabled={busy || listBusy || !saves.length}>
      {!saves.length && <option value="">저장 없음</option>}
      {saves.map(save => <option key={save.snapshot_id} value={save.snapshot_id}>{save.campaign_name} · v{save.state_version} · {new Date(save.created_at).toLocaleString("ko-KR")} · {save.snapshot_id.slice(0, 8)}</option>)}
    </select>
    <button className="secondary" type="button" onClick={() => void refreshSaves()} disabled={busy || listBusy}>목록 새로고침</button>
    {saveOffset < saveTotal && <button className="secondary" type="button" onClick={() => void refreshSaves(undefined, true)} disabled={busy || listBusy}>이전 저장 더 불러오기</button>}
    <button className="secondary" type="button" onClick={() => void loadCampaign()} disabled={starting || !selectedSave || busy || listBusy}>복원</button>
    {listError && <p className="error" role="alert">{listError}</p>}
    {campaign && campaign.state.journal?.length > 0 && <details><summary>모험 기록 ({campaign.state.journal.length})</summary><ol>{campaign.state.journal.map((entry: { text: string; day: number; time: string }, index: number) => <li key={index}>{entry.day}일 {entry.time} · {entry.text}</li>)}</ol></details>}
    {saveMessage && <p className="note">{saveMessage}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
