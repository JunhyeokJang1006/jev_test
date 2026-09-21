"use client";

type Enemy = { id: string; name: string; hp: number; x: number; y: number };
type Combat = { enemies?: Enemy[]; width?: number; height?: number; player_x: number; player_y: number; enemy_x: number; enemy_y: number; enemy_hp: number; exit_x: number; exit_y: number; round: number; walls?: number[][]; initiative?: { first?: string; player_roll?: number; enemy_roll?: number } };

export default function Battlefield({ combat, actions, busy, onAction }: { combat: Combat; actions: string[]; busy: boolean; onAction: (action: string) => void }) {
  const directions: Record<string, string> = { "0,-1": "전투 이동: 위", "0,1": "전투 이동: 아래", "-1,0": "전투 이동: 왼쪽", "1,0": "전투 이동: 오른쪽" };
  const width = combat.width ?? 6, height = combat.height ?? 5;
  const enemies = combat.enemies ?? [{ id: "goblin_001", name: "Goblin", hp: combat.enemy_hp, x: combat.enemy_x, y: combat.enemy_y }];
  const attackLabels: Record<string, string> = { goblin_001: "고블린을 공격한다", goblin_002: "두 번째 고블린을 공격한다" };
  return <section aria-label="전술 전투" data-testid="battlefield">
    <h3>여관 전투 · {combat.round}라운드</h3>
    <p>진영 선제권: {combat.initiative?.first === "enemy" ? "적 진영" : "Kael"}</p>
    <ul aria-label="적 상태">{enemies.map(enemy => <li key={enemy.id}>{enemy.name}: HP {enemy.hp}{enemy.hp <= 0 ? " · 쓰러짐" : ""}</li>)}</ul>
    <p>한 칸 이동 또는 행동 후 살아 있는 적들이 차례로 대응합니다. 인접한 적을 클릭해 공격하고, 출구에서 후퇴할 수 있습니다. 방어는 이번 적 대응 전체에 AC +2입니다.</p>
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))`, gap: 4 }}>
      {Array.from({ length: width * height }, (_, index) => {
        const x = index % width, y = Math.floor(index / width);
        const wall = combat.walls?.some(point => point[0] === x && point[1] === y);
        const player = combat.player_x === x && combat.player_y === y;
        const enemy = enemies.find(enemy => enemy.x === x && enemy.y === y && enemy.hp > 0);
        const exit = combat.exit_x === x && combat.exit_y === y;
        const action = directions[`${x - combat.player_x},${y - combat.player_y}`];
        const canMove = !wall && !enemy && action && actions.includes(action);
        const attack = enemy ? attackLabels[enemy.id] : undefined;
        const canAttack = attack && actions.includes(attack);
        const content = player ? "Kael" : enemy ? (enemy.id === "goblin_002" ? "정찰병" : "고블린") : wall ? "벽" : exit ? "출구" : "·";
        return <button key={index} type="button" style={{ margin: 0, padding: "12px 0", fontSize: 12, minWidth: 0 }} aria-label={canAttack ? `공격: ${enemy?.name}` : canMove ? `이동: (${x}, ${y})` : `${content} (${x}, ${y})`} disabled={busy || (!canMove && !canAttack)} onClick={() => { if (canAttack) onAction(attack); else if (canMove) onAction(action); }}>{content}</button>;
      })}
    </div>
  </section>;
}
