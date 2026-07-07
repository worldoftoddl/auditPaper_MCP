"""기동 검증 (지시서 3장): manifest와 실행 환경의 계약 대조 — 불일치면 기동 거부.

검사 순서: ①임베딩 모델 ②sparse 계약 ③토크나이저 ④컬렉션 ⑤용어 사전 ⑥임베딩 프로브.
routing_gold.json은 검증 대상도, 로드 대상도 아니다 (채점 전용).
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "index"
sys.path.insert(0, str(ROOT / "scripts"))
from build_index import COLLECTION, load_env  # noqa: E402

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


def validate_encoder(index_dir=INDEX_DIR, encoder=None, log=print):
    """지연 로드 경로(mcp_server 백그라운드)용 단독 진입점."""
    manifest = json.loads((Path(index_dir) / "manifest.json").read_text(encoding="utf-8"))
    return _validate_encoder(manifest, encoder, log)


def validate(index_dir=INDEX_DIR, client=None, encoder=None, log=print, defer_encoder=False):
    """계약 6항목 검증. 통과 시 (manifest, vocab_tokens, glossary, client, encoder) 반환.

    client/encoder를 주면 재사용(테스트·경량 기동), 없으면 여기서 생성한다.
    defer_encoder=True면 모델 의존 검사(①차원·⑥프로브)를 뒤로 미루고 encoder=None을
    반환한다 — 호출측은 반드시 validate_encoder()로 나머지 검사를 완결해야 하며,
    실패 시 서빙을 중단해 기동 거부 의미를 보존해야 한다 (mcp_server 참조).
    """
    index_dir = Path(index_dir)
    manifest = json.loads((index_dir / "manifest.json").read_text(encoding="utf-8"))
    emb, sp = manifest["embedding"], manifest["sparse"]

    # ① 임베딩 모델 — normalize 계약(모델 비의존부)
    _check("embedding.normalize_embeddings", True, emb["normalize_embeddings"],
           "manifest가 정규화 임베딩이 아님 — 2단계 적재기와 계약 확인")

    # ② sparse 계약 — vocab.json meta == manifest.sparse (k1·b·avgdl·vocab_size)
    vocab_doc = json.loads((index_dir / "vocab.json").read_text(encoding="utf-8"))
    vmeta, vtokens = vocab_doc["meta"], vocab_doc["tokens"]
    for key in ("k1", "b", "avgdl", "vocab_size"):
        _check(f"sparse.{key}", sp[key], vmeta.get(key),
               "vocab.json이 컬렉션과 다른 판 — index/ 산출물을 manifest와 같은 커밋으로 복원")
    _check("sparse.vocab_size(tokens)", sp["vocab_size"], len(vtokens),
           "vocab.json tokens 수가 meta와 불일치 — 파일 손상 의심, 재생성 필요")

    # ③ 토크나이저 — kiwipiepy major.minor 일치 (패치 차이는 경고)
    import kiwipiepy
    exp_v, act_v = sp["kiwipiepy_version"], kiwipiepy.__version__
    _check("sparse.kiwipiepy(major.minor)",
           ".".join(exp_v.split(".")[:2]), ".".join(act_v.split(".")[:2]),
           f"kiwipiepy=={exp_v} 설치 필요 (형태소 분리가 달라지면 sparse 질의가 어긋남)")
    if exp_v != act_v:
        log(f"[contracts] 경고: kiwipiepy 패치 버전 차이 ({exp_v} → {act_v})")

    # ④ 컬렉션 — 존재 + 포인트 수
    if client is None:
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
        client = QdrantClient(url=url, api_key=key, timeout=60)
    _check("collection.exists", True, client.collection_exists(manifest["collection"]),
           f"컬렉션 {manifest['collection']} 없음 — 적재기(build_index.py)로 재구축")
    n = client.count(manifest["collection"], exact=True).count
    _check("collection.points", manifest["points"], n,
           "포인트 수 불일치 — 컬렉션과 manifest의 판이 다름, 적재기 재실행")

    # ⑤ 용어 사전 로드
    gpath = index_dir / "glossary.jsonl"
    if not gpath.exists():
        raise ContractMismatch("glossary", "index/glossary.jsonl", None,
                               "적재기 --stage offline으로 재생성")
    glossary = [json.loads(l) for l in gpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not glossary:
        raise ContractMismatch("glossary", ">0건", 0, "glossary.jsonl이 비어 있음 — 재생성 필요")
    log(f"[contracts] 용어 사전 로드: {len(glossary)}건")

    # ①(차원)·⑥(임베딩 프로브) — 모델 의존부
    if not defer_encoder:
        encoder = _validate_encoder(manifest, encoder, log)
    elif encoder is not None:
        encoder = _validate_encoder(manifest, encoder, log)

    log(f"[contracts] 계약 검증 {'통과' if not (defer_encoder and encoder is None) else '통과(인코더 검사 유예)'}: "
        f"{manifest['collection']} {n}포인트, vocab {sp['vocab_size']}토큰, glossary {len(glossary)}건")
    return manifest, vtokens, glossary, client, encoder


assert COLLECTION  # build_index와의 상수 연결 유지 (import 시 드리프트 조기 감지)
