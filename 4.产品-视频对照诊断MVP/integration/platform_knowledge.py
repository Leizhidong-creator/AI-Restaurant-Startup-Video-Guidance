"""平台餐饮专家知识库检索(护城河)——填补后端缺失的 platform_rag。

后端「餐饮专家在线」现在只有"用户自己视频"的私人知识(KnowledgeRetrieverPort),
没有平台专家知识的检索入口。这里用决策内核的检索器,对 platform.jsonl(餐饮专家知识库)
做 scope=platform 检索,产出后端 KnowledgeHit 形状的结果,供连麦/复盘引用(带稳定证据 id)。

- 默认离线词法降级(LexicalFallbackRetriever):无需 embedding/网络,用现有 platform.jsonl 即可跑。
- 生成向量索引后(scripts/build_index.py),传 index_path + embedder 切到语义检索(ScopedVectorRetriever)。

接入后端:后端新增一个 platform_rag 工具,内部调用本类 .search();工具结果里的 hit.id
即报告可引用的证据 id。详见 integration/README.md。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from restaurant_handoff.retrieval import (
    LexicalFallbackRetriever,
    ScopedVectorRetriever,
    SearchHit,
)


@dataclass
class KnowledgeHit:
    """对齐后端 yongge_online.knowledge.schemas.KnowledgeHit(接入时转成其 pydantic 模型)。"""

    id: str
    kind: str
    content: str
    tags: list[str] = field(default_factory=list)
    start_ms: int | None = None
    end_ms: int | None = None
    score: float = 0.0


def _to_hit(hit: SearchHit) -> KnowledgeHit:
    return KnowledgeHit(
        id=hit.evidence_id,                       # 稳定证据 id,报告引用用它
        kind=hit.evidence_grade,                  # golden / reviewed / secondary
        content=f"{hit.title}｜{hit.snippet}",
        tags=[hit.retrieval_mode],                # dense_vector / lexical_fallback
        start_ms=None,
        end_ms=None,
        score=hit.score,
    )


class PlatformKnowledgeRetriever:
    """餐饮专家平台知识库检索。scope 固定 platform;不需要 user_id/store_id。"""

    def __init__(
        self,
        *,
        documents_path: str,
        index_path: str | None = None,
        embedder=None,
        min_evidence_grade: str = "secondary",
    ) -> None:
        self._min_grade = min_evidence_grade
        if index_path and embedder is not None:
            self._retriever = ScopedVectorRetriever(index_path=index_path, embedder=embedder)
            self._mode = "vector"
        else:
            self._retriever = LexicalFallbackRetriever(documents_path)
            self._mode = "lexical_fallback"

    @property
    def mode(self) -> str:
        return self._mode

    def search(self, query: str, *, limit: int = 3, stages: tuple[str, ...] = ()) -> list[KnowledgeHit]:
        if not query or not query.strip():
            return []
        common = dict(scope="platform", top_k=limit, minimum_evidence_grade=self._min_grade)
        if self._mode == "vector":
            hits = self._retriever.search(query, stages=stages, **common)
        else:
            hits = self._retriever.search(query, **common)  # 词法降级不支持 stage 过滤
        return [_to_hit(hit) for hit in hits]


