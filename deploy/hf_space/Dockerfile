FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# CPU 전용 torch를 먼저 고정 — 기본 인덱스의 CUDA 빌드(~5GB) 방지
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir fastmcp==3.4.3 qdrant-client==1.18.0 \
       kiwipiepy==0.23.2 "sentence-transformers>=5,<6"

# 서버 코드: 공개 GitHub 저장소에서 — Space에는 Dockerfile·README만 두면 된다.
# 코드가 갱신되면 Space Settings → Factory rebuild로 다시 clone된다.
RUN git clone --depth 1 https://github.com/worldoftoddl/auditPaper_assist.git /app
WORKDIR /app

# HF Spaces는 uid 1000 비루트로 실행한다
RUN useradd -m -u 1000 user
USER user
ENV HF_HOME=/home/user/.cache/huggingface

# bge-m3 가중치를 이미지에 선탑재 — 슬립 후 콜드 스타트 단축 + 빌드 시 로드 검증
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# QDRANT_URL·QDRANT_API_KEY·MCP_AUTH_TOKEN은 Space Secrets로 주입 (런타임 환경변수)
ENV MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=7860
EXPOSE 7860
CMD ["python", "-m", "server.mcp_server"]
