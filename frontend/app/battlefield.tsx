"use client";

type Combat = { width?: number; height?: number; player_x: number; player_y: number; enemy_x: number; enemy_y: number; enemy_hp: number; exit_x: number; exit_y: number; round: number; walls?: number[][]; initiative?: { first?: string; player_roll?: number; enemy_roll?: number } };

export default function Battlefield({ combat, actions, busy, onAction }: { combat: Combat; actions: string[]; busy: boolean; onAction: (action: string) => void }) {
  const directions: Record<string, string> = { "0,-1": "전투 이동: 위", "0,1": "전투 이동: 아래", "-1,0": "전투 이동: 왼쪽", "1,0": "전투 이동: 오른쪽" };
  const width = combat.width ?? 6, height = combat.height ?? 5;
  return <section aria-label="전술 전투" data-testid="battlefield">
    <h3>여관 전투 · {combat.round}라운드</h3>
    <p>선제권: {combat.initiative?.first === "enemy" ? "고블린" : "Kael"} · 고블린 HP {combat.enemy_hp}</p>
    <p>한 칸 이동 또는 행동 후 적이 대응합니다. 인접해야 공격할 수 있고, 출구에서 후퇴할 수 있습니다. 방어는 다음 대응의 AC +2입니다.</p>
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))`, gap: 4 }}>
      {Array.from({ length: width * height }, (_, index) => {
        const x = index % width, y = Math.floor(index / width);
        const wall = combat.walls?.some(point => point[0] === x && point[1] === y);
        const player = combat.player_x === x && combat.player_y === y;
        const enemy = combat.enemy_x === x && combat.enemy_y === y;
        const exit = combat.exit_x === x && combat.exit_y === y;
        const action = directions[`${x - combat.player_x},${y - combat.player_y}`];
        const canMove = !wall && !enemy && action && actions.includes(action);
        const content = player ? "Kael" : enemy ? "고블린" : wall ? "벽" : exit ? "출구" : "·";
        return <button key={index} type="button" style={{ margin: 0, padding: "12px 0", fontSize: 12, minWidth: 0 }} aria-label={canMove ? `이동: (${x}, ${y})` : `${content} (${x}, ${y})`} disabled={busy || !canMove} onClick={() => canMove && onAction(action)}>{content}</button>;
      })}
    </div>
  </section>;
}
