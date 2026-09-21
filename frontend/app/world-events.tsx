type WorldEvent = { id: string; title: string; status: string; due_at: number; choice?: string; support?: string | null; outcome?: string | null; resolution?: string | null };
type Faction = { name: string; goal: string; stock: number; trust: number; plan: string };

export default function WorldEvents({ events, factions, elapsed, marketPolicy }: { events: WorldEvent[]; factions: Record<string, Faction>; elapsed: number; marketPolicy?: string }) {
  if (!events.length) return null;
  const supportNames: Record<string, string> = { guards: "경비대 호위", merchants: "수송 자금", volunteers: "자원봉사" };
  const prices: Record<string, string> = { relief: "지원 물자 도착 · 물약 6골드 / 보급품 2골드", shortage: "물자 부족 · 물약 10골드 / 보급품 4골드", caravan: "수송 재개 · 물약 8골드 / 보급품 2골드" };
  return <section aria-label="지속 세계 사건">
    <h3>도시의 다음 움직임</h3>
    <p>게임 시간이 흐르면 파벌의 수송·복구 계획이 진행됩니다. 이동·수련·휴식도 포함되며, 브라우저를 닫아 둔 현실 시간은 포함되지 않습니다.</p>
    {marketPolicy && prices[marketPolicy] && <p aria-label="현재 시장 상황">{prices[marketPolicy]}</p>}
    {events.map(event => <article key={event.id} aria-label={event.title}>
      <h4>{event.title} · {event.status === "pending" ? "진행 예정" : "결과 확정"}</h4>
      {event.status === "pending" && <p>예정 시각까지 {Math.max(0, event.due_at - elapsed)}분</p>}
      {event.id === "supply_convoy" && event.status === "pending" && <>
        <p>{event.support ? `준비한 지원: ${supportNames[event.support] ?? event.support}` : "아직 지원하지 않았습니다. 시장에서 수송을 돕거나 다른 일을 계속할 수 있습니다."}</p>
        <p>문서를 확보했다면 경비대 호위를 요청할 수 있습니다. 전령과 문서를 모두 구했다면 별도 지원 없이도 파벌이 협력합니다. 지원 행동은 예정 시각까지 마쳐야 합니다.</p>
      </>}
      {event.resolution && <p>{event.resolution}</p>}
    </article>)}
    <ul aria-label="파벌 상태">{Object.entries(factions).map(([id, faction]) => <li key={id}>
      <strong>{faction.name}</strong> · 보유 물자 {faction.stock} · 신뢰 {Math.round(faction.trust * 100)}%
      <p>{faction.goal} · {faction.plan}</p>
    </li>)}</ul>
  </section>;
}
