# GPT-5.6 Luna × JEV 기반 D&D 스타일 1인용 AI TRPG 웹앱
## Luna 중심 아키텍처 전면 개정 상세 기획 및 구현 계획서

- 문서 목적: 실제 개발 착수가 가능한 수준으로 제품 목표, 아키텍처, GPT-5.6 Luna/JEV 역할 분담, D&D/SRD 규칙 처리, 도트 그래픽, 데이터 구조, 테스트, 평가, 단계별 개발 계획을 정의한다.
- 기본 전제: 1인 플레이 중심, 개인 사용 우선, 웹앱 형태, React/TypeScript 사용 가능, Python은 핵심 백엔드·규칙 엔진·AI 오케스트레이션에 적극 활용한다.
- 핵심 원칙: **게임의 사실과 규칙은 Python/DB가 관리하고, GPT-5.6 Luna는 기본 GM·행동 해석·NPC 반응·서사 생성·메모리 압축을 담당하며, JEV는 빠른 판단·분류·라우팅을 담당한다.**
- 모델 전략: **Luna가 기본값이다.** 대부분의 턴은 Luna 단독 또는 `JEV → Luna` 경로로 처리한다. 고비용·고추론 모델은 필수가 아니라, 장기 캠페인 재구성이나 특별한 복합 추론에서만 선택적으로 escalation한다.
- 개발 전략: 공개 프레임워크, UI 컴포넌트, SRD 데이터, 타일맵 도구, CC0/CC-BY 도트 에셋을 최대한 재사용한다. 직접 개발의 핵심은 `자연어 → 판단 → 규칙 → 상태 → 서사` 파이프라인과 지속 가능한 세계 상태다.
- 제품 철학: **모델 성능으로 상태관리의 빈틈을 덮지 않는다.** Luna가 충분히 잘 동작하도록 컨텍스트를 작고 정확하게 만들고, deterministic engine이 일관성을 보장한다.

---

# 0. 이번 개정의 핵심 변화

기존 설계는 고성능 추론 모델을 GM의 중심에 두는 접근에 가까웠다. 이번 개정에서는 이를 다음처럼 바꾼다.

```text
기존 개념
JEV → 고성능 GM 모델 → Rules Engine

개정 개념
JEV → GPT-5.6 Luna → Rules Engine → State Commit → GPT-5.6 Luna
```

핵심 변화는 다섯 가지다.

1. **Luna가 기본 모델**
   - 일반 대화, 탐색, NPC 반응, 행동 해석, 장면 묘사, 로그 요약을 Luna가 담당한다.
   - 모든 턴이 상위 추론 모델을 요구한다는 전제를 버린다.

2. **JEV는 Luna를 대체하지 않는다**
   - JEV는 빠른 구조화 판단과 라우팅에 집중한다.
   - 자연스러운 대사·서사·복합 문맥 이해는 Luna가 맡는다.

3. **Python Rules Engine의 권한을 강화**
   - Luna의 판단은 `proposal`이다.
   - HP, AC, 주사위, 위치, 주문 슬롯, 상태이상, 퀘스트 플래그 등은 engine만 확정한다.

4. **Escalation은 선택 기능**
   - 복합 정치관계, 수십 턴에 걸친 플롯 재계획, 대규모 세계 상태 충돌 등 특별한 상황에서만 상위 reasoning route를 호출할 수 있다.
   - 해당 경로가 비활성화되어도 캠페인은 Luna만으로 계속 진행되어야 한다.

5. **작은 컨텍스트 + 구조화 메모리**
   - Luna에게 전체 로그를 던지지 않는다.
   - 현재 장면·관련 NPC·관련 퀘스트·최근 이벤트·필요한 사실만 조립한다.
   - 성능보다 컨텍스트 품질을 우선한다.

---

# 0.1 Luna 중심 설계의 목표

이 프로젝트는 다음 가설을 따른다.

> 대부분의 TRPG 턴은 “최고 난도의 추론”이 아니라 “정확한 상태조회 + 자연어 해석 + 합리적인 국소 판단 + 좋은 서사화” 문제다.

따라서 게임 품질을 결정하는 우선순위는 다음으로 둔다.

```text
1. 상태 정확성
2. 권한 분리
3. 관련 컨텍스트 검색
4. 규칙 엔진
5. Luna 출력 계약
6. JEV 라우팅
7. 모델 자체의 고난도 추론 성능
```

즉 “더 강한 모델로 교체하면 해결되는 게임”이 아니라, **Luna로도 안정적으로 운영되는 시스템**을 목표로 한다.

---

# 1. 프로젝트 한 줄 정의

> 플레이어가 자연어로 자유롭게 행동하면, AI가 이를 D&D 스타일의 규칙과 세계 상태에 맞게 해석하고, 필요 시 주사위 판정과 전투를 수행하며, 세계가 장기적으로 기억·변화하는 1인용 AI TRPG 웹앱.

단순한 “AI Dungeon Master 챗봇”이 아니라 다음 세 가지를 동시에 갖는 것을 목표로 한다.

1. **게임으로서의 결정성**
   - HP, AC, 주문 슬롯, 이동, 상태이상, 주사위 등은 코드가 관리한다.
   - 이미 확정된 세계 사실은 AI가 임의로 바꾸지 못한다.

2. **TRPG로서의 자유도**
   - 버튼에 있는 행동만 선택하는 것이 아니라 자연어로 무엇이든 시도할 수 있다.
   - 정형화되지 않은 행동은 Luna/JEV가 게임 규칙에 매핑한다.

3. **장기 캠페인으로서의 지속성**
   - NPC, 퀘스트, 관계, 아이템, 파벌, 시간, 장소, 비밀, 과거 사건을 저장한다.
   - 세션을 종료했다가 다시 시작해도 세계가 유지된다.

---

# 2. 이 프로젝트에서 가장 중요한 설계 원칙

## 2.1 Luna에게 “게임 상태의 진실”을 맡기지 않는다

GPT-5.6 Luna는 자연어 해석과 생성에 강하지만, 게임 상태의 최종 원장(system of record)이 되어서는 안 된다.

따라서 아래 항목은 Luna가 직접 수정할 수 없게 한다.

- HP
- 최대 HP
- AC
- 능력치
- 숙련 보너스
- 아이템 수량
- 돈
- 주문 슬롯
- 상태이상
- 위치
- initiative
- 피해량
- 주사위 결과
- 퀘스트 플래그
- 사망 여부
- NPC 관계 수치
- 주요 세계 사실

GPT-5.6 Luna가 할 수 있는 일은 다음과 같다.

- 플레이어 행동을 해석한다.
- 규칙 엔진에 필요한 행동 후보를 제안한다.
- NPC 의도 및 반응을 추론한다.
- 판정 결과를 서사적으로 묘사한다.
- 새로운 장소/NPC/사건의 초안을 생성한다.
- 세계 상태를 변경해야 하는 후보 이벤트를 제안한다.

최종 변경은 항상 `GameEngine`의 검증된 command를 통한다.

---

## 2.2 “서사 상태”와 “기계 상태”를 분리한다

예:

```text
서사:
"오른팔에 깊은 상처를 입어 검을 들기 어려워졌다."

기계 상태:
HP = 11 / 35
Condition = injured_arm
Attack penalty = -2
```

텍스트만 저장하면 이후 모델이 이 상처의 의미를 다르게 해석할 수 있다.

따라서 중요한 사건은 반드시 structured state로 변환한다.

---

## 2.3 Event Sourcing에 가까운 구조를 사용한다

현재 상태만 저장하지 않고 “무슨 일이 있었는가”를 이벤트로 기록한다.

예:

```json
{
  "event_id": "evt_0183",
  "turn": 46,
  "type": "NPC_RELATION_CHANGED",
  "actor": "npc_harlan",
  "target": "player_001",
  "before": 0.20,
  "after": 0.45,
  "reason": "Player warned Harlan about the assassination attempt"
}
```

장점:

- AI가 왜 현재 상태가 되었는지 설명할 수 있다.
- 세이브를 복원하기 쉽다.
- 버그를 추적하기 쉽다.
- Luna/JEV 판단 평가 데이터를 자동으로 얻을 수 있다.

---

# 3. 권장 기술 스택

## 3.1 전체 구성

```text
Frontend
├─ Next.js
├─ React
├─ TypeScript
├─ Tailwind CSS
├─ shadcn/ui
├─ Zustand
├─ TanStack Query
└─ Phaser (도트 지도/전투)

Backend
├─ Python 3.12+
├─ FastAPI
├─ Pydantic
├─ SQLModel 또는 SQLAlchemy
├─ SQLite
└─ Alembic

AI
├─ GPT-5.6 Luna — 기본 GM / 해석 / NPC / 서사 / 요약
├─ JEV — 빠른 분류 / 점수화 / 라우팅 / 검증
├─ Optional Escalation Model — 복합 추론이 정말 필요한 경우만
└─ Prompt / Context Builder — 모델보다 중요한 입력 조립 계층

Game Content
├─ D&D SRD 5.2.1 범위
├─ Open5e 등 공개 데이터
├─ 직접 만든 campaign content
└─ CC0/CC-BY 그래픽 에셋

Tooling
├─ Tiled Map Editor
├─ pytest
├─ Playwright
└─ GitHub
```

---

# 4. 왜 Next.js + React + Python인가

## Frontend

React는 화면 상태와 다양한 패널을 동시에 다루기에 적합하다.

TRPG 화면에는 다음이 동시에 존재한다.

- GM narration
- NPC dialogue
- player input
- character sheet
- dice log
- quest log
- map
- inventory
- combat
- NPC relationship
- debug panel

Streamlit으로도 가능하지만 커스텀 UI와 게임적 인터랙션을 넣기 시작하면 제약이 빠르게 생긴다.

따라서 UI는 React가 적합하다.

## Backend

게임 엔진은 Python으로 유지한다.

사용자가 Python 경험이 있으므로 다음을 익숙한 영역에 남길 수 있다.

- rules engine
- dice
- 상태 변환
- 데이터 검증
- GPT-5.6 Luna API
- JEV API
- campaign simulation
- test harness

---

# 5. 도트 그래픽: 가능하며 권장한다

## 5.1 결론

도트 그래픽 자체는 어려운 문제가 아니다.

어려워지는 경우는 아래처럼 접근할 때다.

> 모든 캐릭터 애니메이션, 맵, 전투, 충돌, UI까지 직접 게임 엔진으로 만든다.

그럴 필요가 없다.

이 프로젝트에서 도트 그래픽은 **시각화 계층**으로 취급한다.

```text
React
├─ 텍스트 / UI / 캐릭터 시트
└─ Phaser Canvas
   ├─ 맵
   ├─ 플레이어 sprite
   ├─ NPC sprite
   ├─ monster sprite
   └─ 간단한 전투 animation
```

즉 게임 상태는 Python backend에 있고 Phaser는 그 상태를 보여주는 renderer이다.

---

# 6. 권장 도트 그래픽 스택

## Phaser

Phaser를 권장한다.

이유:

- browser-native 2D game framework
- tilemap 지원
- sprite animation
- camera
- collision
- input
- scene
- particles
- React 페이지 내부에 mount 가능

PixiJS도 훌륭하지만 PixiJS는 상대적으로 rendering layer에 더 가깝다.

이 프로젝트는 향후 다음이 필요할 수 있다.

- character movement
- collision
- grid combat
- interactive objects
- tilemap
- camera
- animation

따라서 Phaser가 조금 더 편하다.

---

# 7. Tiled Map Editor 사용

맵을 직접 코드로 만들지 않는다.

Tiled에서 시각적으로 작성한다.

예:

```text
Town Map

Ground Layer
├─ grass
├─ road
└─ water

Building Layer
├─ inn
├─ blacksmith
└─ town hall

Object Layer
├─ NPC spawn
├─ door
├─ chest
└─ encounter trigger

Collision Layer
├─ wall
└─ obstacle
```

그리고 JSON으로 export한다.

예:

```text
assets/maps/greyhaven.json
```

Phaser가 이 JSON을 불러온다.

---

# 8. 도트 에셋 전략

직접 픽셀아트를 만드는 것은 MVP에 필요 없다.

초기에는 다음 종류의 공개 에셋을 적극 활용한다.

## Kenney

장점:

- CC0 에셋이 많다.
- 라이선스 관리가 쉽다.
- 스타일 통일이 비교적 쉽다.

특히 다음 계열이 적합하다.

- Tiny Dungeon
- Tiny Town
- Roguelike Characters
- RPG Base
- RPG Urban

권장 MVP 규격:

```text
Tile size: 16 × 16
Render scale: 3x 또는 4x
Nearest-neighbor scaling
```

즉 실제 16×16 sprite를 화면에서는 48×48 혹은 64×64로 렌더링한다.

CSS:

```css
canvas {
  image-rendering: pixelated;
}
```

---

# 9. 도트 그래픽 MVP 수준

처음부터 Zelda 같은 이동 게임을 만들 필요가 없다.

## 단계 1

**현재 위치 그림**

```text
[Inn pixel scene]

GM:
여관 안에는 술 취한 광부 세 명과 후드를 쓴 여행자가 있다.
```

맵은 움직이지 않는다.

## 단계 2

**클릭 가능한 맵**

플레이어 sprite를 클릭한 위치로 이동한다.

## 단계 3

**타일 이동**

WASD / click-to-move

## 단계 4

**전투 grid**

```text
□ □ □ □ □
□ P □ G □
□ □ # □ □
□ □ □ G □
```

P = player  
G = goblin

## 단계 5

AI가 생성한 encounter를 map에 동적으로 배치한다.

중요한 점은 **도트 시스템이 AI 시스템 개발을 막지 않게 하는 것**이다.

---

# 10. 제품 화면 구조

## 기본 Desktop layout

```text
┌──────────────────────────────────────────────────────────────┐
│ LUNA REALMS                  Greyhaven · Day 8 · 21:36     │
├───────────────┬─────────────────────────────┬────────────────┤
│ CHARACTER     │                             │ MAP            │
│               │          STORY              │                │
│ Kael Lv 5     │                             │ [Pixel Map]    │
│ HP 31 / 37    │ 비가 지붕을 두드린다.       │                │
│ AC 17         │                             │                │
│               │ 경비대장 Harlan이 문을      │                │
│ STR +2        │ 닫으며 말한다.              │                │
│ DEX +4        │                             │                │
│ CHA +3        │ "무슨 일이오?"              │                │
├───────────────┤                             ├────────────────┤
│ QUEST         │                             │ NPC            │
│               │                             │                │
│ ● Missing     │                             │ Harlan         │
│   Scholar     │                             │ Neutral        │
│ ○ Cult        │                             │ Suspicion 42%  │
├───────────────┴─────────────────────────────┴────────────────┤
│ > 시장의 명령을 받았다고 거짓말한다...                     │
│                                                     [SEND]   │
├──────────────────────────────────────────────────────────────┤
│ 🎲 Deception 14 + 6 = 20 / DC 16 → SUCCESS                 │
└──────────────────────────────────────────────────────────────┘
```

---

# 11. 주요 화면

## 11.1 Campaign screen

핵심 플레이 화면.

구성:

- narration
- NPC dialogue
- player input
- quick actions
- dice result
- relevant map
- relevant NPC
- current objectives

## 11.2 Character sheet

- stats
- saves
- skills
- inventory
- equipment
- spells
- conditions
- buffs/debuffs
- biography

## 11.3 Journal

자동 작성된다.

```text
Day 3
- Greyhaven 도착
- Harlan 경비대장과 처음 만남

Day 5
- 실종된 학자의 연구실 발견
- Black Hand 문양 확인

Day 8
- 시장의 명령을 사칭해 경비 기록 열람
```

## 11.4 NPC Codex

```text
Harlan Voss

Known facts
- Greyhaven 경비대장
- 시장에게 충성함
- 밀수 조직을 싫어함

Player relationship
Trust: 42
Fear: 3
Suspicion: 18

Player knows:
"아내가 4년 전 사망함"

Unknown to player:
[hidden]
```

## 11.5 World / faction

파벌 간 관계를 시각화할 수 있다.

```text
Royal Guard
   ↓ hostile
Black Hand
   ↑ trade
Smugglers
```

## 11.6 Debug screen

개발 중 가장 중요하다.

```text
Player input
↓
Intent Parser
↓
JEV evaluations
↓
GPT-5.6 Luna reasoning request
↓
Rules decision
↓
Dice
↓
State diff
↓
Narrative
```

---

# 11.5 Luna 중심 실행 아키텍처

## 11.5.1 기본 턴 경로

대부분의 플레이어 입력은 다음 경로로 처리한다.

```text
PLAYER INPUT
   │
   ▼
Context Builder
   │
   ├─ current scene
   ├─ relevant entities
   ├─ recent events
   ├─ active constraints
   └─ player mechanical state
   │
   ▼
JEV Pre-Router
   │
   ├─ action type
   ├─ check required?
   ├─ likely skill
   ├─ risk
   └─ Luna call type
   │
   ▼
GPT-5.6 Luna Interpreter
   │
   └─ structured action proposal
   │
   ▼
Python Rules Engine
   │
   ├─ validate
   ├─ roll
   ├─ calculate
   └─ produce authoritative outcome
   │
   ▼
State Commit
   │
   └─ event log + DB update
   │
   ▼
GPT-5.6 Luna Narrator
   │
   └─ authoritative outcome을 바꾸지 않고 서사화
   │
   ▼
UI
```

Luna는 기본적으로 두 역할로 분리한다.

### Interpreter

플레이어가 **무엇을 하려는지** 구조화한다.

### Narrator

확정된 결과가 **어떻게 보이고 들리고 느껴지는지** 표현한다.

같은 Luna 모델을 사용하더라도 역할별 system prompt와 output schema를 분리한다.

---

## 11.5.2 단순 턴 Fast Path

모든 입력에서 Luna를 두 번 호출할 필요는 없다.

예:

> 여관 주인에게 맥주 한 잔 주문한다.

JEV가 다음처럼 판단할 수 있다.

```text
mechanical_check = false
complex_reasoning = false
state_mutation = trivial
```

이 경우:

```text
JEV
↓
Luna one-shot response
↓
simple state event
```

로 끝낸다.

목표는 “AI 호출 횟수를 줄이는 것” 자체보다, **불필요한 reasoning pipeline을 만들지 않는 것**이다.

---

## 11.5.3 Deterministic Fast Path

일부 행동은 Luna 호출도 생략할 수 있다.

예:

```text
"포션을 마신다."
"인벤토리를 연다."
"북쪽 문으로 이동한다."
"검을 장착한다."
```

UI가 이미 구조화된 command를 제공한다면:

```text
React action
↓
Python command
↓
Engine
↓
state update
↓
필요한 경우에만 Luna narration
```

으로 처리한다.

따라서 자연어가 아닌 버튼 액션까지 전부 LLM에 보내지 않는다.

---

## 11.5.4 Complex Turn Path

예:

> 어제 경비대장에게 흘린 가짜 정보 때문에 왕실군이 서쪽 창고로 몰렸을 테니, 그 틈을 이용해 도둑 길드에게 내가 정보를 조작했다는 사실은 숨긴 채 동쪽 항구를 치자고 제안한다.

이 경우:

```text
JEV
↓
complex_reasoning = high
multi_entity = true
long_memory_required = true
↓
Context Retrieval 확장
↓
Luna deep-context interpretation
↓
필요한 경우 optional escalation
↓
Rules / World Engine
```

그러나 escalation의 결과 역시 `proposal`에 불과하다. 세계 상태를 직접 쓸 권한은 없다.

---

## 11.5.5 Escalation Policy

상위 reasoning route는 다음 조건 중 복수 충족 시에만 고려한다.

```text
- 3개 이상의 주요 파벌이 얽힘
- 서로 충돌하는 장기 기억을 재조정해야 함
- 캠페인 전체 목표를 재계획해야 함
- 플레이어가 여러 단계 전략을 한 번에 제안
- Luna 결과의 구조적 confidence가 낮음
- validation loop가 2회 이상 실패
```

권장 pseudo-policy:

```python
if deterministic_action:
    run_engine()
elif jev.simple and not jev.requires_check:
    run_luna_fast()
elif jev.complexity < COMPLEX_THRESHOLD:
    run_luna_standard()
else:
    result = run_luna_extended_context()

    if result.validation_failed_twice:
        result = optional_escalation(result)
```

중요:

> “복잡해 보인다”는 이유 하나만으로 고급 모델을 호출하지 않는다.

---

## 11.5.6 Luna Failure Handling

Luna output이 schema를 통과하지 못하면 narrative로 얼버무리지 않는다.

```text
Luna output
↓
Pydantic validation
↓
FAIL
↓
repair prompt
↓
FAIL
↓
safe fallback
```

safe fallback 예:

```text
행동의 의도는 이해했지만 현재 규칙 상태에서 자동으로 확정할 수 없다.
가장 보수적인 해석으로 한 개의 판정만 수행한다.
```

내부적으로는 사용자에게 시스템 오류를 노출하기보다 규칙적으로 안전한 경로를 선택한다.

---

# 12. AI 역할 설계

## 12.1 GPT-5.6 Luna: Default GM Execution Layer

Luna는 “비싼 예외 처리 모델”이 아니라 게임의 기본 실행 모델이다.

하나의 Luna를 논리적으로 다음 역할로 나눈다.

```text
Luna Interpreter
Luna NPC Actor
Luna Narrator
Luna Memory Summarizer
Luna World Planner
```

각 역할은 동일 모델을 쓸 수 있지만 prompt와 schema를 분리한다.

GPT-5.6 Luna가 맡는다.

- 복합 행동 해석
- 장면 이해
- 플롯 추론
- NPC의 장기 목표
- 모호한 행동의 의미
- hidden truth와 현재 정보의 관계 추론
- encounter narrative
- creative world generation
- outcome narration

GPT-5.6 Luna가 맡지 않는다.

- dice generation
- HP 계산
- damage arithmetic
- inventory mutation
- spell slot
- AC
- movement rules
- permanent state mutation

---

# 12.2 Luna 역할별 계약

## Luna Interpreter

입력:

- current scene
- relevant entities
- player state
- recent events
- player utterance

출력은 자유문이 아니라 structured output이다.

```json
{
  "intent": "deceive_guard",
  "action_type": "social",
  "targets": ["npc_harlan"],
  "steps": [
    "claim_mayor_authorization"
  ],
  "proposed_check": {
    "skill": "deception",
    "difficulty_band": "moderate"
  },
  "requested_state_reads": []
}
```

Interpreter는 결과를 확정하지 않는다.

---

## Luna NPC Actor

NPC의 실제 지식과 관계 상태만 받는다.

절대 주지 않는 것:

- 세계 전체 hidden truth
- 다른 NPC의 private memory
- 플레이어가 알지 못하는 GM-only 정보 중 해당 NPC가 모르는 정보

출력:

```json
{
  "npc_id": "npc_harlan",
  "reaction_intent": "verify_claim",
  "speech_act": "request_evidence",
  "emotional_tone": "suspicious",
  "proposed_relation_delta": {
    "suspicion": 0.05
  }
}
```

실제 relation delta 적용 여부는 engine/policy가 결정한다.

---

## Luna Narrator

입력에는 이미 확정된 결과를 제공한다.

```json
{
  "check": "Deception",
  "dc": 15,
  "roll_total": 18,
  "outcome": "success",
  "state_changes": [
    "guard_allows_archive_access"
  ]
}
```

Narrator는 다음을 하면 안 된다.

- success를 failure로 바꾸기
- 새로운 보상 생성
- 추가 피해 임의 생성
- 숨겨진 사실 노출
- 플레이어 감정 강제
- 다음 플레이어 행동 자동 결정

---

## Luna Memory Summarizer

세션 로그를 단순 요약하는 역할이 아니다.

memory summary는 다음 형식으로 분리한다.

```text
FACTS
RELATION CHANGES
QUEST CHANGES
UNRESOLVED HOOKS
PLAYER DISCOVERIES
NPC-SPECIFIC MEMORIES
```

중요 fact는 원본 event ID를 유지한다.

예:

```json
{
  "fact": "Harlan saw the player carrying the royal seal.",
  "source_events": ["evt_0281", "evt_0284"],
  "confidence": 1.0
}
```

Luna summary가 원본 event를 대체하지 않는다.

---

## Luna World Planner

매 턴 호출하지 않는다.

호출 시점:

```text
in-game day changed
major faction event occurred
major quest resolved
campaign chapter changed
```

Planner는 다음 world events의 `후보`를 만든다.

실제 적용은 world engine이 검증한다.

---

# 12.3 Luna Context Budget 전략

성능 저하의 가장 흔한 원인은 모델 자체보다 과도하고 불필요한 context다.

따라서 context를 다음처럼 나눈다.

```text
Always
├─ GM contract
├─ current player state
├─ current location
└─ current turn

Conditional
├─ active NPC memory
├─ active quests
├─ nearby objects
├─ recent combat state
└─ relevant historical events

Never by default
├─ entire campaign log
├─ every NPC profile
├─ all locations
├─ all quests
└─ complete rules corpus
```

규칙 텍스트 역시 필요한 규칙만 retrieval한다.

---

# 12.4 Luna 호출 클래스

코드상 호출 목적을 명시적으로 분리한다.

```python
class LunaCallType(Enum):
    FAST_NARRATION = "fast_narration"
    ACTION_INTERPRETATION = "action_interpretation"
    NPC_RESPONSE = "npc_response"
    OUTCOME_NARRATION = "outcome_narration"
    MEMORY_SUMMARY = "memory_summary"
    WORLD_PLANNING = "world_planning"
```

로그에는 반드시 `call_type`을 저장한다.

이후 어떤 역할에서 품질 문제가 많은지 분석할 수 있다.

---

# 13. JEV: Fast Judgment Layer

JEV는 다음과 같은 question에 적합하다.

## 행동 분류

```yaml
action_type:
  type: choice
  choices:
    - social
    - attack
    - exploration
    - spell
    - item
    - movement
    - rest
```

## 판정 필요성

```yaml
requires_check:
  type: boolean
```

## skill 후보

```yaml
skill:
  type: choice
  choices:
    - athletics
    - acrobatics
    - stealth
    - investigation
    - perception
    - insight
    - deception
    - intimidation
    - persuasion
    - none
```

## 복잡한 Luna 추론 경로 필요 여부

```yaml
requires_luna_reasoning:
  type: boolean
```

## NPC reaction

```yaml
npc_reaction:
  type: choice
  choices:
    - cooperate
    - question
    - refuse
    - threaten
    - attack
    - retreat
    - ignore
```

---

# 14. JEV를 사용하면 안 되는 영역

JEV가 규칙의 최종 authority가 되면 안 된다.

예:

```text
잘못된 구조

JEV:
"이 상황은 opportunity attack입니다."

→ 그대로 공격 발생
```

대신:

```text
JEV
"상대가 threat zone을 떠나는 행동으로 보임"

↓

Rules Engine
actual position
movement type
disengage 여부
reaction 여부

↓

Opportunity Attack true / false
```

---

# 15. 세 계층의 권한

```text
Layer 1
Deterministic Game Engine
★★★★★ authority

Layer 2
GPT-5.6 Luna
★★★☆☆ interpretation

Layer 3
JEV
★★☆☆☆ classification / routing
```

Rules Engine이 최종 authority이다.

---

# 16. Luna 중심 Player Turn Pipeline

플레이어가 다음처럼 입력한다.

> 샹들리에 줄을 자르고 떨어지는 샹들리에를 밟아서 건너편 난간으로 뛰어간다.

## Step 1: context retrieval

```text
current location
nearby objects
player state
visible NPC
recent events
active quest
```

## Step 2: JEV pre-evaluation

```json
{
  "action_type": "movement",
  "requires_check": true,
  "risk": "high",
  "requires_luna_reasoning": true
}
```

## Step 3: GPT-5.6 Luna action interpretation

```json
{
  "intent": "reach_upper_balcony",
  "steps": [
    "cut_rope",
    "jump_on_chandelier",
    "jump_to_balcony"
  ],
  "proposed_check": {
    "skill": "acrobatics",
    "difficulty": "hard"
  }
}
```

## Step 4: Engine validation

엔진이 실제 환경 데이터를 확인한다.

```text
chandelier exists? yes
rope reachable? yes
balcony distance = 6.4m
player movement available? yes
```

## Step 5: check

```text
DC = 17
d20 = 14
DEX/Acrobatics bonus = +5

total = 19
success
```

## Step 6: state event

```json
{
  "type": "PLAYER_MOVED",
  "from": "great_hall_floor",
  "to": "east_balcony"
}
```

## Step 7: GPT-5.6 Luna narration

최종 판정은 바꾸지 못한다.

GPT-5.6 Luna에는 다음처럼 전달한다.

```text
Outcome: SUCCESS
Do not change mechanical result.
Narrate the sequence dramatically.
```

---

# 17. 게임 엔진 주요 모듈

```text
game/
├─ engine.py
├─ state.py
├─ commands.py
├─ events.py
├─ dice.py
├─ checks.py
├─ movement.py
├─ combat.py
├─ inventory.py
├─ conditions.py
├─ spells.py
└─ time.py
```

---

# 18. Command / Event 패턴

AI가 DB를 직접 수정하지 않는다.

예:

```python
MoveCharacter(
    character_id="player_1",
    destination="east_balcony"
)
```

Engine이 검사한다.

성공하면:

```python
CharacterMoved(...)
```

event를 생성한다.

---

# 19. 데이터 모델

## Campaign

```python
Campaign
- id
- name
- created_at
- current_day
- current_time
- current_location
- campaign_summary
```

## Character

```python
Character
- id
- name
- level
- race
- class
- hp
- max_hp
- ac
- stats
- skills
- location_id
```

## NPC

```python
NPC
- id
- name
- role
- location
- alive
- disposition
- goals
- personality
```

## Relationship

NPC마다 단순 friendly/hostile 대신 여러 축을 둔다.

```text
trust
fear
respect
affection
suspicion
debt
```

예:

```json
{
  "trust": 0.62,
  "fear": 0.05,
  "respect": 0.71,
  "suspicion": 0.14
}
```

---

# 20. NPC Knowledge Model

매우 중요한 부분.

NPC는 세계 전체를 알면 안 된다.

각 knowledge에는 provenance를 둔다.

```json
{
  "claim": "The mayor is working with smugglers",
  "npc": "npc_harlan",
  "belief": 0.71,
  "source": "informant_12",
  "truth_status": "unknown"
}
```

세계의 실제 truth와 NPC의 belief를 분리한다.

---

# 21. Hidden Truth System

예:

```yaml
world_truth:
  mayor_corrupt: true
  cult_leader: npc_0028
  dragon_alive: true
  ancient_vault_location: black_fen
```

플레이어는 직접 접근할 수 없다.

NPC 역시 직접 접근할 수 없다.

오직 GM reasoning layer가 필요한 경우 제한적으로 조회한다.

이 덕분에:

- 거짓말
- 오해
- 음모
- 미스터리
- 잘못된 소문

을 만들 수 있다.

---

# 22. Quest 시스템

퀘스트를 단순 textual objective로 두지 않는다.

```yaml
quest:
  id: q_001
  title: Missing Scholar

  states:
    - not_started
    - investigating
    - scholar_found
    - resolved
    - failed

  triggers:
    scholar_found:
      condition:
        event: PLAYER_DISCOVERED_LOCATION
        location: cellar_lab
```

AI가 quest state를 직접 마음대로 완료하지 못한다.

---

# 23. 시간 시스템

게임 시간은 engine이 관리한다.

행동별 시간 비용.

```text
대화: 5~20분
지역 이동: 거리 기반
short rest: 1시간
long rest: 8시간
전투: round 기반
탐색: 10~60분
```

시간이 지나면 world simulation trigger가 실행된다.

---

# 24. World Simulation

예:

```text
Day 7 → Day 8

Faction simulation
```

각 파벌은:

```text
goal
resources
knowledge
threats
relationships
current plan
```

을 가진다.

예:

```yaml
Black Hand:
  goal: control_port
  resources: 72
  influence: 0.43
  plan: bribe_customs_official
```

GPT-5.6 Luna가 복잡한 계획을 생성할 수 있지만 실제 world state 변경은 engine이 검증한다.

---

# 25. World Tick

매 turn마다 돌리지 않는다.

비용이 크다.

추천:

```text
minor tick:
important player action

medium tick:
1 in-game hour

major tick:
1 in-game day
```

---

# 26. Memory Architecture

LLM context에 모든 기록을 넣지 않는다.

메모리를 다음처럼 계층화한다.

## Tier 1: active scene

최근 10~30개 event

## Tier 2: location memory

현재 장소 관련 facts

## Tier 3: NPC memory

현재 등장 NPC 관련 facts

## Tier 4: campaign summary

장기 요약

## Tier 5: event archive

전체 로그

필요할 때 retrieval한다.

---

# 27. Context Builder

GPT-5.6 Luna에게 전달하는 context는 매번 자동 생성한다.

```text
SYSTEM
GM contract

CAMPAIGN
summary

CURRENT SCENE
location
time
weather

PLAYER
mechanical state

NPC
relevant characters

KNOWN FACTS
retrieved memory

HIDDEN FACTS
only if necessary

RECENT EVENTS
last N events

PLAYER ACTION
...
```

---

# 27.1 Luna 호출 최소화 정책

목표는 “최소 비용” 자체가 아니라 **게임 리듬을 끊지 않는 것**이다.

한 턴에서 권장 호출 수:

```text
0 call
정형 command

1 call
단순 대화 / narration

1~2 calls
일반 skill check

2~3 calls
복합 social interaction

3+ calls
특별한 복합 world event에서만
```

불필요한 구조:

```text
Intent model
↓
Skill model
↓
DC model
↓
NPC model
↓
Narrator model
```

권장 구조:

```text
JEV batch judgment
↓
Luna structured interpretation
↓
Engine
↓
Luna narration
```

---

# 27.2 Luna 결과 캐시

동일한 사실 조회나 static description을 매번 생성하지 않는다.

캐시 가능 항목:

```text
location base description
known NPC appearance
item description
static lore summary
rules retrieval
```

캐시하면 안 되는 항목:

```text
현재 NPC 반응
현재 장면 결과
플레이어 행동 해석
관계 변화
```

---

# 27.3 모델 독립성

애플리케이션 내부 코드에서 `"luna"`라는 문자열을 직접 여기저기 박지 않는다.

interface:

```python
class GMModel(Protocol):
    async def interpret_action(...): ...
    async def narrate_outcome(...): ...
    async def generate_npc_response(...): ...
```

default implementation:

```python
LunaGMModel
```

이렇게 하면 나중에 다른 모델 실험도 쉽다.

하지만 제품 기본값은 계속 Luna로 유지한다.

---

# 28. Combat

전투는 자연어와 grid를 둘 다 지원한다.

## Casual mode

> 고블린에게 달려들어서 검을 휘두른다.

자동으로 대상, 이동, 공격을 처리.

## Tactical mode

도트 grid에서 직접 캐릭터를 이동한다.

```text
5 ft grid
```

Phaser가 화면을 렌더링하고 Python engine이 실제 판정을 담당한다.

---

# 29. Combat Engine

```text
initiative
turn order
movement
action
bonus action
reaction
attack
damage
saving throws
conditions
concentration
death saves
```

MVP에서는 먼저:

```text
initiative
movement
basic attack
damage
death
```

만 구현한다.

---

# 30. D&D 규칙 범위

전체 D&D 책을 구현하지 않는다.

초기에는 SRD 범위 중심.

권장:

**SRD 5.2.1 기반 compatible game**

이렇게 표현하는 편이 좋다.

추후 개인 사용에서는 필요한 규칙을 추가할 수 있지만, 외부 공개/배포를 고려한다면 SRD 및 각 자산 라이선스를 철저히 분리한다.

---

# 31. Game Data Layer

```text
data/
├─ rules/
│  ├─ skills.json
│  ├─ conditions.json
│  └─ actions.json
│
├─ monsters/
├─ spells/
├─ items/
└─ classes/
```

rule text와 actual engine logic을 구분한다.

---

# 32. UI State

Frontend는 Zustand 정도면 충분하다.

예:

```text
useGameStore

campaign
character
activeScene
combat
map
selectedNpc
uiMode
debug
```

서버 state는 TanStack Query를 사용한다.

---

# 33. API 설계

## Player turn

```http
POST /api/game/turn
```

request:

```json
{
  "campaign_id": "cmp_1",
  "input": "경비병에게 시장이 보냈다고 거짓말한다."
}
```

response:

```json
{
  "narrative": "...",
  "events": [],
  "dice": [],
  "state_diff": {},
  "scene": {}
}
```

---

## Campaign

```text
POST /api/campaign
GET /api/campaign/{id}
POST /api/campaign/{id}/save
POST /api/campaign/{id}/load
```

## Character

```text
GET /api/character/{id}
POST /api/character/{id}/equip
POST /api/character/{id}/use-item
```

## Debug

```text
GET /api/debug/turn/{turn_id}
```

---

# 34. Streaming

Luna narrative는 streaming하도록 한다.

이렇게 하면 API 응답을 기다리는 느낌이 줄어든다.

화면:

```text
GM:
낡은 문이 천천히 열리기 시작한다...
```

텍스트가 token 단위로 표시된다.

반면 state mutation은 narrative streaming 전에 확정한다.

---

# 35. Pixel map과 backend 연결

Backend:

```json
{
  "location": "greyhaven_inn",
  "entities": [
    {
      "id": "player",
      "x": 12,
      "y": 8
    },
    {
      "id": "npc_harlan",
      "x": 18,
      "y": 6
    }
  ]
}
```

Phaser:

```text
state → sprites 위치 갱신
```

Phaser가 game truth를 갖지 않는다.

---

# 36. AI 생성 맵은 나중에

초기에는 사람이 만든 tilemap을 쓴다.

장기적으로는 GPT-5.6 Luna가:

```json
{
  "map_type": "dungeon",
  "size": [32, 32],
  "rooms": [...],
  "connections": [...]
}
```

같은 abstract layout을 생성하고 deterministic generator가 실제 tilemap을 만든다.

**LLM에게 32×32 tile index 배열을 직접 생성시키는 것은 권장하지 않는다.**

---

# 37. Procedural Map Generator

향후:

```text
GPT-5.6 Luna
↓
semantic map spec

{
  "rooms": [
    "entrance",
    "guard_room",
    "altar",
    "treasure"
  ]
}

↓

Python generator
↓
actual grid

↓

Phaser
```

이것이 가장 안정적이다.

---

# 38. 음악/사운드

MVP에는 필요 없다.

나중에:

```text
location ambience
combat
rain
tavern
forest
dungeon
```

정도만 추가해도 체감이 크다.

Audio engine은 browser Web Audio 또는 Howler.js 정도면 충분하다.

---

# 39. AI-generated art

초기에는 사용하지 않아도 된다.

도트 sprite는 공개 asset이 더 일관성이 높다.

향후 portrait만 이미지 생성 모델로 만든다.

```text
Pixel sprite
→ Kenney

NPC portrait
→ generated image
```

처럼 역할을 나누는 것이 좋다.

---

# 40. 가장 중요한 개발 순서

도트 그래픽부터 만들면 안 된다.

다음 순서가 적절하다.

```text
Game loop
→ state
→ AI
→ rules
→ save
→ UI
→ map
→ visual polish
```

---

# 41. Phase 0 — Repository bootstrap

목표:

실행 가능한 frontend/backend skeleton.

구조:

```text
luna-realms/

frontend/
backend/
data/
assets/
docs/
tests/
```

완료 기준:

```bash
npm run dev
```

과

```bash
uvicorn app.main:app --reload
```

가 실행된다.

---

# 42. Phase 1 — Text-only Vertical Slice

가장 중요한 단계.

도트 그래픽 없이 먼저 게임을 완성한다.

범위:

- 플레이어 1명
- NPC 2명
- 장소 3개
- 퀘스트 1개
- skill check
- 간단 전투
- save/load
- Luna GM
- JEV routing

플레이 시간:

```text
20~30분
```

성공 기준:

> 처음부터 엔딩까지 AI TRPG 한 판을 실제로 할 수 있다.

---

# 43. Phase 2 — Deterministic Game Engine

구현:

- dice
- character stats
- skill check
- inventory
- HP
- combat
- conditions
- event log

테스트 중심으로 작성한다.

예:

```python
def test_attack_hits_when_total_equals_ac():
    ...
```

---

# 44. Phase 3 — JEV Evaluation Layer

모든 JEV 호출을 저장한다.

```json
{
  "question": "requires_check",
  "input_hash": "...",
  "prediction": true,
  "confidence": 0.92,
  "final_engine_decision": true
}
```

이것이 추후 JEV 효용 검증 데이터가 된다.

---

# 45. Phase 4 — Luna GM

GPT-5.6 Luna prompt를 하나의 거대 prompt로 만들지 않는다.

분리한다.

```text
GM Interpreter
Narrator
World Planner
NPC Reasoner
Memory Summarizer
```

단, 실제 모델 호출은 상황에 따라 합칠 수 있다.

---

# 46. Phase 5 — React UI

구현 우선순위:

1. Story
2. Input
3. Character
4. Dice
5. Quest
6. NPC
7. Debug

map은 이후.

---

# 47. Phase 6 — Pixel Scene

Kenney 같은 공개 asset을 사용해 장소 하나만 만든다.

예:

```text
Greyhaven Inn
```

기능:

- background tilemap
- player sprite
- NPC sprite
- clickable NPC

이 정도면 충분하다.

---

# 48. Phase 7 — Grid Combat

전투 상태일 때 Phaser map이 tactical mode로 전환된다.

```text
Exploration
↓ encounter
Combat Mode
↓ victory
Exploration
```

---

# 49. Phase 8 — Persistent Campaign

추가:

- world day/time
- factions
- long-term NPC memory
- quest branching
- world events
- campaign summary

---

# 50. Phase 9 — World Simulation

파벌 행동을 도입한다.

MVP 이후 기능이다.

---

# 51. Phase 10 — Dynamic Content

GPT-5.6 Luna가 생성:

- NPC
- quest
- rumours
- locations
- encounters

생성된 content는 바로 사용하지 않고 schema validation을 거친다.

---

# 52. Quality Gates

각 AI output은 Pydantic schema를 통과해야 한다.

예:

```python
class ActionInterpretation(BaseModel):
    intent: str
    action_type: ActionType
    target_ids: list[str]
    proposed_check: SkillCheck | None
```

parsing 실패 시 narrative 생성으로 넘어가지 않는다.

---

# 53. Hallucination 방지

GPT-5.6 Luna에게 DB 전체를 자유롭게 수정하게 하지 않는다.

허용 tool:

```text
request_skill_check
request_move
request_attack
request_dialogue
propose_relation_change
propose_quest_event
```

Engine이 검증한다.

---

# 54. Narrative Contract

Luna Narrator는 다음을 지켜야 한다.

```text
- 이미 확정된 roll을 변경하지 않는다.
- 존재하지 않는 item을 만들지 않는다.
- 죽은 NPC를 살아 있게 하지 않는다.
- player의 생각이나 감정을 강제로 결정하지 않는다.
- player 행동 결과를 확정하지 않고 engine outcome을 따른다.
- hidden information을 노출하지 않는다.
```

---

# 55. 플레이어 agency

가장 중요하다.

GM은 다음을 하지 않는다.

> 너는 두려움에 질려 도망친다.

대신:

> 굉음과 함께 바닥이 흔들린다. 뜨거운 공기가 얼굴을 덮친다. 어떻게 하겠는가?

플레이어의 선택은 사용자가 결정한다.

---

# 56. Difficulty / DC 시스템

GPT-5.6 Luna가 임의 숫자를 바로 생성하지 않는다.

Luna/JEV는 difficulty category만 제안한다.

```text
trivial
easy
moderate
hard
very_hard
nearly_impossible
```

Engine이 해당 category를 DC로 변환한다.

이 방식이 DC drift를 줄인다.

---

# 57. 평가 데이터

이 프로젝트는 JEV 실험 플랫폼으로도 활용할 수 있다.

매 turn마다:

```text
player input
JEV decision
GPT-5.6 Luna interpretation
engine result
manual rating(optional)
```

을 저장한다.

---

# 58. JEV A/B Test

## Condition A

GPT-5.6 Luna only

## Condition B

Luna + JEV

## Condition C

JEV + Luna + deterministic constraints

비교:

- 판정 일관성
- rule violation
- latency
- cost
- 동일 상황 재실행 안정성
- 사람이 보기에 합리적인가

---

# 58.1 Luna 전용 평가 지표

단순 “재미있다”만으로 모델 품질을 평가하지 않는다.

## Action Interpretation

- target entity accuracy
- action type accuracy
- required check agreement
- skill choice agreement
- invalid state reference rate

## Narrative Fidelity

- engine outcome contradiction rate
- invented item rate
- invented NPC fact rate
- hidden truth leakage rate
- player-agency violation rate

## NPC Consistency

- knowledge boundary violation
- personality drift
- relationship-state contradiction
- dead/absent entity hallucination

## Memory

- factual retention
- false memory insertion
- provenance preservation
- outdated fact reuse

---

# 58.2 Luna vs JEV 기여 분리

다음 조건을 분리해서 비교한다.

```text
A. Luna only
B. JEV → Luna
C. JEV → Luna → deterministic engine
D. JEV → Luna → engine → Luna narration
```

D가 실제 제품 기본 조건이다.

비교 목적:

- JEV가 분류 안정성을 실제로 높이는가?
- Rules Engine이 hallucination을 얼마나 줄이는가?
- Narrator 분리가 결과 충실도를 높이는가?
- 호출 증가 대비 UX 개선이 있는가?

---

# 59. Regression Scenario Library

100개 정도의 고정 상황을 만든다.

예:

```text
R001
잠긴 문 앞

R002
적대적인 경비병 설득

R003
낭떠러지 점프

R004
은신 중 공격

R005
NPC에게 거짓 정보 제공
```

AI/Prompt가 바뀔 때 매번 돌린다.

---

# 60. Replay 기능

event log가 있기 때문에 특정 turn을 재실행할 수 있다.

예:

```text
Turn 81
Player input:
...

Run A
JEV v1

Run B
JEV v2
```

이 기능은 개발에 매우 유용하다.

---

# 61. Observability

Debug screen에 표시:

```text
Turn latency
GPT-5.6 Luna latency
JEV latency
tokens
cost
tool calls
retrieved memories
state diff
```

---

# 62. DB

혼자 쓰는 경우 SQLite가 가장 적합하다.

장점:

- 서버 설치 없음
- 파일 하나
- backup 쉬움
- Python 지원 훌륭
- 충분한 성능

파일:

```text
data/luna_realms.db
```

---

# 63. Save system

manual save와 autosave 둘 다 지원.

```text
autosave
- 매 turn
- combat 시작
- combat 종료
- major event
```

event log 때문에 저장 비용은 낮다.

---

# 64. 배포

개인 사용이면 처음에는 로컬.

```text
Frontend
localhost:3000

Backend
localhost:8000
```

Docker Compose로 나중에 한 명령으로 실행할 수 있게 한다.

```bash
docker compose up
```

---

# 65. 외부 접속이 필요할 때

그때만 배포한다.

예:

```text
Frontend
Vercel

Backend
Railway / Render / Fly.io

DB
SQLite 유지 가능
또는 Supabase/Postgres
```

하지만 1인용이라면 복잡하게 만들 필요 없다.

---

# 66. 모바일

Next.js responsive layout으로 만들면 된다.

모바일에서는:

```text
Story
↓
Input

bottom navigation
Character / Map / Quest / Journal
```

PC에서는 3-column.

---

# 67. 설치형 앱

나중에 필요하면 Tauri/Electron으로 감쌀 수 있다.

하지만 처음에는 PWA만으로 충분하다.

---

# 68. 공개 자원 활용 원칙

가능한 한 직접 만들지 않는다.

```text
UI
→ shadcn

icons
→ Lucide

rules content
→ SRD

game data
→ Open5e / SRD dataset

tile map
→ Tiled

pixel asset
→ Kenney / OpenGameArt

game canvas
→ Phaser

backend
→ FastAPI

validation
→ Pydantic
```

직접 만드는 핵심:

```text
Luna GM architecture
JEV evaluation
state engine
NPC knowledge
world simulation
AI ↔ deterministic bridge
```

---

# 69. 라이선스 관리

`THIRD_PARTY_LICENSES.md` 파일을 반드시 만든다.

예:

```text
Kenney Tiny Dungeon
License: CC0

D&D SRD 5.2.1
License: CC BY 4.0
Attribution: ...

OpenGameArt Asset X
License: CC0
```

에셋 다운로드 시 license 정보를 같이 저장한다.

---

# 70. 폴더 구조 최종안

```text
luna-realms/
│
├─ frontend/
│  ├─ app/
│  │  ├─ campaign/
│  │  ├─ character/
│  │  └─ settings/
│  │
│  ├─ components/
│  │  ├─ story/
│  │  ├─ character/
│  │  ├─ quest/
│  │  ├─ npc/
│  │  ├─ combat/
│  │  ├─ map/
│  │  └─ debug/
│  │
│  ├─ game/
│  │  └─ phaser/
│  │
│  ├─ stores/
│  └─ lib/
│
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ game/
│  │  ├─ ai/
│  │  │  ├─ luna/
│  │  │  └─ jev/
│  │  ├─ world/
│  │  ├─ memory/
│  │  ├─ rules/
│  │  └─ storage/
│  │
│  └─ tests/
│
├─ assets/
│  ├─ tiles/
│  ├─ sprites/
│  ├─ portraits/
│  ├─ maps/
│  └─ audio/
│
├─ data/
│  ├─ srd/
│  └─ campaign.db
│
├─ evals/
│  ├─ scenarios/
│  ├─ fixtures/
│  └─ reports/
│
├─ docs/
│  ├─ architecture.md
│  ├─ rules.md
│  ├─ ai-contract.md
│  └─ licenses.md
│
└─ docker-compose.yml
```

---

# 71. 첫 번째 Vertical Slice의 구체적 내용

## 장소

Greyhaven Inn

## NPC

Harlan — 경비대장  
Mira — 여행자

## 사건

도난당한 왕실 봉인

## 선택 가능한 접근

- 조사
- 설득
- 협박
- 거짓말
- 잠입
- 전투
- NPC 추적

## 엔딩

3개 정도.

---

# 72. Vertical Slice에서 반드시 검증할 것

1. 자연어 행동이 실제 game command로 변환되는가?
2. AI가 세계에 없는 사실을 함부로 생성하지 않는가?
3. JEV가 routing에 도움이 되는가?
4. 전투가 deterministic하게 돌아가는가?
5. 저장 후 이어서 플레이 가능한가?
6. NPC가 과거 사건을 기억하는가?
7. 동일 상황을 다시 실행해도 판정 범주가 크게 흔들리지 않는가?
8. 도트 맵이 몰입을 높이는가?

---

# 73. 처음 만들 필요 없는 것

다음은 절대로 MVP에 넣지 않는 것을 권장한다.

- multiplayer
- real-time networking
- voice
- 3D
- procedural animation
- huge open world
- 전체 D&D spell
- 전체 class
- 모든 monster
- AI-generated pixel sprites
- crafting
- economy simulation
- hundreds of NPCs
- multiplayer DM tools
- account/login

---

# 74. 초기 캐릭터 제한

처음에는:

```text
1 character
1 class
level 3
```

정도로 시작해도 충분하다.

게임 엔진이 검증되면 늘린다.

---

# 75. UI 미학

도트 그래픽과 현대적인 UI를 섞는다.

추천 방향:

```text
Game world:
Pixel art

UI:
Modern dark fantasy
```

즉 전체를 고전 RPG처럼 만들기보다:

```text
Baldur's Gate style information density
+
modern web UI
+
pixel tactical map
```

정도로 잡는다.

---

# 76. Map 표현의 역할

지도는 “이동 게임”이 아니라 **상황의 spatial grounding** 역할을 한다.

AI에게도 지도 데이터를 전달할 수 있다.

예:

```json
{
  "player": [12, 8],
  "guard": [15, 8],
  "door": [18, 8],
  "cover": [[13, 7], [14, 7]]
}
```

따라서:

> 경비병의 뒤로 몰래 간다

가 실제 공간 관계와 맞는지 확인할 수 있다.

이것은 AI GM의 hallucination을 줄이는 데도 도움이 된다.

---

# 77. 도트 그래픽의 실질적 개발 난이도

## 낮음

- static pixel background
- sprite 표시
- tilemap
- character marker
- click selection

## 중간

- character movement
- collision
- camera
- animated sprites
- tactical combat

## 높음

- procedural map
- dynamic animation generation
- fully simulated physical world
- procedural pixel art

따라서 **중간 단계까지만 목표로 하면 충분히 현실적이다.**

---

# 78. 예상 개발 난이도 배분

체감상 어려운 부분은 오히려 그래픽이 아니다.

```text
AI state consistency        ★★★★★
NPC knowledge/memory        ★★★★★
Rules ↔ natural language    ★★★★★
World state architecture    ★★★★☆
Combat engine               ★★★★☆
Pixel map                   ★★☆☆☆
React UI                    ★★★☆☆
```

---

# 79. 성공 기준

이 프로젝트의 성공은 예쁜 UI가 아니다.

다음 질문에 YES이면 성공이다.

> 2시간 플레이 후 AI가 1시간 전에 발생한 사건과 NPC의 지식 상태를 정확히 반영하면서, 플레이어가 예상하지 못한 자연어 행동을 시도해도 규칙적으로 합리적인 결과를 만들어낼 수 있는가?

---

# 80. 최종 목표 아키텍처

```text
                         PLAYER
                           │
                           ▼
                 ┌──────────────────┐
                 │   React Client   │
                 │                  │
                 │ Story / Map / UI │
                 └─────────┬────────┘
                           │
                           ▼
                 ┌──────────────────┐
                 │     FastAPI      │
                 └─────────┬────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
       JEV Router      Luna GM         Memory
          │                │                │
          └────────────┬───┴────────────────┘
                       ▼
              ┌─────────────────┐
              │ Action Proposal │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Rules Engine   │
              │ Deterministic   │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │    Game State   │
              │ SQLite + Events │
              └────────┬────────┘
                       │
            ┌──────────┴───────────┐
            ▼                      ▼
      Luna Narrator          Phaser Map
            │                      │
            └──────────┬───────────┘
                       ▼
                     PLAYER
```

---

# 81. 권장 첫 구현 목표

처음부터 “AI D&D 완성품”을 만들려고 하지 않는다.

첫 번째 목표는 다음 하나면 된다.

> **사용자가 자유문장으로 입력한 행동 하나가 JEV/GPT-5.6 Luna에 의해 해석되고, Python 규칙 엔진에서 검증·주사위 판정된 뒤, 게임 상태가 저장되고, GPT-5.6 Luna가 그 결과를 서술하며, React 화면과 작은 도트 맵에 결과가 반영된다.**

이 한 루프가 성공하면 나머지는 확장 문제다.

---

# 82. 첫 번째 개발 티켓

## `VERTICAL-001 — Player action end-to-end`

### 입력

```text
나는 문 옆 그림자에 숨어 경비병이 지나가기를 기다린다.
```

### 시스템

```text
JEV
→ exploration
→ stealth
→ check required

GPT-5.6 Luna
→ hide beside doorway
→ target = avoid guard detection

Engine
→ Stealth DC 14
→ roll = 11 + bonus 5
→ success

State
→ player.hidden = true

Luna Narrator
→ 결과 서술

Phaser
→ player sprite alpha / icon 변경
```

### PASS

- 결과가 DB에 기록됨
- narrative가 mechanical result와 일치
- 새로고침해도 상태 유지
- debug panel에서 전체 pipeline 확인 가능

이 ticket이 프로젝트의 진짜 시작점이다.

---

# 83. 2차 구현 티켓

## `VERTICAL-002 — NPC deception`

```text
"시장님이 직접 저를 보냈습니다."
```

JEV:

```text
social
deception
```

NPC knowledge 확인.

Engine check.

NPC state 변경.

GPT-5.6 Luna dialogue 생성.

---

# 84. 3차 구현 티켓

## `VERTICAL-003 — Combat`

```text
경비병을 밀치고 검을 뽑는다.
```

combat transition.

initiative.

attack.

damage.

state update.

pixel combat view.

---

# 85. 추천 결론

이 프로젝트는 다음처럼 생각하는 것이 가장 좋다.

```text
AI chatbot
×
D&D rules engine
×
persistent world simulator
×
small pixel RPG renderer
```

그중에서도 가장 중요한 것은:

```text
GPT-5.6 Luna = 기본 GM 해석·NPC·서사·요약
JEV = 빠른 판단·분류·라우팅
Python = 규칙과 게임 상태의 최종 권한
React = 사용 경험
Phaser = 세계의 공간적 표현
SQLite = 기억
```

이다.

도트 그래픽은 핵심 장애물이 아니다.

오히려 공개된 16×16/32×32 타일셋과 Tiled + Phaser를 사용하면 비교적 적은 코드로 “게임처럼 보이는” 수준까지 갈 수 있다.

반대로 가장 어려운 부분은 **LLM이 자유롭게 생성하면서도 게임 세계의 사실·규칙·NPC 지식을 침범하지 않도록 authority를 분리하는 것**이다.

따라서 개발 우선순위는 반드시 다음을 유지한다.

```text
1. 상태
2. 규칙
3. AI 계약
4. 턴 루프
5. 기억
6. UI
7. 도트 그래픽
8. 세계 확장
```

---

# 85.1 권장 런타임 모드

개발·운영 편의를 위해 세 가지 모드를 둔다.

## `economy`

```text
JEV 적극 활용
Luna 호출 최소화
world planning 빈도 낮음
```

빠른 반복 테스트용.

## `default`

```text
JEV pre-routing
Luna interpretation
deterministic engine
Luna narration
```

일상 플레이의 기본값.

## `cinematic`

```text
default
+
더 풍부한 Luna narration
+
중요 NPC 대화 확장
+
world planning 빈도 증가
```

중요 장면에서만 사용.

이 세 모드는 모델 자체를 바꾸지 않고 context와 호출 정책을 바꾼다.

---

# 85.2 설정 예시

```yaml
ai:
  default_model: gpt-5.6-luna

  jev:
    enabled: true

  escalation:
    enabled: false

  luna:
    fast_path: true
    max_repair_attempts: 2

world:
  minor_tick: important_action
  medium_tick: 1h
  major_tick: 1d

narrative:
  mode: default
```

초기 버전에서는 `escalation.enabled = false`를 권장한다.

먼저 Luna만으로 완주 가능한지 확인한다.

---

# 85.3 Luna 중심 MVP의 최종 성공 조건

다음 조건을 모두 만족해야 한다.

1. 30분 이상의 세션을 Luna 중심으로 완주할 수 있다.
2. 핵심 게임 상태를 Luna가 직접 수정하지 않는다.
3. 동일한 저장 상태에서 재실행했을 때 기계적 결과가 규칙적으로 재현된다.
4. NPC가 자신이 모르는 hidden truth를 발설하지 않는다.
5. Luna narration이 engine 결과를 뒤집지 않는다.
6. JEV가 없어도 fallback으로 플레이가 지속된다.
7. optional escalation이 꺼져 있어도 주요 기능이 모두 동작한다.
8. 새로고침/재실행 후 campaign state가 유지된다.
9. 도트 맵은 게임 상태를 표현할 뿐 별도 truth source가 되지 않는다.
10. debug panel에서 `JEV → Luna → Engine → State → Luna` 흐름을 추적할 수 있다.

---

# 86. 참고할 공개 기술/리소스

## 규칙

- Wizards of the Coast — D&D SRD 5.2.1
  - Creative Commons CC BY 4.0 기반.
  - 호환 가능한 5.5e 스타일 게임 규칙 기반으로 활용 가능.

## 도트 그래픽

- Kenney — Tiny Dungeon
  - 16×16
  - CC0

- Kenney — Tiny Town
  - 16×16
  - CC0

- Kenney — Roguelike Characters
  - CC0

- OpenGameArt
  - 다양한 CC0/CC-BY RPG tileset 존재.
  - 각 에셋별 라이선스 확인 필요.

## 지도

- Tiled Map Editor
  - GUI 기반 tilemap editor.
  - JSON export 가능.

## Rendering

- Phaser
  - Tilemap/Tiled JSON 지원.
  - sprite, scene, camera, collision, animation 등을 제공.

- PixiJS
  - 더 얇은 rendering layer가 필요한 경우 대안.

---

# 87. 최종 권장 MVP 범위 요약

```text
Frontend
Next.js + React + shadcn

Backend
FastAPI + Python

AI
Luna + JEV

DB
SQLite

Rules
SRD subset

Graphics
Phaser + Tiled + Kenney CC0

Campaign
1

Player
1

Locations
3

NPC
3~5

Quest
1

Combat
1 encounter

Playtime
20~40 minutes
```

이 정도가 완성되면 이후 기능은 거의 모두 “기존 시스템 위에 확장”하는 방식으로 진행할 수 있다.



---

# 부록 A. 이번 v2에서의 구현 우선순위

```text
P0
State / Event Log / Rules Engine

P1
GPT-5.6 Luna Interpreter
GPT-5.6 Luna Narrator
JEV Router

P2
NPC Knowledge
Memory Retrieval
Quest State

P3
React UI
Debug Panel

P4
Phaser Pixel Map
Combat Grid

P5
World Simulation
Optional Escalation
Procedural Content
```

가장 중요한 개발 원칙은 하나다.

> **Luna가 강해서 게임이 유지되는 것이 아니라, 게임 구조가 강해서 Luna를 안정적으로 사용할 수 있어야 한다.**

이 원칙을 지키면 이후 모델을 교체하거나 JEV를 제거·교체하더라도 게임 엔진 전체를 다시 만들 필요가 없다.
