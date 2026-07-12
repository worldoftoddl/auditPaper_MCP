#!/usr/bin/env python3
"""코퍼스 ↔ raw 원본 전수 대조 (품질 감사 2부, 2단계).

audit_extract_raw.py의 산출(eval/audit_out/raw_extract/)과 corpus_md/·guidelines_md/를
문단 단위로 대조한다.

- L1 존재성: 코퍼스 문단의 각 물리 행을 정규화(공백 전제거·NFKC·인용부호 접기)하여
  raw 전체 스트림에서 부분열 검색. 실패 행은 40자 조각으로 재검해 존재율 산출.
  버킷: OK(전 행 존재) / PARTIAL(조각 존재율≥0.5) / MISSING(<0.5).
- L2 번호 정렬: slug별 코퍼스 문단번호 집합 ↔ raw 추출 번호 집합의 차집합.
  raw−corpus = 수록 누락 후보(핵심), corpus−raw = 번호 재구성 한계 참고.
- 자가검증(--self-test): 코퍼스 문단 3건에 변조 주입 → 3/3 탐지 확인.

정당 차이 화이트리스트는 피감 스크립트의 보정 상수를 import해 대조 시 주석 처리
(피감 로직 재사용이 아니라 '선언된 보정 목록'의 확인이므로 감사 독립성과 무관).

사용법:
  .venv/bin/python eval/audit_compare.py                # 전수 대조
  .venv/bin/python eval/audit_compare.py --slug kifrs_1115
  .venv/bin/python eval/audit_compare.py --self-test
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXTRACT = ROOT / "eval" / "audit_out" / "raw_extract"
OUTFILE = ROOT / "eval" / "audit_out" / "compare_report.json"

sys.path.insert(0, str(ROOT / "scripts"))

CHUNK = 40          # 실패 행 재검 조각 길이 (정규화 후 문자 수)
PARTIAL_MIN = 0.5   # 이 미만이면 MISSING


# ------------------------------------------------------------------ 정규화

_QUOTE_MAP = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", "―": "-",
    "∼": "~", "〜": "~", "ㆍ": "·", "•": "·",
    "…": ".", "‥": ".",
})


def norm(s: str) -> str:
    """대조용 정규화: NFKC → 인용부호·대시 접기 → 모든 공백 제거."""
    s = s.replace("․", "·")  # ONE DOT LEADER(․) — NFKC가 '.'로 바꾸기 전에 가운데점으로
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_QUOTE_MAP)
    # 콜론 제거: 코퍼스가 용어정의 표를 "용어: 정의"로 재구성하며 삽입한 구분자
    s = s.replace(":", "").replace("：", "")
    # 낫표류 제거 — 2018-1·3 난독화 복원 시 「」가 한글 영역(녂녃)으로
    # 오변환되는 부작용까지 함께 접는다. 대괄호는 서식 삽입([명칭 기재])
    # 표기가 코퍼스·원문에서 엇갈려 함께 제거.
    s = re.sub(r"[「」『』〈〉《》녂녃\[\]{}'\"]", "", s)
    return re.sub(r"\s+", "", s)


def norm_line_md(line: str) -> str:
    """코퍼스 마크다운 행 → 대조용 텍스트. 장식 제거 후 norm."""
    t = line.strip()
    t = re.sub(r"^\|", "", t)
    t = t.replace("|", " ")                    # 표 구분자
    if re.fullmatch(r"[\s\-:|]+", t):          # 표 구분행 ---|---
        return ""
    t = re.sub(r"\*+", "", t)
    t = re.sub(r"\[\^\d+\]", " ", t)           # 각주 참조 마커 [^51]
    t = t.replace("<br>", " ")
    # 인라인 각주는 통째 제거 — 각주 내용은 raw에서 본문 스트림 밖(별도 각주부)에 있다
    t = re.sub(r"\[각주:[^\]]*\]", " ", t)
    t = re.sub(r"^[-*•·▪◦>]\s*", "", t)        # 불릿·인용
    t = re.sub(r"^부록-\([a-z0-9]{1,3}\)[\s.]*", "", t)  # 부록 내 항 마커 행
    # 행머리 하위 항 마커 — 감사기준 raw는 (a)·(1)·(ⅰ) 마커가 자동 번호라
    # 텍스트에 없음. 행머리에 한해 제거 (문중 괄호는 보존).
    t = re.sub(r"^\((?:[a-zA-Z]{1,4}|\d{1,2}|[ⅰ-ⅻ]{1,4})\)[\s.]*", "", t)
    return norm(t)


# --------------------------------------------------------------- 코퍼스 파싱

PARA_HEAD = re.compile(r"^(\S{1,40})\.\t(.*)$", re.S)
GUIDE_HEAD = re.compile(r"^(\d+(?:-\d+)?|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+)\.\s+(.*)$", re.S)


def parse_corpus_file(path: Path):
    """(paras, sections) — paras: [(para_id, [원문 행,...])], sections: [절 제목,...]"""
    text = path.read_text(encoding="utf-8")
    body = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    paras, sections = [], []
    cur = None
    for line in body.split("\n"):
        if line.startswith("## "):
            sections.append(line[3:].strip())
            cur = None
            continue
        m = PARA_HEAD.match(line)
        if m:
            cur = (m.group(1), [m.group(2)])
            paras.append(cur)
            continue
        if line.strip():
            if cur is None:
                cur = ("(무번호)", [line])
                paras.append(cur)
            else:
                cur[1].append(line)
    return paras, sections


# ------------------------------------------------------------ raw 스트림 구성

def load_raw_stream(slug: str, ksa_foot_pool: str) -> str | None:
    """slug(kifrs_NNNN[_bc|_ie] | ksa_* | guide_*)의 raw 정규화 스트림."""
    base = re.sub(r"_(bc|ie)$", "", slug)
    f = EXTRACT / f"{base}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    stream = norm(" ".join(p["text"] for p in d["paras"]))
    foots = norm(" ".join(d.get("footnotes", [])))
    if slug.startswith("ksa_"):
        foots += ksa_foot_pool
    return stream + "" + foots  # 경계 문자로 스트림 넘김 매치 방지


def load_raw_nos(slug: str) -> list[str]:
    base = re.sub(r"_(bc|ie)$", "", slug)
    f = EXTRACT / f"{base}.json"
    if not f.exists():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    return [p["no"] for p in d["paras"] if p.get("no")]


# ------------------------------------------------------------------ L1 대조

def check_para(lines: list[str], stream: str, is_guide: bool):
    """(버킷, 존재율, 실패행 목록)"""
    fails, total_chunks, hit_chunks = [], 0, 0
    for raw_line in lines:
        nl = norm_line_md(raw_line)
        if not nl:
            continue
        if nl in stream:
            n = max(1, len(nl) // CHUNK)
            total_chunks += n
            hit_chunks += n
            continue
        # 각주 위첨자 꼬리(…한다.12) 제거 재시도
        nl2 = re.sub(r"\.\d{1,3}(?=[가-힣(]|$)", ".", nl)
        # PDF 줄바꿈 하이픈 잔재(guide) 접기 재시도
        if is_guide:
            nl2 = nl2.replace("-", "")
        if nl2 != nl and (nl2 in stream or (is_guide and nl2 in stream.replace("-", ""))):
            n = max(1, len(nl) // CHUNK)
            total_chunks += n
            hit_chunks += n
            continue
        # 조각 재검
        hay = stream.replace("-", "") if is_guide else stream
        probe = nl2 if is_guide else nl
        chunks = [probe[i:i + CHUNK] for i in range(0, len(probe), CHUNK)] or [probe]
        hits = sum(1 for c in chunks if len(c) >= 8 and c in hay)
        short = [c for c in chunks if len(c) < 8]
        total_chunks += len(chunks)
        hit_chunks += hits + sum(1 for c in short if c in hay)
        fails.append({"line": raw_line.strip()[:120],
                      "chunk_hit": f"{hits}/{len(chunks)}"})
    rate = hit_chunks / total_chunks if total_chunks else 1.0
    if not fails:
        return "OK", 1.0, []
    return ("PARTIAL" if rate >= PARTIAL_MIN else "MISSING"), round(rate, 3), fails


# ------------------------------------------------------------------ L2 대조

CORPUS_L2_RE = re.compile(r"^(한?\d+(?:\.\d+)*[A-Z]?|[A-Z]{1,3}\d+[A-Z]?(?:\.\d+[A-Z]?)*|BC[A-Z]{1,2}\.?\d+[A-Z]?(?:\.\d+[A-Z]?)*)$")


def _desynth(cid: str) -> str | None:
    """갈래 합성 ID → raw 원번호 복원 (규약 4.3-5의 합성 문법 역변환).
    IE사례3-7 → 7 | IE부록B-12 → B12 | BC-B62 → B62 | IE부록2 → (원번호 없음)"""
    m = re.match(r"^IE사례\d+[A-Z]?-(.+)$", cid)
    if m:
        return m.group(1)
    m = re.match(r"^(?:IE|BC)부록([A-Z])-(.+)$", cid)
    if m:
        return m.group(1) + m.group(2)
    m = re.match(r"^BC-(.+)$", cid)
    if m:
        return m.group(1)
    return None


def l2_compare(slug: str, corpus_ids: list[str], raw_nos: list[str]):
    corpus_ids = list(corpus_ids) + [
        d for i in corpus_ids if (d := _desynth(i))]
    c = {i for i in corpus_ids if CORPUS_L2_RE.match(i)}
    r = set(raw_nos)
    if slug.startswith("ksa_"):
        # 감사기준 raw 번호는 본문·A 계열만 재구성됨 — 코퍼스도 같은 계열로 한정
        c = {i for i in c if re.fullmatch(r"A?\d+", i)}
    return sorted(r - c, key=str), sorted(c - r, key=str)


# ------------------------------------------------------------------ 메인

def iter_targets(only_slug: str | None):
    for f in sorted((ROOT / "corpus_md").glob("*.md")):
        if f.stem == "README":
            continue
        if only_slug and f.stem != only_slug:
            continue
        yield f.stem, f, False
    for f in sorted((ROOT / "guidelines_md").glob("guide_*.md")):
        if only_slug and f.stem != only_slug:
            continue
        yield f.stem, f, True


def guide_stream(slug: str) -> str | None:
    """guide는 본문 PDF + 부록 DOC/DOCX가 합본 — 존재하는 조각을 병합."""
    parts = []
    for cand in (slug, f"{slug}-appx"):
        f = EXTRACT / f"{cand}.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            parts.append(norm(" ".join(p["text"] for p in d["paras"])))
    if slug.startswith("guide_2014"):
        f = EXTRACT / "guide_2014-x.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8"))
            parts.append(norm(" ".join(p["text"] for p in d["paras"])))
    return "".join(parts) if parts else None


def run(only_slug=None, mutate=None):
    # 통합본 각주 풀 (추출기가 ksa_200에만 실음 — 전 ksa에 공유)
    f200 = EXTRACT / "ksa_200.json"
    ksa_foot_pool = ""
    if f200.exists():
        ksa_foot_pool = norm(" ".join(json.loads(f200.read_text())["footnotes"]))

    report, skipped = {}, []
    n_mutated = 0
    for slug, path, is_guide in iter_targets(only_slug):
        paras, sections = parse_corpus_file(path)
        if mutate and n_mutated < len(mutate):
            for idx in mutate:
                if idx < len(paras) and n_mutated < len(mutate):
                    pid, lines = paras[idx]
                    lines[0] = lines[0][:10] + "★변조주입된문자열★" + lines[0][30:]
                    n_mutated += 1
        stream = (guide_stream(slug) if is_guide
                  else load_raw_stream(slug, ksa_foot_pool))
        if stream is None:
            skipped.append(slug)
            continue
        rows = {"OK": 0, "PARTIAL": [], "MISSING": []}
        for pid, lines in paras:
            bucket, rate, fails = check_para(lines, stream, is_guide)
            if bucket == "OK":
                rows["OK"] += 1
            else:
                rows[bucket].append({"para": pid, "rate": rate, "fails": fails[:4]})
        report[slug] = {
            "n_para": len(paras), "ok": rows["OK"],
            "partial": rows["PARTIAL"], "missing": rows["MISSING"],
            "_ids": [p for p, _ in paras],
            "n_sections": len(sections),
        }

    # L2는 문서(base) 단위 — 정본+_bc+_ie 갈래의 코퍼스 ID를 합산해 raw 번호와 대조
    by_base = defaultdict(list)
    for slug in report:
        by_base[re.sub(r"_(bc|ie)$", "", slug)].append(slug)
    for base, slugs in by_base.items():
        ids = [i for s in slugs for i in report[s]["_ids"]]
        raw_extra, corpus_extra = l2_compare(base, ids, load_raw_nos(base))
        target = base if base in report else slugs[0]
        report[target]["l2_raw_only"] = raw_extra
        report[target]["l2_corpus_only"] = corpus_extra
    for slug in report:
        report[slug].pop("_ids")
        report[slug].setdefault("l2_raw_only", [])
        report[slug].setdefault("l2_corpus_only", [])
    return report, skipped


def summarize(report, skipped):
    tot = ok = 0
    worst = []
    for slug, r in sorted(report.items()):
        tot += r["n_para"]
        ok += r["ok"]
        n_p, n_m = len(r["partial"]), len(r["missing"])
        if n_p or n_m or r["l2_raw_only"]:
            worst.append((slug, n_p, n_m, len(r["l2_raw_only"])))
    print(f"\n총 {len(report)}파일 {tot}문단 | OK {ok} ({ok/tot*100:.2f}%) | "
          f"PARTIAL {sum(len(r['partial']) for r in report.values())} | "
          f"MISSING {sum(len(r['missing']) for r in report.values())}")
    if skipped:
        print(f"raw 부재로 건너뜀: {', '.join(skipped)}")
    if worst:
        print("\n이상 파일 (partial / missing / L2 raw-only):")
        for slug, p, m, l2 in sorted(worst, key=lambda x: -(x[1] + x[2]))[:30]:
            print(f"  {slug:20s} P={p:3d} M={m:3d} L2={l2}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        # kifrs_1115 문단 5·50·200에 변조 주입 → 전건 탐지돼야 함
        report, _ = run(only_slug="kifrs_1115", mutate=[5, 50, 200])
        r = report["kifrs_1115"]
        n_detect = len(r["partial"]) + len(r["missing"])
        print(f"[자가검증] 변조 3건 주입 → 탐지 {n_detect}건 "
              f"({'통과' if n_detect >= 3 else '실패'})")
        base, _ = run(only_slug="kifrs_1115")
        b = base["kifrs_1115"]
        n_base = len(b["partial"]) + len(b["missing"])
        print(f"[자가검증] 비변조 기준선 이상: {n_base}건 (변조 탐지는 기준선 대비 +3이어야 함)")
        ok = n_detect - n_base >= 3
        print("자가검증:", "3/3 통과" if ok else "실패")
        sys.exit(0 if ok else 1)

    report, skipped = run(only_slug=args.slug)
    summarize(report, skipped)
    OUTFILE.parent.mkdir(parents=True, exist_ok=True)
    OUTFILE.write_text(json.dumps(
        {"report": report, "skipped": skipped}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(f"\n저장: {OUTFILE}")


if __name__ == "__main__":
    main()
