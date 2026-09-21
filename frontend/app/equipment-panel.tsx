export type EffectiveStats = { ac: number; attack_bonus: number; damage_bonus: number; damage_die: number; stealth_bonus: number; persuasion_bonus: number };
type Item = { id: string; name: string; slot: "weapon" | "armor" | "ranged"; price: number; attack_delta: number; damage_delta: number; damage_die: number; ac_delta: number; stealth_delta: number };
type Equipment = { owned: string[]; equipped: { weapon: string; armor: string; ranged?: string }; catalog: Item[] };
export type RangedStats = { equipped: boolean; attack_bonus: number; damage_die: number; damage_bonus: number; minimum_range: number; maximum_range: number; ammunition: number };

export const signed = (value: number) => value >= 0 ? `+${value}` : `${value}`;

export default function EquipmentPanel({ equipment, stats, ranged }: { equipment?: Equipment; stats?: EffectiveStats; ranged?: RangedStats }) {
  if (!equipment || !stats) return null;
  const names = Object.fromEntries(equipment.catalog.map(item => [item.id, item.name]));
  return <section aria-label="장비와 실효 능력치">
    <h3>장비</h3>
    <p aria-label="장착 장비">무기: {names[equipment.equipped.weapon] ?? "확인 필요"} · 갑옷: {names[equipment.equipped.armor] ?? "확인 필요"}</p>
    {ranged && <div aria-label="원거리 장비">
      <p>단궁: {ranged.equipped ? "장착 중" : "미장착"} · 화살 {ranged.ammunition}/30개 · 명중 {signed(ranged.attack_bonus)} · 피해 1d{ranged.damage_die}{signed(ranged.damage_bonus)}</p>
      <p>사거리 {ranged.minimum_range}~{ranged.maximum_range}칸(가로·세로 거리 합). 사격은 주요 행동과 화살 1개를 쓰며 빗나가도 소비합니다. 인접한 적이 있거나 벽에 가리면 쏠 수 없습니다.</p>
      <p>시장에서 단궁과 화살을 각각 구매하세요. 활은 근접 무기와 별도로 장착하고, 화살은 휴식으로 보충되지 않습니다.</p>
    </div>}
    <p aria-label="실효 능력치">AC {stats.ac} · 명중 {signed(stats.attack_bonus)} · 피해 1d{stats.damage_die}{signed(stats.damage_bonus)} · 은신 {signed(stats.stealth_bonus)} · 설득 {signed(stats.persuasion_bonus)}</p>
    <p>성장한 기본 능력에 현재 장비만 한 번 합산한 서버 판정 값입니다. 장비 구매와 교체는 각각 1분이며 전투 중에는 불가능합니다. 구매해도 자동 장착하지 않습니다.</p>
    <details><summary>보유 장비와 시장 목록</summary>
      <ul>{equipment.catalog.map(item => <li key={item.id}>
        <p>{item.name} · {equipment.equipped[item.slot] === item.id ? "장착 중" : equipment.owned.includes(item.id) ? "보유" : `시장 ${item.price}골드`}</p>
        <p>{item.slot === "ranged" ? "원거리 전용 · 피해 1d6+기본 피해 · 근접 무기 보정 제외" : item.slot === "weapon" ? `피해 주사위 1d${item.damage_die} · 기본 명중 ${signed(item.attack_delta)} · 기본 피해 ${signed(item.damage_delta)}` : `기본 AC ${signed(item.ac_delta)} · 기본 은신 ${signed(item.stealth_delta)}`}</p>
      </li>)}</ul>
      <p>구매·장착은 아래 가능한 행동에서 선택하세요. 퀘스트 소지품과 장비는 별도로 보관하며, 같은 장비를 중복 구매하지 않습니다.</p>
    </details>
  </section>;
}
