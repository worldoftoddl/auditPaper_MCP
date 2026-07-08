"""기동 검증 (지시서 3장): 메타 컬렉션의 manifest와 실행 환경의 계약 대조 — 불일치면 기동 거부.

검사 순서: ①임베딩 모델 ②sparse 계약 ③토크나이저 ④컬렉션 ⑤용어 사전 ⑥임베딩 프로브.
manifest·vocab·glossary는 로컬 index/ 파일이 아니라 Qdrant 메타 컬렉션에서 읽는다 —
서버는 접속 정보(.env)만으로 기동하며 코퍼스 저장소·index/ 산출물이 필요 없다
(지시서 v1.1 이탈: DB 단일 소스 — server/README.md 기록).
routing_gold.json은 검증 대상도, 로드 대상도 아니다 (채점 전용).
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_index import COLLECTION, META_COLLECTION, load_env, meta_point_id  # noqa: E402

PROBE_TEXT = "수행의무"
PROBE_TOL = 1e-3


class ContractMismatch(Exception):
    """기동 거부 사유. 항목·기대값·실측값·조치 힌트를 담는다."""
    code = "CONTRACT_MISMATCH"

    def __init__(self, item, expected, actual, hint):
        self.item, self.expected, self.actual, self.hint = item, expected, actual, hint
        super().__init__(f"[{self.code}] {item}: 기대 {expected!r} / 실측 {actual!r} — {hint}")


def _check(item, expected, actual, hint):
    if expected != actual:
        raise ContractMismatch(item, expected, actual, hint)


def make_client():
    """.env/환경변수에서 Qdrant 클라이언트 생성 — 서버의 유일한 외부 의존."""
    # .mcp.json의 ${VAR} 확장이 빈 문자열을 넣을 수 있음 — 비우고 .env로 폴백
    for k in ("QDRANT_URL", "QDRANT_API_KEY"):
        if os.environ.get(k) == "":
            del os.environ[k]
    load_env()
    url, key = os.environ.get("QDRANT_URL"), os.environ.get("QDRANT_API_KEY")
    if not url:
        raise ContractMismatch("qdrant.접속", "QDRANT_URL/.env", None,
                               ".env에 QDRANT_URL·QDRANT_API_KEY를 기록하세요")
    from qdrant_client import QdrantClient
    return QdrantClient(url=url, api_key=key, timeout=60)


def load_meta(client):
    """메타 컬렉션 → (manifest, vocab_doc, glossary). glossary는 ord 순(파일 순서 보존)."""
    if not client.collection_exists(META_COLLECTION):
        raise ContractMismatch("meta.collection", META_COLLECTION, None,
                               "적재기(build_index.py --stage upsert)로 메타 컬렉션을 생성하세요")
    got = client.retrieve(META_COLLECTION,
                          ids=[meta_point_id("manifest"), meta_point_id("vocab")],
                          with_payload=True)
    by_kind = {p.payload["kind"]: p.payload for p in got}
    if set(by_kind) != {"manifest", "vocab"}:
        raise ContractMismatch("meta.points", "manifest+vocab", sorted(by_kind),
                               "메타 컬렉션 불완전 — 적재기 재실행")
    manifest = by_kind["manifest"]["data"]
    vocab_doc = {"meta": by_kind["vocab"]["meta"], "tokens": by_kind["vocab"]["tokens"]}
    glossary, offset = [], None
    while True:
        pts, offset = client.scroll(META_COLLECTION, limit=1000, offset=offset, with_payload=True)
        glossary += [p.payload for p in pts if p.payload.get("kind") == "glossary"]
        if offset is None:
            break
    glossary.sort(key=lambda e: e["ord"])
    return manifest, vocab_doc, glossary


def _validate_encoder(manifest, encoder=None, log=print):
    """검사 ①·⑥의 모델 의존부: 인코더 로드(로드 자체가 revision 강제) + 차원 + 프로브."""
    emb = manifest["embedding"]
    if encoder is None:
        log(f"[contracts] 질의측 인코더 로드: {emb['model']} (rev {emb['revision']}, CPU-fp32)")
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(emb["model"], revision=emb["revision"])
    _check("embedding.dim", emb["dim"], encoder.get_sentence_embedding_dimension(),
           "모델 차원 불일치 — manifest.embedding.model과 동일 모델을 로드하세요")
    vec = encoder.encode([PROBE_TEXT], normalize_embeddings=True)[0]
    norm = float((vec ** 2).sum() ** 0.5)
    if abs(norm - 1.0) > PROBE_TOL:
        raise ContractMismatch("embedding.probe_norm", f"1±{PROBE_TOL}", norm,
                               "인코더가 정규화 벡터를 내지 않음 — normalize_embeddings 설정 확인")
    log(f"[contracts] 임베딩 프로브 통과 (L2 노름 {norm:.6f})")
    return encoder


def validate_encoder(manifest, encoder=None, log=print):
    """지연 로드 경로(mcp_server 백그라운드)용 단독 진입점."""
    return _validate_encoder(manifest, encoder, log)


def validate(client=None, encoder=None, log=print, defer_encoder=False, meta=None):
    """계약 6항목 검증. 통과 시 (manifest, vocab_tokens, glossary, client, encoder) 반환.

    client/encoder를 주면 재사용(테스트·경량 기동), 없으면 여기서 생성한다.
    meta=(manifest, vocab_doc, glossary)를 주면 메타 컬렉션 조회를 건너뛴다(테스트용 변조 주입).
    defer_encoder=True면 모델 의존 검사(①차원·⑥프로브)를 뒤로 미루고 encoder=None을
    반환한다 — 호출측은 반드시 validate_encoder()로 나머지 검사를 완결해야 하며,
    실패 시 서빙을 중단해 기동 거부 의미를 보존해야 한다 (mcp_server 참조).
    """
    if client is None:
        client = make_client()
    manifest, vocab_doc, glossary = meta if meta is not None else load_meta(client)
    emb, sp = manifest["embedding"], manifest["sparse"]

    # ① 임베딩 모델 — normalize 계약(모델 비의존부)
    _check("embedding.normalize_embeddings", True, emb["normalize_embeddings"],
           "manifest가 정규화 임베딩이 아님 — 2단계 적재기와 계약 확인")
    # payload 본문 계약 — 서버는 본문을 컬렉션에서 제공하므로 없으면 기동 불가
    _check("payload_document", True, manifest.get("payload_document"),
           "컬렉션 payload에 본문 없음 — 적재기(--stage upsert) 재실행으로 재구축")

    # ② sparse 계약 — 메타 컬렉션 vocab.meta == manifest.sparse (k1·b·avgdl·vocab_size)
    vmeta, vtokens = vocab_doc["meta"], vocab_doc["tokens"]
    for key in ("k1", "b", "avgdl", "vocab_size"):
        _check(f"sparse.{key}", sp[key], vmeta.get(key),
               "메타 컬렉션 vocab이 컬렉션과 다른 판 — 적재기 재실행으로 동일 판 재구축")
    _check("sparse.vocab_size(tokens)", sp["vocab_size"], len(vtokens),
           "vocab tokens 수가 meta와 불일치 — 메타 컬렉션 손상 의심, 적재기 재실행")

    # ③ 토크나이저 — kiwipiepy major.minor 일치 (패치 차이는 경고)
    import kiwipiepy
    exp_v, act_v = sp["kiwipiepy_version"], kiwipiepy.__version__
    _check("sparse.kiwipiepy(major.minor)",
           ".".join(exp_v.split(".")[:2]), ".".join(act_v.split(".")[:2]),
           f"kiwipiepy=={exp_v} 설치 필요 (형태소 분리가 달라지면 sparse 질의가 어긋남)")
    if exp_v != act_v:
        log(f"[contracts] 경고: kiwipiepy 패치 버전 차이 ({exp_v} → {act_v})")

    # ④ 컬렉션 — 존재 + 포인트 수
    _check("collection.exists", True, client.collection_exists(manifest["collection"]),
           f"컬렉션 {manifest['collection']} 없음 — 적재기(build_index.py)로 재구축")
    n = client.count(manifest["collection"], exact=True).count
    _check("collection.points", manifest["points"], n,
           "포인트 수 불일치 — 컬렉션과 manifest의 판이 다름, 적재기 재실행")

    # ⑤ 용어 사전
    if not glossary:
        raise ContractMismatch("glossary", ">0건", 0,
                               "메타 컬렉션에 glossary 없음 — 적재기 재실행")
    log(f"[contracts] 용어 사전 로드: {len(glossary)}건 (메타 컬렉션)")

    # ①(차원)·⑥(임베딩 프로브) — 모델 의존부
    if not defer_encoder:
        encoder = _validate_encoder(manifest, encoder, log)
    elif encoder is not None:
        encoder = _validate_encoder(manifest, encoder, log)

    log(f"[contracts] 계약 검증 {'통과' if not (defer_encoder and encoder is None) else '통과(인코더 검사 유예)'}: "
        f"{manifest['collection']} {n}포인트, vocab {sp['vocab_size']}토큰, glossary {len(glossary)}건")
    return manifest, vtokens, glossary, client, encoder


assert COLLECTION and META_COLLECTION  # build_index와의 상수 연결 유지 (import 시 드리프트 조기 감지)
