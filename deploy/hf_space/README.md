---
title: auditpaper-standards MCP
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# auditpaper-standards MCP 서버

한국 회계감사기준(KSA)·K-IFRS·회계감사실무지침을 검색·조회하는 읽기 전용 MCP 서버.
코드·데이터 구조는 [GitHub 저장소](https://github.com/worldoftoddl/auditPaper_MCP) 참조.

이 Space는 위 저장소를 빌드 시 clone해 FastMCP HTTP 서버로 실행한다.
엔드포인트는 `https://<이-Space-URL>/mcp`이며, 모든 요청에
`Authorization: Bearer <MCP_AUTH_TOKEN>` 헤더가 필요하다 (없으면 401).

## Space 운영자 설정 (Settings → Variables and secrets)

| Secret | 값 |
|---|---|
| `QDRANT_URL` | Qdrant Cloud 클러스터 URL |
| `QDRANT_API_KEY` | Qdrant API 키 |
| `MCP_AUTH_TOKEN` | 접속 비밀번호 (16자 이상 — 미설정 시 서버가 기동 거부) |
| `HF_TOKEN` | (선택) HF Access Token(Read) — 빌드 시 모델 다운로드 속도 제한 회피 |

- Space는 **Public**이어야 한다 (Private Space는 HF 자체 인증 헤더를 요구해
  MCP 클라이언트의 Bearer 토큰과 충돌). 접근 통제는 `MCP_AUTH_TOKEN`이 담당한다.
- GitHub 저장소의 서버 코드가 갱신되면 **Settings → Factory rebuild**로 재배포.

## 클라이언트 연결 (.mcp.json)

```json
{
  "mcpServers": {
    "auditpaper-standards": {
      "type": "http",
      "url": "https://<계정>-<space이름>.hf.space/mcp",
      "headers": { "Authorization": "Bearer <MCP_AUTH_TOKEN>" }
    }
  }
}
```

도구 스키마·캐시 규칙 등 소비자 안내는 저장소의
[`docs/사용안내_원격MCP.md`](https://github.com/worldoftoddl/auditPaper_MCP/blob/main/docs/%EC%82%AC%EC%9A%A9%EC%95%88%EB%82%B4_%EC%9B%90%EA%B2%A9MCP.md) 참조.
