"use client";

import { useEffect, useRef, useState } from "react";
import type PhaserType from "phaser";

type SceneState = {
  location_id?: string;
  location_name?: string;
  hidden?: boolean;
  player?: { hp?: number };
  npcs?: { id: string; name: string }[];
  combat?: { active?: boolean; enemy_hp?: number };
};

const exits: Record<string, { label: string; action: string }[]> = {
  greyhaven_inn: [{ label: "시장 →", action: "시장으로 이동" }],
  market: [{ label: "← 여관", action: "여관으로 이동" }, { label: "창고 →", action: "창고로 이동" }],
  warehouse: [{ label: "시장 →", action: "시장으로 이동" }],
};
const talk: Record<string, string> = {
  npc_harlan: "하를란과 대화", npc_mira: "미라와 대화", npc_oren: "오렌과 대화",
};

export default function PixelScene({ state, actions, busy, onAction }: {
  state: SceneState; actions: string[]; busy: boolean; onAction: (action: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const snapshot = useRef(state);
  const instance = useRef<PhaserType.Game | null>(null);
  const controls = useRef({ actions, busy, onAction });
  const [error, setError] = useState(false);
  const [renderedState, setRenderedState] = useState<SceneState | null>(null);
  useEffect(() => { controls.current = { actions, busy, onAction }; }, [actions, busy, onAction]);
  useEffect(() => {
    snapshot.current = state;
    const scene = instance.current?.scene.getScene("LocationScene");
    if (scene?.sys.isActive()) {
      scene.scene.restart();
    }
  }, [state]);

  useEffect(() => {
    if (!host.current) return;
    const parent = host.current;
    let disposed = false;
    let game: PhaserType.Game | undefined;
    void import("phaser").then(({ default: Phaser }) => {
      if (disposed) return;
      class LocationScene extends Phaser.Scene {
        constructor() { super("LocationScene"); }
        create() {
          const state = snapshot.current;
          this.game.canvas.setAttribute("aria-label", `${state.location_name ?? "현재 장소"} 탐험 지도`);
          const graphics = this.add.graphics();
          const inn = state.location_id === "greyhaven_inn";
          const market = state.location_id === "market";
          for (let y = 0; y < 10; y++) for (let x = 0; x < 20; x++) {
            const wall = y === 0 || y === 9 || x === 0 || x === 19;
            graphics.fillStyle(wall ? 0x182331 : (x + y) % 2 ? (inn ? 0x47372e : 0x35434c) : (inn ? 0x42332b : 0x303c44));
            graphics.fillRect(x * 32, y * 32, 31, 31);
          }
          const label = (x: number, y: number, text: string, color = "#eadfbe") =>
            this.add.text(x, y, text, { fontFamily: "sans-serif", fontSize: "22px", color,
              backgroundColor: "#182331", padding: { x: 5, y: 3 } }).setOrigin(0.5);
          const actionZone = (x: number, y: number, action: string) => {
            this.add.zone(x, y, 80, 64).setInteractive({ useHandCursor: true }).on("pointerdown", () => {
              const current = controls.current;
              if (parent.dataset.ready === "true" && !current.busy && current.actions.includes(action)) current.onAction(action);
            });
          };
          label(320, 18, state.location_name ?? "Greyhaven");
          if (inn) {
            graphics.fillStyle(0x8d6040).fillRect(128, 64, 352, 22);
            graphics.fillStyle(0xb78b53).fillRect(128, 61, 352, 5);
            graphics.fillStyle(0xde9b47).fillRect(540, 64, 30, 32);
            graphics.fillStyle(0xffcf75).fillRect(548, 72, 14, 20);
          } else {
            for (let index = 0; index < 4; index++) {
              const x = 128 + index * 100;
              graphics.fillStyle(market ? 0x567766 : 0x805f42).fillRect(x, 58, 58, 42);
              graphics.lineStyle(2, 0xb69a67).strokeRect(x + 4, 62, 50, 34);
              if (!market) graphics.lineBetween(x + 4, 62, x + 54, 96);
            }
          }
          const person = (x: number, y: number, color: number, alpha = 1) => {
            const figure = this.add.graphics().setAlpha(alpha);
            figure.fillStyle(0x182027).fillEllipse(x, y + 23, 32, 12);
            figure.fillStyle(color).fillRect(x - 10, y - 4, 20, 22);
            figure.fillStyle(0xd4aa84).fillRect(x - 7, y - 18, 14, 14);
            figure.fillStyle(0x222c39).fillRect(x - 10, y + 17, 8, 9).fillRect(x + 2, y + 17, 8, 9);
          };
          person(100, 202, state.player?.hp === 0 ? 0x6d5555 : 0x85b3cb, state.hidden ? 0.45 : 1);
          label(100, 246, state.player?.hp === 0 ? "전투 불능" : state.hidden ? "Kael · 은신" : "Kael");
          for (const [index, npc] of (state.npcs ?? []).entries()) {
            const x = 260 + index * 160;
            person(x, 146, index % 2 ? 0xa687a5 : 0xc19c57);
            label(x, 193, npc.name);
            if (talk[npc.id]) actionZone(x, 155, talk[npc.id]);
          }
          if (state.combat?.active) {
            person(480, 238, 0x779344);
            label(480, 280, `Goblin · ${state.combat.enemy_hp ?? 0} HP`, "#f4a49c");
            actionZone(480, 238, "고블린을 공격한다");
          }
          const paths = exits[state.location_id ?? ""] ?? [];
          for (const [index, path] of paths.entries()) {
            const x = paths.length === 2 && index === 0 ? 48 : 568;
            graphics.fillStyle(0x9e8454).fillRect(x - 18, 228, 36, 46);
            label(x, 294, path.label, "#e8c773");
            actionZone(x, 250, path.action);
          }
          this.game.events.once(Phaser.Core.Events.POST_RENDER, () => {
            if (!disposed) setRenderedState(state);
          });
        }
      }
      game = new Phaser.Game({ type: Phaser.CANVAS, parent, width: 640, height: 320,
        backgroundColor: "#182331", pixelArt: true, banner: false,
        scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
        fps: { target: 30 }, scene: LocationScene });
      instance.current = game;
      game.canvas.setAttribute("role", "img");
    }).catch(() => { if (!disposed) setError(true); });
    return () => { disposed = true; game?.destroy(true); instance.current = null; };
  }, []);

  return <div className="pixel-map">
    <div className="pixel-host" ref={host} data-testid="pixel-scene" data-ready={renderedState === state ? "true" : "false"} />
    <p className="note">인물과 출구를 눌러 행동하세요. 같은 행동을 아래 버튼과 키보드로도 선택할 수 있습니다.</p>
    {error && <p role="status">지도를 불러오지 못했습니다. 아래 행동 버튼으로 계속 진행할 수 있습니다.</p>}
  </div>;
}
