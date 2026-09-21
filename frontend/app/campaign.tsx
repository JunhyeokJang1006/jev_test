"use client";

import { useEffect, useRef, useState } from "react";
import PixelScene from "./pixel-scene";
import Battlefield from "./battlefield";
import WorldEvents from "./world-events";
import EquipmentPanel from "./equipment-panel";
import { boundedFetch, CAMPAIGN_KEY, clearPending, MUTATION_LOCK, OUTBOX_KEY, readPending, storePending, type PendingTurn } from "./turn-recovery";

type Campaign = { id: string; name: string; state_version: number; state: Record<string, any>; latest_turn?: Turn | null; actions?: string[] };
type Turn = { turn_id: string; state_version: number; narrative: string; narrative_status?: string; dice: Record<string, any>; event: { type: string; payload: Record<string, any> }; state: Record<string, any> };
type Save = { snapshot_id: string; campaign_id: string; campaign_name: string; state_version: number; created_at: string };
type EndingChoice = { ending: "law" | "mercy" | "exile"; command: string; consequence: string; campaignId: string; version: number };

const apiBase = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

export default function CampaignPanel() {
  const initialized = useRef(false);
  const pending = useRef(false);
  const activeCampaignId = useRef<string | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [narrative, setNarrative] = useState("Greyhaven Inn의 문이 빗소리 너머로 흔들린다.");
  const [input, setInput] = useState("나는 문 옆 그림자에 숨어 경비병이 지나가기를 기다린다.");
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(true);
  const [error, setError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [endingChoice, setEndingChoice] = useState<EndingChoice | null>(null);
  const [unresolved, setUnresolved] = useState<PendingTurn | null>(null);
  const [storageBlocked, setStorageBlocked] = useState(false);
  const [campaignChanged, setCampaignChanged] = useState(false);
  const actionsBlocked = busy || starting || !!unresolved || storageBlocked || campaignChanged;
  const [saves, setSaves] = useState<Save[]>([]);
  const [selectedSave, setSelectedSave] = useState("");
  const [saveTotal, setSaveTotal] = useState(0);
  const [saveOffset, setSaveOffset] = useState(0);
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState("");
  const listPending = useRef(false);

  function syncOutbox() {
    try {
      setUnresolved(readPending()); setStorageBlocked(false);
      setCampaignChanged(!!activeCampaignId.current && localStorage.getItem(CAMPAIGN_KEY) !== activeCampaignId.current);
    }
    catch (caught) {
      setStorageBlocked(true);
      setError(caught instanceof Error ? caught.message : "브라우저 저장소에 접근할 수 없습니다.");
    }
  }

  async function mutate(task: () => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try {
      if (!navigator.locks) throw new Error("안전한 행동 복구를 위해 브라우저의 보안 연결 및 Web Locks 지원이 필요합니다.");
      await navigator.locks.request(MUTATION_LOCK, { ifAvailable: true }, async lock => {
        if (!lock) throw new Error("다른 탭에서 처리 중입니다. 잠시 후 다시 시도해 주세요.");
        await task();
      });
    } catch (caught) { setError(caught instanceof Error ? caught.message : "요청을 완료하지 못했습니다."); }
    finally { syncOutbox(); pending.current = false; setBusy(false); }
  }

  async function fetchCampaign(id: string) {
    const response = await boundedFetch(`${apiBase}/api/campaign/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error("캠페인을 가져오지 못했습니다. 연결 확인 후 새로고침해 주세요.");
    const current = await response.json();
    if (current.id !== id || !Number.isSafeInteger(current.state_version) || !current.state || typeof current.state !== "object") throw new Error("캠페인 응답을 확인할 수 없습니다.");
    return current as Campaign;
  }

  function showCampaign(current: Campaign) {
    activeCampaignId.current = current.id;
    setCampaignChanged(localStorage.getItem(CAMPAIGN_KEY) !== current.id);
    setCampaign(current);
    if (current.latest_turn?.narrative) setNarrative(current.latest_turn.narrative);
  }

  function requireResolved() {
    if (readPending()) throw new Error("먼저 미해결 행동을 재시도해 주세요.");
    if (campaign && localStorage.getItem(CAMPAIGN_KEY) !== campaign.id) throw new Error("다른 탭에서 캠페인이 변경되었습니다. 새로고침해 주세요.");
  }

  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === OUTBOX_KEY || event.key === CAMPAIGN_KEY || event.key === null) syncOutbox();
    };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, []);

  async function refreshSaves(preferred?: string, append = false) {
    if (listPending.current) return;
    listPending.current = true; setListBusy(true); setListError("");
    try {
      const offset = append ? saveOffset : 0;
      const response = await boundedFetch(`${apiBase}/api/saves?limit=50&offset=${offset}`);
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
      const recovered = readPending();
      setUnresolved(recovered);
      const savedId = recovered?.envelope.campaign_id ?? window.localStorage.getItem(CAMPAIGN_KEY);
      const response = savedId
        ? await boundedFetch(`${apiBase}/api/campaign/${encodeURIComponent(savedId)}`)
        : await boundedFetch(`${apiBase}/api/campaign`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
      if (!response.ok) { setError("캠페인을 시작할 수 없습니다."); return; }
      const created = await response.json();
      if (!savedId) window.localStorage.setItem(CAMPAIGN_KEY, created.id);
      showCampaign(created);
      } catch { setError("서버에 연결할 수 없습니다. 연결을 확인한 뒤 새로고침해 주세요."); }
      finally { syncOutbox(); setStarting(false); }
    })();
  }, []);

  async function recoverNarration(retry: boolean) {
    if (starting || !campaign?.latest_turn) return;
    await mutate(async () => {
      requireResolved();
      const id = campaign.id;
      const turnId = campaign.latest_turn!.turn_id;
      let inProgress = false;
      if (retry) {
        try {
          const response = await boundedFetch(`${apiBase}/api/campaign/${encodeURIComponent(id)}/turn/${encodeURIComponent(turnId)}/narration`, { method: "POST" });
          const body = await response.json();
          inProgress = response.status === 409 && body?.detail === "narration_in_progress";
          if (!response.ok && !inProgress) throw new Error("narration_retry_failed");
          if (response.ok && (body?.turn_id !== turnId || typeof body?.narrative !== "string")) throw new Error("invalid_narration_response");
        } catch {
          throw new Error("서사 복구 결과를 확인하지 못했습니다. 판정은 다시 실행되지 않습니다. 서사 상태 새로고침으로 확인해 주세요.");
        }
      }
      // A later action may already exist: never replace it with the repaired historical turn.
      const current = await fetchCampaign(id);
      if (current.state_version < campaign.state_version) throw new Error("최신 캠페인 상태를 확인하지 못했습니다.");
      showCampaign(current);
      if (inProgress && current.latest_turn?.turn_id === turnId && current.latest_turn.narrative_status === "pending") {
        setError("서사를 생성 중입니다. 잠시 후 서사 상태를 새로고침해 주세요.");
      }
    });
  }

  async function sendTurn(action = input, confirmation?: EndingChoice, retry = false) {
    if (starting || (!retry && (!campaign || !action.trim()))) return;
    await mutate(async () => {
      let turn = readPending();
      if (!retry) {
        requireResolved();
        if (!campaign || (confirmation && confirmation.campaignId !== campaign.id)) return;
        turn = storePending({ campaign_id: campaign.id, request_id: crypto.randomUUID(), expected_state_version: confirmation?.version ?? campaign.state_version, input: action, ...(confirmation ? { confirmed_ending: confirmation.ending } : {}) });
      }
      if (!turn) return;
      setUnresolved(turn); setEndingChoice(null);
      const response = await boundedFetch(`${apiBase}/api/game/turn`, { method: "POST", headers: { "Content-Type": "application/json" }, body: turn.raw });
      const body = await response.json();
      if (!response.ok) {
        // Only a recognizable, definitive client rejection releases the envelope.
        const definitive = (response.status === 404 && body?.detail === "campaign_not_found")
          || (response.status === 409 && ["stale_state_version", "request_id_reused_with_different_body", "turn_conflict"].includes(body?.detail))
          || (response.status === 422 && (Array.isArray(body?.detail) || typeof body?.detail === "string"))
          || (response.status === 409 && body?.detail?.code === "ending_confirmation_required" && ["law", "mercy", "exile"].includes(body.detail.ending) && typeof body.detail.command === "string" && typeof body.detail.consequence === "string");
        if (!definitive) throw new Error("처리 결과를 확인하지 못했습니다. 같은 행동을 재시도해 주세요.");
        // Preserve recovery until the displayed version is synchronized as well.
        if (response.status !== 404) showCampaign(await fetchCampaign(turn.envelope.campaign_id));
        else { setCampaign(null); activeCampaignId.current = null; }
        clearPending(turn); setUnresolved(null);
        if (response.status === 409 && body.detail?.code === "ending_confirmation_required") {
          setEndingChoice({ ...body.detail, campaignId: turn.envelope.campaign_id, version: turn.envelope.expected_state_version });
          return;
        }
        throw new Error(typeof body.detail === "string" ? body.detail : "턴을 처리할 수 없습니다.");
      }
      if (!body || typeof body.turn_id !== "string" || !Number.isSafeInteger(body.state_version) || body.state_version !== turn.envelope.expected_state_version + 1 || typeof body.narrative !== "string" || !body.state || typeof body.state !== "object" || !Array.isArray(body.actions)) throw new Error("턴 응답을 확인할 수 없습니다. 같은 행동을 재시도해 주세요.");
      // A replay can be older than the campaign: use the authoritative latest view.
      const current = await fetchCampaign(turn.envelope.campaign_id);
      if (current.state_version < body.state_version) throw new Error("최신 상태를 확인할 수 없습니다. 같은 행동을 재시도해 주세요.");
      window.localStorage.setItem(CAMPAIGN_KEY, current.id);
      clearPending(turn); setUnresolved(null); showCampaign(current);
    });
  }

  async function saveCampaign() {
    if (!campaign || listPending.current) return;
    requireResolved();
    try {
    const response = await boundedFetch(`${apiBase}/api/campaign/${campaign.id}/save`, { method: "POST" });
    const body = await response.json();
    if (response.ok) {
      window.localStorage.setItem("luna-realms-snapshot-id", body.snapshot_id);
      window.localStorage.setItem("luna-realms-snapshot-source", campaign.id);
      await refreshSaves(body.snapshot_id);
    }
    setSaveMessage(response.ok ? `세이브 완료 · ${body.snapshot_id.slice(0, 8)}` : "세이브 실패");
    } catch { setSaveMessage("연결 오류로 저장하지 못했습니다."); }
  }

  async function loadCampaign() {
    if (starting || listPending.current) return;
    requireResolved();
    const snapshot = saves.find(item => item.snapshot_id === selectedSave);
    if (!snapshot) { setSaveMessage("복원할 저장을 선택해 주세요."); return; }
    try {
    const response = await boundedFetch(`${apiBase}/api/campaign/${snapshot.campaign_id}/load`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ snapshot_id: snapshot.snapshot_id }) });
    if (!response.ok) { setSaveMessage("세이브를 불러올 수 없습니다."); return; }
    const restored = await response.json();
    window.localStorage.setItem("luna-realms-campaign-id", restored.id);
    showCampaign(restored);
    setEndingChoice(null);
    setError("");
    setNarrative("저장된 캠페인을 복원했습니다.");
    setSaveMessage("복원 완료");
    } catch { setSaveMessage("연결 오류로 복원하지 못했습니다."); }
  }

  return <section className="campaign" aria-label="Greyhaven 캠페인">
    <div className="campaign-heading"><div><p className="eyebrow">{campaign?.state.location_name ?? "GREYHAVEN"}</p><h2>{campaign?.name ?? "캠페인 준비 중"}</h2></div><span>{campaign?.state.day ?? 1}일 · {campaign?.state.time ?? "21:36"}</span></div>
    {campaign && (campaign.state.combat?.active ? <Battlefield combat={campaign.state.combat} stats={campaign.state.effective_stats} actions={campaign.actions ?? []} busy={actionsBlocked} onAction={action => void sendTurn(action)} /> : <PixelScene state={campaign.state} actions={campaign.actions ?? []} busy={actionsBlocked} onAction={action => void sendTurn(action)} />)}
    <p className="narrative">{narrative}</p>
    {["pending", "failed"].includes(campaign?.latest_turn?.narrative_status ?? "") && <section aria-label="서사 복구">
      <p className="note">판정은 저장되었습니다. {campaign?.latest_turn?.narrative_status === "failed" ? "AI 서사를 만들지 못해 판정 원문을 표시합니다." : "서사는 아직 완료되지 않았습니다."} 복구해도 주사위·보상·시간은 다시 처리하지 않습니다.</p>
      <button className="secondary" type="button" disabled={actionsBlocked} onClick={() => void recoverNarration(false)}>서사 상태 새로고침</button>
      <button className="secondary" type="button" disabled={actionsBlocked} onClick={() => void recoverNarration(true)}>서사만 다시 생성</button>
    </section>}
    {campaignChanged && <p className="error" role="alert">다른 탭에서 캠페인이 변경되었습니다. 새로고침해 현재 캠페인을 불러와 주세요.</p>}
    {campaign && campaign.state.player?.hp <= 0 && <section aria-label="패배 후 진행">
      <h3>쓰러졌지만 모험은 이어집니다</h3>
      {(campaign.actions ?? []).some(action => /^(응급 치료 받기|보급품으로 치료하기|도움을 기다리기)/.test(action)) ? <>
        <p>아래 치료 행동을 선택하면 HP {Math.max(1, Math.floor(campaign.state.player.max_hp / 2))}로 회복합니다. 응급 치료는 10골드·1시간, 보급품 치료는 보급품 1개·4시간, 도움을 기다리면 자원 없이 8시간이 필요합니다.</p>
        <p>시간은 실제 게임 시간에 반영됩니다. 퀘스트와 단서는 유지되지만 패배는 승리로 바뀌지 않고 경험치도 얻지 않습니다. 이전 저장에서 다시 도전할 수도 있습니다.</p>
      </> : <p>현재 상태에서는 치료 행동이 없습니다. 이전 저장을 복원해 다시 도전할 수 있습니다.</p>}
    </section>}
    {campaign?.state.defeat?.status === "recovered" && <p className="note" aria-label="패배의 대가">패배 후 회복 · {campaign.state.defeat.minutes}분 경과 · 골드 {campaign.state.defeat.gold_spent} / 보급품 {campaign.state.defeat.supplies_spent} 소비. 이전 전투의 패배 기록은 유지됩니다.</p>}
    <div className="facts"><span>Kael · HP {campaign?.state.player?.hp ?? 31}/{campaign?.state.player?.max_hp ?? 37}</span><span>{campaign?.state.hidden ? "은신 중" : "노출 상태"}</span>{campaign?.state.combat?.active && <span>전투 · 생존 적 {(campaign.state.combat.enemies ?? [{ hp: campaign.state.combat.enemy_hp }]).filter((enemy: { hp: number }) => enemy.hp > 0).length}명</span>}</div>
    <p>주변 인물: {(campaign?.state.npcs ?? []).map((npc: { name: string }) => npc.name).join(", ") || "없음"}</p>
    {campaign?.state.expedition && <section aria-label="망루 원정">
      <h3>{campaign.state.expedition.title}</h3>
      <p>{campaign.state.expedition.objective}</p>
      <p>확보한 단서 {(campaign.state.expedition.clues ?? []).length}개 · {campaign.state.expedition.status === "completed" ? "보고 완료" : campaign.state.expedition.status === "resolved" ? "현장 해결 · 시장으로 돌아가 보고하세요" : "진행 중"}</p>
      {campaign.state.expedition.approach === "combat" && <p>진입로 확보: 매복자를 물리쳤습니다.{campaign.state.expedition.status === "active" ? " 단서를 확인하고 구조 대상을 선택하세요." : ""}</p>}
      {campaign.state.expedition.status === "active" && <p>두 대상을 모두 구할 기회까지 {Math.max(0, campaign.state.expedition.deadline_at - (campaign.state.elapsed_minutes ?? 0))}분. 이동·휴식·작업 시간도 포함됩니다. 기한을 넘겨도 한 대상을 선택해 진행할 수 있습니다.</p>}
      {campaign.state.expedition.resolution && <p>{campaign.state.expedition.resolution}</p>}
      <p>설득·잠입은 각각 한 번만 시도할 수 있습니다. 실패해도 안전한 작업으로 진행할 수 있습니다. 동시 구출에는 두 단서와 로프, 최종 작업 5분이 필요합니다.</p>
    </section>}
    {campaign && <WorldEvents events={campaign.state.world_events ?? []} factions={campaign.state.factions ?? {}} elapsed={campaign.state.elapsed_minutes ?? 0} marketPolicy={campaign.state.market_policy} />}
    {campaign && <EquipmentPanel equipment={campaign.state.equipment} stats={campaign.state.effective_stats} />}
    {campaign?.state.progression && <section aria-label="캐릭터 성장">
      <p>레벨 {campaign.state.progression.level} · 경험치 {campaign.state.progression.xp} / {campaign.state.progression.next_level_xp ?? "현재 성장 상한"}</p>
      <p>기본 능력(성장 포함): 공격 +{campaign.state.player.attack_bonus ?? 5} · 은신 +{campaign.state.player.stealth_bonus ?? 5} · 설득 +{campaign.state.player.persuasion_bonus ?? 3}</p>
      <p>성장은 1시간 수련으로 최대 HP +5와 선택한 기술을 강화합니다. 전투 +1, 은신/설득 +2 중 선택하세요.</p>
    </section>}
    {campaign?.state.resources && <section aria-label="회복과 보급">
      <p>골드 {campaign.state.resources.gold ?? 0} · 치유 물약 {campaign.state.resources.healing_potions ?? 0} · 야영 보급품 {campaign.state.resources.camp_supplies ?? 0} · 회복 주사위 {campaign.state.resources.hit_dice ?? 0}/2</p>
      <p>물약: 2d4+2 회복, 전투 중에는 보조 행동 1회. 여관 짧은 휴식: 1시간·회복 주사위 1개로 1d8+2. 긴 휴식: 8시간·보급품 1개로 완전 회복.</p>
    </section>}
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
    {campaign?.latest_turn?.dice?.roll != null && <p aria-label="최근 판정">주사위 {campaign.latest_turn.dice.roll} + {campaign.latest_turn.dice.bonus ?? 0} = {campaign.latest_turn.dice.total ?? campaign.latest_turn.dice.roll} · {campaign.latest_turn.dice.dc != null ? `DC ${campaign.latest_turn.dice.dc}` : "전투 판정"} · {campaign.latest_turn.dice.outcome}{campaign.latest_turn.event.payload.attack_rolls?.length === 2 && <span> · 공격 굴림 [{campaign.latest_turn.event.payload.attack_rolls.join(", ")}] 중 높은 값 선택</span>}</p>}
    {campaign?.state.world_consequences && <p aria-label="세계 변화">통행세: {({ suspended: "징수 잠정 중단", contested: "공개 분쟁", unchanged: "변화 없음" } as Record<string, string>)[campaign.state.world_consequences.tax_collection]} · 피난민: {campaign.state.world_consequences.refugees === "evacuated" ? "피난 완료" : "도시 잔류"}</p>}
    {campaign?.state.world_effects && <p aria-label="도시 공고">{campaign.state.world_events?.some((event: { status: string }) => event.status === "resolved") ? "이전 도시 공고: " : ""}{campaign.state.world_effects.applied ? campaign.state.world_effects.notice : `사건의 소식이 퍼지고 있습니다. 공고까지 ${Math.max(0, campaign.state.world_effects.effective_at - (campaign.state.elapsed_minutes ?? 0))}분.`}</p>}
    <nav aria-label="가능한 행동">{campaign?.actions?.map(action => <button className="secondary" key={action} type="button" disabled={actionsBlocked} onClick={() => void sendTurn(action)}>{action}</button>)}</nav>
    <label htmlFor="action">행동</label><textarea id="action" value={input} onChange={(event) => setInput(event.target.value)} disabled={!campaign || actionsBlocked} />
    <button type="button" onClick={() => void sendTurn()} disabled={!campaign || actionsBlocked}>{busy ? "판정 중…" : "행동 보내기"}</button>
    {unresolved && <section aria-label="행동 복구" role="alert">
      <p>이전 행동의 처리 결과를 확인해야 합니다. 새 행동과 저장·복원은 확인 후 사용할 수 있습니다.</p>
      <p>미해결 행동: {unresolved.envelope.input}</p>
      <button type="button" disabled={busy || starting || storageBlocked} onClick={() => void sendTurn(undefined, undefined, true)}>같은 행동 재시도</button>
    </section>}
    {endingChoice && <section aria-label="결말 선택 확인" role="alert">
      <h3>{endingChoice.command} — 이 선택을 확정할까요?</h3>
      <p>{endingChoice.consequence}</p>
      <p>확정 전에는 상태가 바뀌지 않습니다. 필요하면 먼저 세이브하세요.</p>
      <button type="button" disabled={actionsBlocked} onClick={() => void sendTurn(endingChoice.command, endingChoice)}>결말 확정</button>
      <button className="secondary" type="button" disabled={actionsBlocked} onClick={() => setEndingChoice(null)}>선택 취소</button>
    </section>}
    <button className="secondary" type="button" onClick={() => void mutate(saveCampaign)} disabled={!campaign || actionsBlocked || listBusy}>세이브</button>
    <label htmlFor="save-slot">저장 선택 ({saveTotal})</label>
    <select id="save-slot" style={{ width: "100%", minWidth: 0 }} value={selectedSave} onChange={event => setSelectedSave(event.target.value)} disabled={busy || listBusy || !saves.length}>
      {!saves.length && <option value="">저장 없음</option>}
      {saves.map(save => <option key={save.snapshot_id} value={save.snapshot_id}>{save.campaign_name} · v{save.state_version} · {new Date(save.created_at).toLocaleString("ko-KR")} · {save.snapshot_id.slice(0, 8)}</option>)}
    </select>
    <button className="secondary" type="button" onClick={() => void refreshSaves()} disabled={busy || listBusy}>목록 새로고침</button>
    {saveOffset < saveTotal && <button className="secondary" type="button" onClick={() => void refreshSaves(undefined, true)} disabled={busy || listBusy}>이전 저장 더 불러오기</button>}
    <button className="secondary" type="button" onClick={() => void mutate(loadCampaign)} disabled={!selectedSave || actionsBlocked || listBusy}>복원</button>
    {listError && <p className="error" role="alert">{listError}</p>}
    {campaign && campaign.state.journal?.length > 0 && <details><summary>모험 기록 ({campaign.state.journal.length})</summary><ol>{campaign.state.journal.map((entry: { text: string; day: number; time: string }, index: number) => <li key={index}>{entry.day}일 {entry.time} · {entry.text}</li>)}</ol></details>}
    {saveMessage && <p className="note">{saveMessage}</p>}
    {error && <p className="error" role="alert">{error}</p>}
  </section>;
}
