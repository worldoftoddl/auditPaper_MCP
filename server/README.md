# server/ — 콜드 해석 데모의 MCP 서버 (3단계)

지시서 `MCP/3단계_지시서_v1.1_콜드해석_MCP.md`의 산출물. Qdrant Cloud
`standards_20250829_bgem3`(10,063포인트)를 지식 도구로 노출하는 FastMCP stdio 서버다.

- `core.py` — Gateway(도구 3종 구현)·정책·정의 주입. MCP 비의존 (원격 전송 어댑터 교체 대비)
- `contracts.py` — 기동 검증 6항목. `index/manifest.json`과 실행 환경이 불일치하면 기동 거부
- `mcp_server.py` — FastMCP 도구 3종 + 오류 봉투. `python -m server.mcp_server`

배선: 루트 `.mcp.json` (접속 실값은 `.env` — 커밋 금지). 인수 테스트:
`.venv/bin/pytest tests/test_acceptance.py -v` (A1~A10, 실 Qdrant 대상 ~30초).

## v1.1 전환 사유 (완료 기준 ⑥)

v1의 `standards_worksheet_map` 런타임 도구(조서번호 → 기준서 사전 라우팅 표)는 폐기했다.
사전 라우팅 표가 런타임에 개입하면 "에이전트가 처음 보는 조서를 스스로 해석했다"는 데모
서사가 성립하지 않기 때문이다. 라우팅 표는 `eval/routing_gold.json`(채점 전용 골드셋)으로
승격됐고, 코드 전체에서 이 파일을 참조하는 곳은 `eval/score_interpretation.py`(채점기)뿐이다
— 서버·에이전트 런타임은 로드하지 않는다. **사전 라우팅 → 콜드 해석 + 채점표.**

## 구현 확정·이탈 기록

1. **본문 텍스트는 로컬 파스에서**: 2단계 payload에는 본문이 없다(적재기 `upsert_all` 참조).
   서버는 기동 시 `build_index.prepare()`로 코퍼스를 파싱해 cid→본문을 메모리에 보유하고,
   Qdrant는 랭킹·필터·실물 존재 증명(UUID5 retrieve)을 담당한다. 로컬 파스와 컬렉션의
   동일성은 2단계 S9(전수 왕복) + 기동 검증(포인트 수) + prepare() 내부 총계 assert가 보증.
2. **get_paragraph의 분할 폴백 경로**: 논리 ID `KSA::240::부록1`은 UUID5 직조회가 실패
   (물리 ID는 `#1`/`#2`)하므로 지시서의 payload 등가 조회(source_type+standard_no+para_no)로
   두 조각을 찾아 part_no 순 재조립한다 — 별도 분기 없이 지시서의 폴백이 분할을 흡수.
3. **정의 주입의 대표 선정 구체화** (지시서 5.2 "충돌 시 문맥 기준서 자체 정의 → 정의 보유
   기준서"): 명시 필터 문맥은 그대로 최우선. 문맥이 '결과 최빈'에서 온 약한 신호일 때는
   전용 정의 조각(`::정의-` — 부록A 용어집 원전)을 산문 발췌보다 우선한다. 실측 근거:
   "전문가적 의구심의 정의" 질의의 결과 최빈은 ASSR-3000이라 산문 발췌(ASSR-3000::12)가
   뽑혔는데, 정의 원전으로는 1200 용어집·200::13이 정확하다 (A1).
4. **질의 일치 용어는 동일 cid가 results에 있어도 주입** (지시서의 '동일 cid 생략' 규칙은
   결과 파생(빈도순) 용어에만 적용): 사용자가 명시적으로 물은 용어의 정의를 생략하면
   A5(결과와 주입 동시 요구)와 모순되기 때문. 생략 규칙의 취지(중복 노이즈 억제)는 결과
   파생 용어에서 유지된다.
5. **define_terms 매칭 3단계** (지시서는 2단계: 정확 → 공백 제거): 사전 표제가 수식어를
   동반하는 실측('지배력'의 표제는 '피투자자에 대한 지배력', IFRS 10 원문 표제) 때문에
   포함 일치 폴백을 추가했다. 어절 일치(표제의 공백 분리 어절과 정확 일치)를 합성어 부분
   문자열('공동지배력')보다 우선하고, 매칭된 표제는 출력의 `matched` 필드로 노출한다 (A8).
6. **A7 테스트 조정**: 지시서 원문은 자유 검색("중요성 판단 개념체계 참조", standard_no=PS2)
   상위에서 참조 문단을 기대하지만, 실측상 이 질의로는 top20에 참조 문단이 미도달('판단'이
   PS2 본문을 강하게 끌어당김). 가드 검증의 취지를 살려 `para_type="참조"` 필터를 병용해
   note 부착을 결정적으로 검증한다. 자유 검색 유기 히트("중요성 개념체계 발췌" top8에서
   참조2·3 부상 + note 부착)도 실측으로 확인했다.
7. **A9 검증 방식**: 실제 서버 프로세스 기동 대신 기동 경로의 단위인 `contracts.validate()`를
   변조 사본(k1=9.9)으로 직접 호출해 `CONTRACT_MISMATCH` 거부를 확인한다 — 서버 main은
   이 함수의 예외로만 기동 여부를 결정하므로 등가.
8. **para_type='부록' 명시 필터는 옵트아웃보다 우선**: include_examples=false와
   para_type='부록'이 동시에 오면 모순 — 명시 요청을 우선하고 applied.notes에 기록한다.
9. **오류 봉투에도 collection 포함**: 지시서 4장은 "모든 도구 출력 최상위에 collection"이라
   했으므로 오류 응답에도 일관 적용했다.

## 도구 요약

| 도구 | 역할 | 핵심 규칙 |
|---|---|---|
| `standards_get_paragraph` | cid 직조회·인용 검증 | `#` 조각 ID 거부, 분할 재조립, context 0~3 이웃 |
| `standards_search` | 하이브리드(RRF) + 정의 주입 | 부록 기본 제외(`examples_excluded` 집계), 참조 가드 note, oov 토큰 기록 |
| `standards_define_terms` | 용어 사전 직조회 | 3단계 매칭, context_standard 우선 대표 + alternates |

기동 순서: contracts(모델·sparse·토크나이저·컬렉션·glossary·프로브) → 코퍼스 로컬 파스
→ Gateway → stdio. 전 도구 애노테이션 readOnly/idempotent, 오류 봉투 4코드
(NOT_FOUND · INVALID_INPUT · CONTRACT_MISMATCH · UPSTREAM_UNAVAILABLE) + 행동 힌트.
