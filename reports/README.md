# reports/ — 조서 해석 보고서

- 파일명: `해석_{조서번호}.md` — 조서번호는 채점 파일 `eval/score_{조서번호}.json`과 같은 슬러그(2100·3600A·4000P-1·8100 …). 조서 원본(xlsx/docx)은 이 폴더에 미추적으로 둔다.
- 생성: `CLAUDE.md`의 "조서 해석 플로우"대로 에이전트가 산출 — 형식은 ①정체 ②할 일 목록 ③근거 규정 발췌 ④미확인·불확실 사항, 모든 규정 주장에 cid.
- 채점: `.venv/bin/python eval/score_interpretation.py reports/해석_{조서번호}.md {조서번호}`.
