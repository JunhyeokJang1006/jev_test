# 자유 입력 해석 평가

이 평가기는 26개의 고정 한국어 자유문장과 합성 장면에서 interpreter의 `intent`와 순서 있는 `target_ids`를 채점한다. 버튼 문구와 정확히 같은 입력은 사용하지 않는다. 정답은 corpus에 독립적으로 명시하며 mock 결과에 맞춰 생성하지 않는다. 실제 DB, 플레이 기록, 엔진 판정, 주사위, narrator를 실행하지 않으므로 실제 플레이나 게임 전체 완성도 검증이 아니다.

기본 실행은 공급자 설정 함수를 호출하지 않고 HTTP 호출 예산도 0으로 제한한다.

```bash
uv run --locked python scripts/evaluate_ai.py
```

실모델 평가는 사용자가 연결 정보와 유료 호출 범위를 확인한 뒤 명시적으로 실행한다. 기존 AI 어댑터의 `.env` 로더를 사용하며 공급자는 하나만 선택한다. Luna가 기본이며 DeepSeek 보조 fallback은 평가에서는 끈다.

```bash
uv run --locked python scripts/evaluate_ai.py --live --provider luna --max-calls 3 --limit 3
uv run --locked python scripts/evaluate_ai.py --live --provider deepseek --max-calls 26
```

`--max-calls`는 live 필수이고 1~100이다. HTTP 직전 전체 호출 수를 제한한다. 예산 소진·미설정·실패로 mock이 반환된 사례도 전체 정확도에 포함되지만 실모델 평가 수와 공급자 정확도에는 포함되지 않는다. `--limit`은 1~26이며 생략하면 전체 corpus를 평가한다. 일부 사례만 선택한 결과는 `complete: false`로 표시한다.

기존 `GM_PROVIDER` 설정도 적용된다. `GM_PROVIDER=mock`이거나 선택 공급자가 설정에서 제외되어 있으면 live 플래그만으로 이를 덮어쓰지 않으며 모델 coverage는 0이 된다. 필요한 경우 위 live 명령 앞에 `GM_PROVIDER=luna` 또는 `GM_PROVIDER=deepseek`를 명시한다.

JSON은 stdout에만 출력한다. 원문 입력·상태·응답·오류 메시지·키는 출력하지 않는다. 사례별 기대/실제 intent와 targets, 공급자, 정답 여부, 실제 모델 평가 여부와 호출 메타데이터를 제공한다. 알 수 없는 intent/target 문자열은 가린다. 전체 정확도, 실제 모델 coverage, 공급자 전용 정확도, 호출 지연의 최근접 순위 p50/p95, 입력/출력 토큰 합계와 누락 수를 보고한다. 토큰 합계는 사용량을 반환한 호출의 합이며 누락을 0토큰으로 확정하지 않는다.

선택 사례가 모두 정답이며 live에서는 모든 사례가 선택 모델의 성공한 호출로 해석됐을 때만 종료 코드 0이다. 측정된 오답이나 fallback coverage 부족은 1, 잘못된 CLI 인자는 2다. 기본 mock은 이동·대화 등을 폭넓게 해석하지 못하므로 오답과 종료 코드 1이 나오는 것이 현재 측정 결과다. mock 실행 및 HTTP 응답 대체 테스트의 성공은 실제 모델 정확도 PASS를 뜻하지 않는다.

검사 범위는 이동/대화, 문 옆 은신, 금지·존재하지 않는 대상, 두 고블린 공격, 밀치기/교란/질주, 행동 예산 소진, 회복과 자원 부족, 결말 설명 요청과 명시 실행, 불지원 행동이다. 정답과 합성 상태를 수정할 때 corpus 정합성 검사를 함께 실행한다.

```bash
uv run --locked pytest -q backend/tests/test_evaluation.py
```

## 2026-09-21 실행 기록

[실행 요약](evaluation-2026-09-21.json): 실제 OpenAI `gpt-5.6-luna`로 첫12개 합성 사례를
평가하여12개 명령이 일치했다. HTTP12회, fallback0회, 입력10,088/출력818토큰,
호출 지연 p50 1,375.126ms/p95 2,475.690ms였다. 전체26개 중14개와 narrator·JEV·
30분/2시간 실제 플레이는 이번 유료 검사에서 실행하지 않았다. 고정 소표본의 결과를
일반적인 해석 정확도95% 달성으로 해석하지 않는다.

모델 ID와 Chat Completions 지원은 [OpenAI 공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-luna)에서 재확인했다.
가격·캐시 세부 항목은 이 실행 보고서로 계산하지 않았으며 토큰 사용량을 비용 청구액으로
간주하지 않는다. 호출 예산은 HTTP 횟수 제한이며 달러 비용 한도가 아니다.

동일26개에 대한 mock 측정은14개 정답(53.85%)이다. mock은 광범위한 자연어 플레이를
대체하지 못한다. 평가 중 혼합 대상/미등록 고블린 공격을 첫 고블린으로 바꾸던 fallback
결함을 발견하여, 전체 문장이 명확한 지원 공격 패턴과 일치할 때만 공격하도록 수정했다.
정확한 버튼 명령은 유지하며 복합·부정·질문 표현을 키워드만으로 피해 행동으로 바꾸지 않는다.

`app.ai_metrics.capture_calls`는 컨텍스트별 호출 정보와 선택적 호출 상한을 제공한다.
중첩 컨텍스트도 부모 예산을 우회하지 못하고 실패한 시도도 횟수에 포함된다.
`luna_realms.ai_calls` 로거의 INFO 메타데이터에는 호출 종류·공급자/모델·지연·토큰·
고정 상태 코드만 담긴다. 프롬프트·응답 원문·URL·키·오류 문구를 수집하지 않는다.
DB 영속 계측, 세션별 비용 제한, 의미적 narrator 평가는 후속 작업이다.
