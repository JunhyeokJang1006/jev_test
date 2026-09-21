"use client";

import { signed, type EffectiveStats, type RangedStats } from "./equipment-panel";

type Enemy = { id: string; name: string; hp: number; x: number; y: number; conditions?: string[] };
type Combat = { encounter_id?: string; title?: string; enemies?: Enemy[]; width?: number; height?: number; player_x: number; player_y: number; enemy_x: number; enemy_y: number; enemy_hp: number; exit_x: number; exit_y: number; round: number; movement_remaining?: number; action_available?: boolean; bonus_action_available?: boolean; defending?: boolean; walls?: number[][]; initiative?: { first?: string; player_roll?: number; enemy_roll?: number } };

export default function Battlefield({ combat, stats, ranged, actions, busy, onAction }: { combat: Combat; stats?: EffectiveStats; ranged?: RangedStats; actions: string[]; busy: boolean; onAction: (action: string) => void }) {
  const directions: Record<string, string> = { "0,-1": "전투 이동: 위", "0,1": "전투 이동: 아래", "-1,0": "전투 이동: 왼쪽", "1,0": "전투 이동: 오른쪽" };
  const width = combat.width ?? 6, height = combat.height ?? 5;
  const enemies: Enemy[] = combat.enemies ?? [{ id: "goblin_001", name: "Goblin", hp: combat.enemy_hp, x: combat.enemy_x, y: combat.enemy_y }];
  const conditionNames: Record<string, string> = { prone: "넘어짐 · 다음 적 차례에 일어나기만 함", exposed: "빈틈 · 다음 공격 2d20 중 높은 값" };
  const attackLabels: Record<string, string> = { goblin_001: "고블린을 공격한다", goblin_002: "두 번째 고블린을 공격한다", bandit_001: "매복자를 공격한다", bandit_002: "두 번째 매복자를 공격한다" };
  const rangedLabels: Record<string, string> = { goblin_001: "고블린에게 사격", goblin_002: "두 번째 고블린에게 사격", bandit_001: "매복자에게 사격", bandit_002: "두 번째 매복자에게 사격" };
  const enemyLabels: Record<string, string> = { goblin_001: "고블린", goblin_002: "정찰병", bandit_001: "매복자", bandit_002: "매복자 2" };
  return <section aria-label="전술 전투" data-testid="battlefield">
    <h3>{combat.title ?? "여관 전투"} · {combat.round}라운드</h3>
    {stats && <p aria-label="전투 실효 능력치">AC {stats.ac + (combat.defending ? 2 : 0)}{combat.defending ? " (방어 +2 포함)" : ""} · 명중 {signed(stats.attack_bonus)} · 피해 1d{stats.damage_die}{signed(stats.damage_bonus)}</p>}
    {ranged?.equipped && <p aria-label="전투 원거리 능력치">단궁 · 화살 {ranged.ammunition}개 · 명중 {signed(ranged.attack_bonus)} · 피해 1d{ranged.damage_die}{signed(ranged.damage_bonus)} · 사거리 {ranged.minimum_range}~{ranged.maximum_range}칸</p>}
    <p>진영 선제권: {combat.initiative?.first === "enemy" ? "적 진영" : "Kael"}</p>
    <ul aria-label="적 상태">{enemies.map(enemy => <li key={enemy.id}>{enemy.name}: HP {enemy.hp}{enemy.hp <= 0 ? " · 쓰러짐" : ""}{(enemy.conditions ?? []).filter(condition => conditionNames[condition]).map(condition => <span key={condition}> · {conditionNames[condition]}</span>)}</li>)}</ul>
    <p aria-label="남은 전투 행동">이동 {combat.movement_remaining ?? 3}칸 (기본 3) · 주요 행동 {combat.action_available === false ? "사용 완료" : "1회"} · 보조 행동 {combat.bonus_action_available === false ? "사용 완료" : "1회"}{combat.defending ? " · 방어 중 AC +2" : ""}</p>
    <p>주요 행동으로 근접 공격·사격·방어·밀치기·질주 중 하나, 보조 행동으로 물약·교란·전투 회복력 중 하나를 선택합니다. 공격 가능한 적을 누르세요. 턴을 종료하면 살아 있는 적들이 차례로 대응합니다. 방어는 이 적 대응 전체에 AC +2이며, 출구에서 후퇴할 수 있습니다.</p>
    {ranged?.equipped && <p>사격은 화살 1개와 주요 행동을 사용합니다. 벽의 모서리에 걸린 사선도 차단됩니다. 적이 인접하면 먼저 이동하거나 근접 공격을 선택하세요. 아래 버튼은 서버가 허용한 공격만 활성화됩니다.</p>}
    <details><summary>전술 행동과 상태 효과</summary><p>밀치기와 교란은 인접한 살아 있는 적에게 d20+3, DC14로 판정합니다. 실패해도 행동은 소비합니다. 밀치기에 성공하면 적이 다음 차례에 일어나기만 합니다. 교란 성공 후 그 적을 공격하면 d20 두 개 중 높은 값을 쓰고 빈틈이 사라집니다. 공격하지 않은 빈틈은 적 차례 시작에 사라집니다. 질주는 주요 행동을 써서 이동 3칸을 추가합니다. 자체 시나리오 규칙입니다.</p></details>
    <button type="button" disabled={busy || !actions.includes("턴 종료")} onClick={() => onAction("턴 종료")}>적 차례로 넘기기</button>
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))`, gap: 4 }}>
      {Array.from({ length: width * height }, (_, index) => {
        const x = index % width, y = Math.floor(index / width);
        const wall = combat.walls?.some(point => point[0] === x && point[1] === y);
        const player = combat.player_x === x && combat.player_y === y;
        const enemy = enemies.find(enemy => enemy.x === x && enemy.y === y && enemy.hp > 0);
        const exit = combat.exit_x === x && combat.exit_y === y;
        const action = directions[`${x - combat.player_x},${y - combat.player_y}`];
        const canMove = !wall && !enemy && action && actions.includes(action);
        const melee = enemy ? attackLabels[enemy.id] : undefined;
        const shot = enemy ? rangedLabels[enemy.id] : undefined;
        const shooting = !!shot && actions.includes(shot) && (!melee || !actions.includes(melee));
        const attack = shooting ? shot : melee;
        const canAttack = attack && actions.includes(attack);
        const content = player ? "Kael" : enemy ? (enemyLabels[enemy.id] ?? enemy.name) : wall ? "벽" : exit ? "출구" : "·";
        return <button key={index} type="button" style={{ margin: 0, padding: "12px 0", fontSize: 12, minWidth: 0 }} aria-label={canAttack ? `${shooting ? "사격" : "공격"}: ${enemy?.name}` : canMove ? `이동: (${x}, ${y})` : `${content} (${x}, ${y})`} disabled={busy || (!canMove && !canAttack)} onClick={() => { if (canAttack) onAction(attack); else if (canMove) onAction(action); }}>{content}</button>;
      })}
    </div>
  </section>;
}
