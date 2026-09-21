// This is a transport outbox, never an authoritative game-state store.
export const OUTBOX_KEY = "luna-realms-turn-outbox";
export const CAMPAIGN_KEY = "luna-realms-campaign-id";
export const MUTATION_LOCK = "luna-realms-campaign-mutation";
export type Envelope = {
  campaign_id: string;
  request_id: string;
  expected_state_version: number;
  input: string;
  confirmed_ending?: "law" | "mercy" | "exile";
};
export type PendingTurn = { raw: string; envelope: Envelope };

export function readPending(): PendingTurn | null {
  const raw = localStorage.getItem(OUTBOX_KEY);
  if (raw === null) return null;
  try {
    const value = JSON.parse(raw);
    const keys = ["campaign_id", "request_id", "expected_state_version", "input", "confirmed_ending"];
    if (!value || typeof value !== "object" || Array.isArray(value)
      || Object.keys(value).some(key => !keys.includes(key))
      || typeof value.campaign_id !== "string" || !value.campaign_id
      || typeof value.request_id !== "string" || !value.request_id
      || !Number.isSafeInteger(value.expected_state_version) || value.expected_state_version < 0
      || typeof value.input !== "string" || !value.input.trim()
      || ("confirmed_ending" in value && !["law", "mercy", "exile"].includes(value.confirmed_ending))) throw new Error();
    return { raw, envelope: value };
  } catch {
    throw new Error("미해결 행동의 복구 기록이 손상되었습니다. 기록을 보존한 채 브라우저 저장소를 점검해 주세요.");
  }
}

export function storePending(envelope: Envelope): PendingTurn {
  if (readPending()) throw new Error("먼저 미해결 행동을 재시도해 주세요.");
  const raw = JSON.stringify(envelope);
  localStorage.setItem(OUTBOX_KEY, raw);
  if (localStorage.getItem(OUTBOX_KEY) !== raw) throw new Error("행동 복구 기록을 저장하지 못했습니다.");
  return { raw, envelope };
}

export function clearPending(turn: PendingTurn) {
  if (localStorage.getItem(OUTBOX_KEY) !== turn.raw) throw new Error("복구 기록이 변경되었습니다. 새로고침해 주세요.");
  localStorage.removeItem(OUTBOX_KEY);
  if (localStorage.getItem(OUTBOX_KEY) !== null) throw new Error("복구 기록을 정리하지 못했습니다.");
}

export function boundedFetch(url: string, options?: RequestInit) {
  return fetch(url, { ...options, signal: AbortSignal.timeout(20_000), cache: "no-store" });
}
