# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 저장소 개요

이 저장소는 코드가 아닌 **문서 코퍼스**다. 한국의 회계감사기준(ISA)과 한국채택국제회계기준(K-IFRS) 원문을 DOCX/원본에서 전처리한 마크다운 파일 103개로 구성되며, RAG 파이프라인(벡터 DB 적재·청킹)의 소스 데이터로 사용된다. 빌드/테스트/린트 명령은 없다.

## 디렉토리 구조

- `auditstandard_md/` — 회계감사기준 전문(2025 개정). ISA-200~720, ISQM-1, FRMK-1, ASSR-3000 등 40개 파일. 파일명은 `ISA-<번호>.md` 형식이며 `00_전문.md`는 전체 목차(prelude_and_toc).
- `ifrs_md/` — K-IFRS 기준서. 원 기준서 계열별 하위 폴더로 분류: `IAS_10XX/`(제1001~1041호), `IFRS_11XX/`(제1101~1117호), `IFRIC_21XX/`, `SIC_20XX/`.
- `Conceptual_framework_md/` — 재무보고를 위한 개념체계, 경영진설명서 개념체계, 중요성 실무서 3개 파일.
- `guidelines_md/` — 회계감사실무지침 9건(2014-1~2018-3), `guide_<번호>.md` 형식. `guidelines_raw/`의 원본에서 변환했으며, 유일하게 목표 규약(`guidelines_raw/벡터저장소_스키마_및_마크다운_작성규약.md` 4장)을 그대로 따른다: frontmatter 3필드(`source_type`/`standard_no`/`standard_title`) + 행 머리 `번호.` 문단 + `[각주: …]` 인라인. 변환 결정사항은 `guidelines_md/README.md` 참조.
- `guidelines_raw/` — 실무지침 원본(DOC/DOCX/PDF)과 벡터 저장소 설계 문서. 원본은 전부 변환 완료.

## 문서 스키마 — 두 가지가 서로 다름

두 코퍼스는 서로 다른 YAML frontmatter와 인라인 메타데이터 규약을 쓴다. 파싱/청킹 코드를 작성할 때 반드시 구분해야 한다.

### 감사기준 (`auditstandard_md/`)

```yaml
schema_version: "1.0"
standard_id: "ISA-200"        # 00_전문.md는 null
standard_no: "200"
standard_title: "..."
source_file: "0. 회계감사기준 전문(2025 개정).docx"
```

본문의 각 블록 뒤에 HTML 주석으로 메타데이터가 붙는다:

```
<!-- para: 1. | kind: requirement | idx: 28 -->
<!-- section: intro | idx: 26 -->
<!-- kind: bullet | idx: 36 -->
```

- `para`: 문단번호(요구사항은 `1.`, 적용자료는 `A1` 형식)
- `kind`: `requirement`, `paragraph_body`, `bullet`, `toc_entry` 등
- `idx`: 원본 문서 내 순번
- `section`: `intro` 등 섹션 구분

### K-IFRS / 개념체계 (`ifrs_md/`, `Conceptual_framework_md/`)

```yaml
standard_id: "K-IFRS 1002"    # 개념체계는 "재무보고 개념체계"
standard_number: "1002"
title: "재고자산"
standard_type: "standard"     # framework 등
standard_family: "IAS"        # IFRS, IFRIC, SIC, CF
original_number: "IAS 2"
base_authority: 1             # 개념체계는 3
components: [bc, definitions, main]
has_korean_additions: true
korean_paragraph_count: 2
```

인라인 메타데이터:

```
<!-- component: main | authority: 1 -->   # 섹션(##) 단위 구성요소 표시
<!-- para: 1 -->                          # 문단번호
<!-- para: 한2.1 | bold_para | korean_addition -->
```

- `component`: `main`(본문), `definitions`(용어의 정의), `bc`(결론도출근거)
- `para`: K-IFRS 문단번호. 한국 추가 문단은 `한` 접두사(예: `한2.1`), 개념체계는 `SP1.1` 같은 형식
- `bold_para`: 원문에서 굵은 글씨(의무규정) 문단
- `korean_addition`: 국제기준에 없는 한국 추가 조항

## 작업 시 유의사항

- 이 코퍼스는 별도 프로젝트(IFRS_Agent)의 벡터 DB 재적재용 소스다. 목표 청크 ID 형식은 `KIFRS::<기준서번호>::<문단번호>` (예: `KIFRS::1115::31`).
- 기준서 원문 파일의 내용을 임의로 수정하지 말 것 — 법정 기준서 원문이며 전처리 산출물이다. 변환/청킹은 별도 스크립트나 출력물로 수행한다.
- 파일명에 괄호·한글·특수문자가 포함되므로 셸 명령에서 반드시 따옴표로 감쌀 것.
