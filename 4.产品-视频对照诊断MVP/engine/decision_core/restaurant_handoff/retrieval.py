from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence

from .embeddings import EmbeddingProvider


class RetrievalServiceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class KnowledgeDocument:
    knowledge_id: str
    version: str
    title: str
    content: str
    scope: Literal["platform", "private"]
    stages: tuple[str, ...]
    topics: tuple[str, ...]
    source_url: str
    source_type: str
    review_status: str
    owner_id: str | None = None
    source_locator: str | None = None
    published_at: str | None = None
    evidence_grade: str = "draft"
    applicability: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    reviewed_by: str | None = None

    @property
    def search_text(self) -> str:
        return "\n".join(
            (
                self.title,
                " ".join(self.stages),
                " ".join(self.topics),
                self.content,
                " ".join(self.applicability),
                " ".join(self.limitations),
            )
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowledgeDocument":
        return cls(
            **{
                **value,
                "stages": tuple(value.get("stages", [])),
                "topics": tuple(value.get("topics", [])),
                "applicability": tuple(value.get("applicability", [])),
                "limitations": tuple(value.get("limitations", [])),
            }
        )


@dataclass(frozen=True)
class SearchHit:
    evidence_id: str
    knowledge_id: str
    title: str
    snippet: str
    score: float
    source_url: str
    source_locator: str | None
    published_at: str | None
    review_status: str
    evidence_grade: str
    retrieval_mode: str


def load_documents(path: str | Path) -> list[KnowledgeDocument]:
    source = Path(path)
    if not source.exists():
        raise RetrievalServiceUnavailable(f"knowledge data unavailable: {source}")
    documents: list[KnowledgeDocument] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                document = KnowledgeDocument.from_dict(json.loads(line))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid document at line {line_number}: {exc}") from exc
            if document.scope == "private" and not document.owner_id:
                raise ValueError(f"private document {document.knowledge_id} has no owner_id")
            documents.append(document)
    ids = [document.knowledge_id for document in documents]
    if len(ids) != len(set(ids)):
        raise ValueError("knowledge_id must be unique")
    return documents


def build_vector_index(
    *,
    documents_path: str | Path,
    output_path: str | Path,
    embedder: EmbeddingProvider,
) -> dict[str, Any]:
    documents = load_documents(documents_path)
    vectors = embedder.embed([document.search_text for document in documents])
    if len(vectors) != len(documents):
        raise RuntimeError("embedding count does not match document count")
    knowledge_digest = hashlib.sha256(
        "\n".join(document.search_text for document in documents).encode("utf-8")
    ).hexdigest()
    payload = {
        "schema_version": "2.0",
        "embedding_model": embedder.model_name,
        "embedding_dimensions": embedder.dimensions,
        "document_count": len(documents),
        "knowledge_digest": knowledge_digest,
        "items": [
            {"document": asdict(document), "vector": vector}
            for document, vector in zip(documents, vectors)
        ],
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("embedding dimensions do not match")
    denominator = math.sqrt(sum(item * item for item in left)) * math.sqrt(
        sum(item * item for item in right)
    )
    return 0.0 if denominator == 0 else sum(a * b for a, b in zip(left, right)) / denominator


def _evidence_id(document: KnowledgeDocument) -> str:
    return f"rag:{document.scope}:{document.knowledge_id}:{document.version}"


def _to_hit(document: KnowledgeDocument, score: float, mode: str) -> SearchHit:
    return SearchHit(
        evidence_id=_evidence_id(document),
        knowledge_id=document.knowledge_id,
        title=document.title,
        snippet=document.content[:280],
        score=round(score, 6),
        source_url=document.source_url,
        source_locator=document.source_locator,
        published_at=document.published_at,
        review_status=document.review_status,
        evidence_grade=document.evidence_grade,
        retrieval_mode=mode,
    )


class ScopedVectorRetriever:
    def __init__(self, *, index_path: str | Path, embedder: EmbeddingProvider) -> None:
        source = Path(index_path)
        if not source.exists():
            raise RetrievalServiceUnavailable(f"vector index unavailable: {source}")
        try:
            self.payload = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RetrievalServiceUnavailable(f"invalid vector index: {exc}") from exc
        self.embedder = embedder
        if self.payload.get("embedding_model") != embedder.model_name:
            raise RetrievalServiceUnavailable("embedding model does not match the vector index")
        if self.payload.get("embedding_dimensions") != embedder.dimensions:
            raise RetrievalServiceUnavailable("embedding dimensions do not match the vector index")

    def search(
        self,
        query: str,
        *,
        scope: Literal["platform", "private"],
        user_id: str | None = None,
        top_k: int = 3,
        min_score: float = 0.2,
        stages: Iterable[str] = (),
        minimum_evidence_grade: str = "draft",
    ) -> list[SearchHit]:
        if scope == "private" and not user_id:
            raise PermissionError("user_id is required for private retrieval")
        if not query.strip():
            raise ValueError("query must not be empty")
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        query_vector = self.embedder.embed([query])[0]
        stage_filter = set(stages)
        candidates: list[tuple[float, KnowledgeDocument]] = []
        for item in self.payload.get("items", []):
            document = KnowledgeDocument.from_dict(item["document"])
            if document.scope != scope:
                continue
            if scope == "private" and document.owner_id != user_id:
                continue
            if stage_filter and not stage_filter.intersection(document.stages):
                continue
            if _grade_rank(document.evidence_grade) < _grade_rank(minimum_evidence_grade):
                continue
            score = _cosine(query_vector, item["vector"])
            if score >= min_score:
                candidates.append((score, document))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [_to_hit(document, score, "dense_vector") for score, document in candidates[:top_k]]


def _tokens(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    latin = set(re.findall(r"[a-z0-9]+", normalized))
    chinese = set(normalized[index : index + 2] for index in range(max(0, len(normalized) - 1)))
    return latin | chinese


EVIDENCE_GRADE_RANK = {"draft": 0, "secondary": 1, "reviewed": 2, "golden": 3}


def _grade_rank(value: str) -> int:
    if value not in EVIDENCE_GRADE_RANK:
        raise ValueError(f"unknown evidence grade: {value}")
    return EVIDENCE_GRADE_RANK[value]


class LexicalFallbackRetriever:
    """Explicit degraded mode. Never label these results as semantic retrieval."""

    def __init__(self, documents_path: str | Path) -> None:
        self.documents = load_documents(documents_path)

    def search(
        self,
        query: str,
        *,
        scope: Literal["platform", "private"],
        user_id: str | None = None,
        top_k: int = 3,
        minimum_evidence_grade: str = "draft",
    ) -> list[SearchHit]:
        if scope == "private" and not user_id:
            raise PermissionError("user_id is required for private retrieval")
        query_tokens = _tokens(query)
        candidates: list[tuple[float, KnowledgeDocument]] = []
        for document in self.documents:
            if document.scope != scope:
                continue
            if scope == "private" and document.owner_id != user_id:
                continue
            if _grade_rank(document.evidence_grade) < _grade_rank(minimum_evidence_grade):
                continue
            document_tokens = _tokens(document.search_text)
            overlap = len(query_tokens.intersection(document_tokens))
            score = overlap / max(1, len(query_tokens))
            if score > 0:
                candidates.append((score, document))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [_to_hit(document, score, "lexical_fallback") for score, document in candidates[:top_k]]


