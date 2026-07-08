# auditPaper_assist — 감사조서 콜드 해석 파이프라인

**어떤 조서든 던지면 에이전트가 읽고 근거 규정과 할 일을 뽑아낸다 — 자유로운 해석, 검증 가능한 인용.**
한국 회계감사기준(ISA)·K-IFRS·실무지침 전문을 벡터 DB로 적재하고, MCP 도구 3종을 든 에이전트가
처음 보는 감사조서를 해석해 수행 절차와 근거 문단(cid)을 산출한다. 인용된 모든 규정은 복합 ID로
실물 대조가 가능하다.

## 데모 장면

실제 산출물: [`reports/해석_2100.md`](reports/해석_2100.md) — 위험평가 국면 21개 시트 서식철의
콜드 해석(할 일 38건, 규정 인용 90회, 라우팅 recall 1.0).

```
사용자   : reports/감사조서서식_2100-2700 위험평가 2025.xlsx 해석해줘
에이전트 : (21개 시트 전수 열람) → 가설: 위험평가 국면의 표준 감사조서 서식철
에이전트 : standards_search("산업적·규제적 요인 이해", standard_no="315") → KSA::315::A69 …
에이전트 : standards_get_paragraph("KSA::250::17")  ← 제출 전 인용 cid 실물 재대조
산출     : reports/해석_2100.md (①정체 ②할 일 ③근거 발췌 ④미확인) → 채점기 recall 1.0
```

## 아키텍처 — 3층

```
[1층 · 데이터]   원문 DOCX/PDF/md (auditstandard_md·ifrs_md·Conceptual_framework_md·guidelines_raw)
                   │ scripts/normalize_corpus.py          (규약 4장 형식 통일, 상설 구조 검증)
                   ▼
                 corpus_md/ 102파일 + guidelines_md/ 9파일 = 111파일 · 10,063문단
                   │ scripts/build_index.py + Colab GPU    (bge-m3 dense + kiwipiepy/BM25 sparse)
                   ▼
                 Qdrant Cloud: standards_20250829_bgem3 (payload에 본문 포함)
                              + *_meta (manifest·vocab·용어사전 664) — DB 단일 소스

[2층 · 도구]     server/ MCP 서버 (FastMCP stdio, .env만으로 기동)
                 standards_search(하이브리드 RRF + 정의 주입) · standards_get_paragraph(직조회·
                 분할 재조립·문맥 확장) · standards_define_terms(용어 사전 3단계 매칭)

[3층 · 에이전트] Claude Code + CLAUDE.md '조서 해석 플로우'
                 조서 전수 열람 → 정체 가설 → 근거 탐색(MCP) → 보고서 산출 → 골드셋 채점
```

**숫자 한 줄**: 원문 111파일 → 10,063포인트 · 검증 4겹(변환 상설 검증 → 적재 점검 1~7·스모크
S1~S9 왕복+본문 전수 → 기동 계약 검증 → 인수 테스트 A1~A10) · 콜드 해석 recall 실측
1.0/1.0/1.0/0.25 (조서 2100·3600A·8100·4000P-1, `eval/score_*.json`).

## 저장소 지도

| 폴더 | 내용 |
|---|---|
| `corpus_md/` | 규약 형식 통일 코퍼스 — 감사기준 39 + 회계기준 63 (적재 대상 ①) |
| `guidelines_md/` | 회계감사실무지침 9건 — 수작업 변환 원본(source of truth) (적재 대상 ②) |
| `auditstandard_md/` `ifrs_md/` `Conceptual_framework_md/` | 변환 전 원문 md (옛 스키마) |
| `guidelines_raw/` | 실무지침 원본(DOC/DOCX/PDF) |
| `scripts/` | `normalize_corpus.py`(변환기) · `build_index.py`(적재기) |
| `index/` | 적재 산출물(vocab·glossary·manifest) — 재구축·감사용 기록 |
| `server/` | MCP 서버 3종 도구 (배선: 루트 `.mcp.json`) |
| `tests/` | 인수 테스트 A1~A10 (실 Qdrant 대상) |
| `eval/` | 채점 전용 골드셋 + recall 채점기 + 채점 결과 |
| `reports/` | 조서 해석 보고서 (`해석_{조서번호}.md`) |
| `docs/` | 규약 정본 · 지시서 아카이브(`workorders/`) · 결함·이탈 대장(`LEDGER.md`) |

## 재현 방법

1. **재구축** — `.venv/bin/python scripts/normalize_corpus.py`(코퍼스 재생성, 바이트 결정적) →
   `.venv/bin/python scripts/build_index.py`(적재. dense는 `embedding.ipynb`로 Colab GPU 이관 가능 —
   `index/README.md`). 접속 정보는 `.env`의 `QDRANT_URL`/`QDRANT_API_KEY`(커밋 금지).
2. **기동** — `.venv/bin/python -m server.mcp_server` 또는 Claude Code가 `.mcp.json`으로 자동 기동.
   검증: `.venv/bin/pytest tests/test_acceptance.py -v`.
3. **데모** — 조서 파일(xlsx/docx)을 `reports/`에 두고 "해석해줘" →
   `CLAUDE.md` 플로우로 `reports/해석_{조서번호}.md` 산출 →
   `.venv/bin/python eval/score_interpretation.py reports/해석_{조서번호}.md {조서번호}`.

설계 규약: [`docs/규약_벡터저장소_스키마.md`](docs/규약_벡터저장소_스키마.md) ·
지시서: [`docs/workorders/`](docs/workorders/) ·
결함·이탈 전수 기록: [`docs/LEDGER.md`](docs/LEDGER.md)
