#!/usr/bin/env python3
"""raw 원본 → 문단 스트림 추출 (품질 감사 2부, 1단계).

corpus_md/·guidelines_md/와의 전수 대조(audit_compare.py)를 위해 raw/ 원본에서
텍스트를 독립 추출한다. 피감 파이프라인(normalize_corpus.py 등)의 로직을 재사용하지
않는다 — 같은 버그를 공유하면 대조가 무의미해지기 때문. OOXML/PDF 명세만 따른다.

출력: eval/audit_out/raw_extract/<slug>.json
  {"slug", "source", "paras": [{"no": str|null, "text": str}], "footnotes": [str]}
  - paras: 본문 순서대로 문단·표 셀 텍스트. no는 문단번호(K-IFRS 리터럴 행머리 or
    감사기준 numbering.xml 전개 결과 "12."/"A34." → "12"/"A34").
  - footnotes: footnotes.xml + endnotes.xml 텍스트 (L1 대조 시 본문과 합산).

사용법:
  .venv/bin/python eval/audit_extract_raw.py --group kifrs   # K-IFRS 63건
  .venv/bin/python eval/audit_extract_raw.py --group ksa     # 감사기준 통합본 36분할 + 3건
  .venv/bin/python eval/audit_extract_raw.py --group guide   # 실무지침 (PDF/DOC/DOCX)
  .venv/bin/python eval/audit_extract_raw.py                 # 전체
"""

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
GRAW = ROOT / "guidelines_raw"
OUT = ROOT / "eval" / "audit_out" / "raw_extract"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


# ---------------------------------------------------------------- DOCX 공통

def zread(z: zipfile.ZipFile, name: str) -> bytes | None:
    """zip 항목명 구분자(\\ vs /) 편차 흡수."""
    for n in z.namelist():
        if n.replace("\\", "/") == name:
            return z.read(n)
    return None


def _run_text(el) -> str:
    """w:p 아래 텍스트 수집. 삭제 추적(w:delText)·필드코드(instrText)·
    호환성 Fallback(mc:Fallback, 이중 추출 방지)은 제외. tab/br → 공백."""
    parts = []
    for node in el.iter():
        tag = node.tag
        if tag == MC + "Fallback":
            # iter는 서브트리 스킵이 안 되므로 표식 후 아래에서 걸러야 하지만,
            # lxml에서는 조상 검사로 처리
            continue
        if tag in (W + "t", W + "instrText", W + "delText"):
            if tag != W + "t":
                continue
            if any(a.tag == MC + "Fallback" for a in node.iterancestors()):
                continue
            if any(a.tag == W + "del" for a in node.iterancestors()):
                continue
            parts.append(node.text or "")
        elif tag in (W + "tab", W + "br", W + "cr"):
            parts.append(" ")
    return "".join(parts)


def _iter_block_texts(container):
    """body/tbl-cell 하위의 블록(p, tbl)을 문서 순서로 순회하며 (kind, element) 방출."""
    for child in container:
        if child.tag == W + "p":
            yield ("p", child)
        elif child.tag == W + "tbl":
            for row in child.iter(W + "tr"):
                for cell in row.iter(W + "tc"):
                    for p in cell.iter(W + "p"):
                        yield ("cell", p)


def read_docx(path: Path):
    """(body_root, footnote_texts) 반환."""
    z = zipfile.ZipFile(path)
    doc = zread(z, "word/document.xml")
    if doc is None:
        raise RuntimeError(f"document.xml 없음: {path.name}")
    root = etree.fromstring(doc)
    body = root.find(W + "body")
    foots = []
    for part in ("word/footnotes.xml", "word/endnotes.xml"):
        raw = zread(z, part)
        if raw is None:
            continue
        for fn in etree.fromstring(raw).iter(W + "footnote", W + "endnote"):
            t = " ".join(_run_text(p) for p in fn.iter(W + "p")).strip()
            if t:
                foots.append(t)
    return z, body, foots


# ------------------------------------------------- K-IFRS: 리터럴 번호 추출

# 행머리 문단번호 (K-IFRS 원문은 번호가 텍스트에 리터럴로 포함 — numId=0으로 자동번호 해제)
# 독립 판정식: 피감 코드의 HEAD_RE를 import하지 않는다.
KIFRS_NO_RE = re.compile(
    r"^(한\s?\d+(?:\.\d+)*[A-Z]?"          # 한국 추가 문단 한2.1
    r"|\d+(?:\.\d+)*[A-Z]?(?:\.\d+)*"       # 1, 31, 5.1, 129A
    r"|[A-Z]{1,3}\d+[A-Z]?(?:\.\d+)*"       # A1, B35B, BC172, IE3, IG14
    r"|BC[A-Z]{1,2}\.?\d+(?:\.\d+)*[A-Z]?"  # BCE.238, BCG.1
    r"|[A-Z]\d+[A-Z]?)"
    r"(?=\s| |$)")


def extract_kifrs(path: Path) -> dict:
    _, body, foots = read_docx(path)
    paras = []
    for kind, p in _iter_block_texts(body):
        tx = _run_text(p).strip()
        if not tx:
            continue
        no = None
        if kind == "p":
            m = KIFRS_NO_RE.match(tx)
            # 영문 위주 행(저작권 블록의 주소 "7 Westferry…" 등)은 번호 오탐 제외
            if m and sum(c.isascii() for c in tx) / len(tx) < 0.7:
                no = m.group(1).replace(" ", "")
        paras.append({"no": no, "text": tx})
    return {"paras": paras, "footnotes": foots}


# ------------------------------------------- 감사기준: numbering.xml 전개

class NumberingExpander:
    """OOXML numbering 전개 — 감사기준 문단번호('1.', 'A1.') 재구성 전용.

    Word 의미론 요약 구현:
    - 카운터는 abstractNum 스코프. 같은 abstract를 공유하는 num 인스턴스는 카운터 공유.
    - num의 lvlOverride/startOverride는 그 numId가 문서에서 처음 사용될 때 카운터 재시작.
    - 문단 numPr(numId=0이면 번호 해제)이 스타일 상속(basedOn 체인)보다 우선.
    """

    def __init__(self, z: zipfile.ZipFile):
        self.num2abs = {}          # numId -> absId
        self.overrides = {}        # numId -> {ilvl: startOverride}
        self.levels = {}           # absId -> {ilvl: (numFmt, lvlText, start)}
        self.counters = {}         # absId -> {ilvl: int}
        self.seen_num = set()
        raw = zread(z, "word/numbering.xml")
        if raw is not None:
            nroot = etree.fromstring(raw)
            for a in nroot.iter(W + "abstractNum"):
                aid = a.get(W + "abstractNumId")
                lvls = {}
                for lv in a.iter(W + "lvl"):
                    il = int(lv.get(W + "ilvl"))
                    fmt = lv.find(W + "numFmt")
                    txt = lv.find(W + "lvlText")
                    st = lv.find(W + "start")
                    lvls[il] = (
                        fmt.get(W + "val") if fmt is not None else "decimal",
                        txt.get(W + "val") if txt is not None else "",
                        int(st.get(W + "val")) if st is not None else 1,
                    )
                self.levels[aid] = lvls
            for n in nroot.iter(W + "num"):
                nid = n.get(W + "numId")
                a = n.find(W + "abstractNumId")
                self.num2abs[nid] = a.get(W + "val") if a is not None else None
                ovr = {}
                for lo in n.findall(W + "lvlOverride"):
                    so = lo.find(W + "startOverride")
                    if so is not None:
                        ovr[int(lo.get(W + "ilvl"))] = int(so.get(W + "val"))
                if ovr:
                    self.overrides[nid] = ovr
        # 스타일 → numPr (basedOn 체인)
        self.style_num = {}
        sraw = zread(z, "word/styles.xml")
        if sraw is not None:
            sroot = etree.fromstring(sraw)
            styles = {}
            for s in sroot.iter(W + "style"):
                styles[s.get(W + "styleId")] = s
            for sid, s in styles.items():
                cur, depth = s, 0
                while cur is not None and depth < 10:
                    npr = cur.find(f"{W}pPr/{W}numPr")
                    if npr is not None:
                        nid = npr.find(W + "numId")
                        il = npr.find(W + "ilvl")
                        if nid is not None:
                            self.style_num[sid] = (
                                nid.get(W + "val"),
                                int(il.get(W + "val")) if il is not None else 0,
                            )
                        break
                    based = cur.find(W + "basedOn")
                    cur = styles.get(based.get(W + "val")) if based is not None else None
                    depth += 1

    def effective(self, p) -> tuple[str, int] | None:
        npr = p.find(f"{W}pPr/{W}numPr")
        if npr is not None:
            nid_el = npr.find(W + "numId")
            if nid_el is not None:
                nid = nid_el.get(W + "val")
                if nid == "0":
                    return None
                il = npr.find(W + "ilvl")
                ilvl = int(il.get(W + "val")) if il is not None else 0
                return (nid, ilvl)
            # numId 없는 numPr → 스타일로 폴백
        st = p.find(f"{W}pPr/{W}pStyle")
        if st is not None:
            return self.style_num.get(st.get(W + "val"))
        return None

    _FMT_ALPHA = "abcdefghijklmnopqrstuvwxyz"

    def _fmt(self, fmt: str, v: int) -> str | None:
        if fmt == "decimal":
            return str(v)
        if fmt == "lowerLetter":
            return self._FMT_ALPHA[(v - 1) % 26]
        if fmt == "upperLetter":
            return self._FMT_ALPHA[(v - 1) % 26].upper()
        return None  # bullet·roman·ganada 등 — 문단번호 아님

    def advance(self, p) -> str | None:
        """문단의 전개 번호 문자열('1.'·'A1.' 등) 또는 None."""
        eff = self.effective(p)
        if eff is None:
            return None
        nid, ilvl = eff
        absid = self.num2abs.get(nid)
        if absid is None or absid not in self.levels:
            return None
        cnt = self.counters.setdefault(absid, {})
        if nid not in self.seen_num:
            self.seen_num.add(nid)
            for il, v in self.overrides.get(nid, {}).items():
                cnt[il] = v - 1  # 다음 증가에서 v가 되도록
        lvls = self.levels[absid]
        if ilvl not in lvls:
            return None
        fmt, lvltext, start = lvls[ilvl]
        cnt[ilvl] = cnt.get(ilvl, start - 1) + 1
        for deeper in [k for k in cnt if k > ilvl]:
            del cnt[deeper]
        # lvlText의 %k 치환
        def sub(m):
            k = int(m.group(1)) - 1
            if k not in lvls:
                return ""
            kf, _, ks = lvls[k]
            s = self._fmt(kf, cnt.get(k, ks))
            return s if s is not None else "�"
        if fmt == "bullet" or not lvltext:
            return None
        out = re.sub(r"%(\d)", sub, lvltext)
        return None if "�" in out else out


KSA_NO_RE = re.compile(r"^(A?\d+)\.$")  # 전개 번호 중 문단번호로 채택할 형식


def extract_ksa_docx(path: Path):
    """numbering 전개 포함 감사기준 DOCX 추출 → 문단 리스트 (경계 분할 전)."""
    z, body, foots = read_docx(path)
    exp = NumberingExpander(z)
    paras = []
    for kind, p in _iter_block_texts(body):
        tx = _run_text(p).strip()
        no = None
        if kind == "p" and tx:
            # 빈 번호 문단은 번호를 소비하지 않는다 — Word 렌더링과 달리 공표
            # 기준서의 실제 번호는 빈 문단을 건너뛴다 (560 A8 실측: 빈 문단이
            # numId 48을 직접 보유하나 공표본 A8은 다음 본문 문단에 붙음).
            label = exp.advance(p)
            if label:
                m = KSA_NO_RE.match(label)
                if m:
                    no = m.group(1)
        if not tx:
            continue
        style = None
        if kind == "p":
            st = p.find(f"{W}pPr/{W}pStyle")
            style = st.get(W + "val") if st is not None else None
        paras.append({"no": no, "text": tx, "_style": style})
    return paras, foots


ISA_BOUND_RE = re.compile(r"^(감사기준서|품질관리기준서)\s*(\d+)\s")


def extract_ksa_group(outdir: Path):
    """통합본 36분할 + 별도 3건."""
    combined = RAW / "감사기준" / "0. 회계감사기준 전문(2025 개정).docx"
    paras, foots = extract_ksa_docx(combined)
    # style '10' + '감사기준서 NNN' 제목이 기준서 경계
    docs = {}   # no -> paras
    cur = None
    preamble = []
    for p in paras:
        if p["_style"] == "10":
            m = ISA_BOUND_RE.match(p["text"] + " ")
            if m:
                cur = m.group(2)
                docs[cur] = []
        (docs[cur] if cur else preamble).append(p)
    for no, ps in docs.items():
        write_out(outdir, f"ksa_{no}", str(combined.relative_to(ROOT)),
                  ps, foots if no == "200" else [])
        # 각주는 통합본 공유 — 첫 문서에만 실어 중복 집계 방지, 대조 시 전체 병합 옵션
    print(f"  통합본 분할: {len(docs)}건 ({', '.join(sorted(docs, key=int))})")
    if preamble:
        write_out(outdir, "ksa_preamble", str(combined.relative_to(ROOT)), preamble, [])

    singles = [
        ("ksa_isqm-1", RAW / "감사기준" / "3. 품질관리기준서1(2018년 제정)_국어전문.docx"),
        ("ksa_assr-3000", RAW / "감사기준" /
         "역사적 재무정보에 대한 감사 및 검토 이외의 인증업무기준(2022년 개정)_전문(개정개요 포함).docx"),
        ("ksa_frmk-1", RAW / "감사기준" / "인증업무개념체계(2022년 개정)_전문.docx"),
    ]
    for slug, path in singles:
        ps, fs = extract_ksa_docx(path)
        write_out(outdir, slug, str(path.relative_to(ROOT)), ps, fs)
        print(f"  {slug}: {len(ps)}문단")


# ------------------------------------------------------------- 실무지침

OBF_LO, OBF_HI = 0xAC00 - 0x912A, 0xD7A3 - 0x912A  # 난독 문자 영역


def deobfuscate_line(txt: str) -> str:
    """2018-1·2018-3 PDF의 폰트 난독화 복원: 본문 폰트의 코드포인트가 실제
    한글에서 -0x912A 이동(ToUnicode 부재로 pdfminer는 드롭, PyMuPDF는 보존).
    행 문자의 1/3 이상이 난독 영역일 때만 행 전체를 +0x912A 복원 —
    로마숫자 등 정상 특수문자(머리글 폰트)의 오변환을 막는다."""
    stripped = txt.strip()
    if not stripped:
        return txt
    n_obf = sum(1 for ch in stripped if OBF_LO <= ord(ch) <= OBF_HI)
    if n_obf < max(1, len(stripped) // 3):
        return txt
    return "".join(
        chr(ord(ch) + 0x912A) if OBF_LO <= ord(ch) <= OBF_HI else ch
        for ch in txt)


def extract_pdf(path: Path, deobf: bool) -> dict:
    import fitz  # PyMuPDF — pdfplumber는 난독 글리프를 드롭하므로 사용 불가
    paras = []
    doc = fitz.open(str(path))
    for pg in doc:
        for blk in pg.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                txt = "".join(sp["text"] for sp in line["spans"]).strip()
                if deobf:
                    txt = deobfuscate_line(txt)
                if txt:
                    paras.append({"no": None, "text": txt})
    return {"paras": paras, "footnotes": []}


def extract_doc_catdoc(path: Path) -> dict | None:
    import shutil
    import subprocess
    if not shutil.which("catdoc"):
        return None
    r = subprocess.run(["catdoc", "-d", "utf-8", str(path)],
                       capture_output=True)
    if r.returncode != 0:
        return None
    # catdoc이 변환 못 한 바이트가 간헐 혼입 — 대체문자로 관용 디코드
    out = r.stdout.decode("utf-8", errors="replace")
    paras = [{"no": None, "text": ln.strip()}
             for ln in out.splitlines() if ln.strip()]
    return {"paras": paras, "footnotes": []}


def extract_guide_group(outdir: Path):
    jobs = [
        # (slug, 파일, 종류, 난독화)
        ("guide_2016-1", GRAW / "[붙임1]회계감사실무지침2016-1(2018년 개정) 개정개요와전문(공표).pdf", "pdf", False),
        ("guide_2017-1", GRAW / "[붙임]회계감사실무지침 2017-1. 전기오류수정에 관한 실무지침(2019년 개정).pdf", "pdf", False),
        ("guide_2018-1", GRAW / "[붙임1]회계감사실무지침 2018-1. 업무수행이사 이름 공시 예외에 관한 회계감사실무지침.pdf", "pdf", True),
        ("guide_2018-2", GRAW / "회계감사실무지침 2018-2. 지배기구와의 커뮤니케이션에 관한 회계감사실무지침(2023년 개정).pdf", "pdf", False),
        ("guide_2018-3", GRAW / "[붙임3]회계감사실무지침 2018-3. 감사 전 재무제표 확인 등에 관한 회계감사실무지침.pdf", "pdf", True),
        ("guide_2014-x", GRAW / "3.회계감사실무지침 전부개정 - 개정전문.doc", "doc", False),
        ("guide_2015-1", GRAW / "1. 회계감사실무지침2015-1 - 제정개요와 전문.doc", "doc", False),
        ("guide_2015-1-appx", GRAW / "2. 감사보고서가 첨부되는 재무제표 책자의 표지와 목차 예시.docx", "docx", False),
        ("guide_2016-1-appx", GRAW / "(붙임)회계감사실무지침2016-1._감사보고서_핵심감사항목_기재사례.doc", "doc", False),
    ]
    skipped = []
    for slug, path, kind, deobf in jobs:
        if kind == "pdf":
            data = extract_pdf(path, deobf)
        elif kind == "docx":
            data = extract_kifrs(path)  # 리터럴 추출로 충분
        else:
            data = extract_doc_catdoc(path)
            if data is None:
                skipped.append(slug)
                continue
        write_out(outdir, slug, str(path.relative_to(ROOT)),
                  data["paras"], data["footnotes"])
        print(f"  {slug}: {len(data['paras'])}행")
    if skipped:
        print(f"  [보류] catdoc 부재로 .doc 미추출: {', '.join(skipped)}")


# ---------------------------------------------------------------- 공통 출력

def write_out(outdir: Path, slug: str, source: str, paras, footnotes):
    for p in paras:
        p.pop("_style", None)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{slug}.json").write_text(
        json.dumps({"slug": slug, "source": source,
                    "paras": paras, "footnotes": footnotes},
                   ensure_ascii=False), encoding="utf-8")


CF_MAP = {
    "kifrs_cf": "시행중_K-IFRS_재무보고를_위한_개념체계",
    "kifrs_mc": "경영진설명서_작성을_위한_개념체계_번역서_수정",
    "kifrs_ps2": "국제회계기준_실무서_2_중요성에_대한_판단_번역서",
}


def extract_kifrs_group(outdir: Path):
    files = sorted((RAW / "IFRS_docx").rglob("*.docx"))
    for f in files:
        m = re.match(r"시행중_K-IFRS_제(\d+)호", f.name)
        if m:
            slug = f"kifrs_{m.group(1)}"
        else:
            slug = next((s for s, pre in CF_MAP.items()
                         if f.name.startswith(pre)), None)
            if slug is None:
                continue
        data = extract_kifrs(f)
        write_out(outdir, slug, str(f.relative_to(ROOT)),
                  data["paras"], data["footnotes"])
        n_no = sum(1 for p in data["paras"] if p["no"])
        print(f"  {slug}: {len(data['paras'])}행 (번호 {n_no})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", choices=["kifrs", "ksa", "guide"],
                    help="미지정 시 전체")
    args = ap.parse_args()
    if args.group in (None, "kifrs"):
        print("[K-IFRS 63건]")
        extract_kifrs_group(OUT)
    if args.group in (None, "ksa"):
        print("[감사기준 통합본+3건]")
        extract_ksa_group(OUT)
    if args.group in (None, "guide"):
        print("[실무지침]")
        extract_guide_group(OUT)


if __name__ == "__main__":
    main()
