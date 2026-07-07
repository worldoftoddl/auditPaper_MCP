#!/usr/bin/env python3
"""콜드 해석 채점기 (지시서 v1.1 7장) — 골드셋 recall.

사용법: python eval/score_interpretation.py reports/해석_<파일명>.md <조서id>
처리: 보고서에서 복합 ID 패턴을 추출해 standard_no 집합("KSA:315" 형)으로 환원, gold와 대조.
출력: JSON(표준출력) + eval/score_<조서id>.json 저장.

주의: routing_gold.json은 채점 전용이다 — 서버·에이전트 런타임 코드는 이 파일을 로드하지
않는다(코드 전체에서 참조는 이 채점기뿐). gold는 명시 참조 스캔 기반이므로 에이전트의
정당한 초과 인용이 gold에 없을 수 있다 → recall 중심, extras는 감점 없이 사람 검토.
"""

import json
import re
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
GOLD_PATH = EVAL_DIR / "routing_gold.json"
CID_RE = re.compile(r"\b(KSA|KIFRS|GUIDE)::([A-Za-z0-9.\-]+)::[^\s\]\)\},;'\"]+")


def score(report_path, worksheet_id):
    gold_doc = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    try:
        entry = gold_doc["worksheets"][worksheet_id]
    except KeyError:
        raise SystemExit(f"[중단] 골드셋에 조서 '{worksheet_id}' 없음 — "
                         f"eval/routing_gold.json의 worksheets 키 확인")
    gold = sorted({f"{code}:{no}" for code in ("KSA", "KIFRS", "GUIDE")
                   for no in entry.get(code, [])})

    text = Path(report_path).read_text(encoding="utf-8")
    cited = sorted({f"{m.group(1)}:{m.group(2)}" for m in CID_RE.finditer(text)})

    hit = [g for g in gold if g in cited]
    extras = [c for c in cited if c not in gold]
    result = {
        "worksheet": worksheet_id,
        "title": entry.get("title", ""),
        "gold": gold,
        "cited": cited,
        "recall": round(len(hit) / len(gold), 4) if gold else None,
        "missed": [g for g in gold if g not in hit],
        "extras": extras,
        "extras_note": "사람 검토 대상(감점 아님)" if extras else "",
        "report": str(report_path),
    }
    out_path = EVAL_DIR / f"score_{worksheet_id}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n저장: {out_path}", file=sys.stderr)
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("사용법: score_interpretation.py <보고서.md> <조서id>")
    score(sys.argv[1], sys.argv[2])
