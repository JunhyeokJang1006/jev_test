"""합성 fixture의 자유 입력 interpreter 평가 결과를 JSON stdout으로 출력한다."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-calls", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--provider", choices=("luna", "deepseek"), default="luna")
    args = parser.parse_args(argv)
    if args.live and (args.max_calls is None or not 1 <= args.max_calls <= 100):
        parser.error("--live에는 --max-calls 1~100이 필요합니다")
    if not args.live and args.max_calls is not None:
        parser.error("--max-calls에는 --live가 필요합니다")
    from app.evaluation import CORPUS, evaluate

    if not 0 <= args.offset < len(CORPUS):
        parser.error(f"--offset은 0~{len(CORPUS) - 1}이어야 합니다")
    if args.limit is not None and not 1 <= args.limit <= len(CORPUS) - args.offset:
        parser.error(f"--limit은 1~{len(CORPUS) - args.offset}이어야 합니다")
    report = evaluate(
        live=args.live,
        max_calls=args.max_calls,
        limit=args.limit,
        offset=args.offset,
        provider=args.provider,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
