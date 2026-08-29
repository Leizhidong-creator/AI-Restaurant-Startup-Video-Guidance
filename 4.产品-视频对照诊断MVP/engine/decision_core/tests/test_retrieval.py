from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    LexicalFallbackRetriever,
    RetrievalServiceUnavailable,
    ScopedVectorRetriever,
    build_vector_index,
)


class FakeEmbedder:
    model_name = "fake-test-embedding"
    dimensions = 2

    def embed(self, texts):
        vectors = []
        for text in texts:
            vectors.append([1.0, 0.0] if any(word in text for word in ("面馆", "选址", "场馆")) else [0.0, 1.0])
        return vectors


class RetrievalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.documents_path = self.root / "documents.jsonl"
        rows = [
            {
                "knowledge_id": "platform-site-1",
                "version": "1.0",
                "title": "场馆面馆选址",
                "content": "场馆人流不一定是吃面客流",
                "scope": "platform",
                "stages": ["site_selection"],
                "topics": ["选址"],
                "source_url": "https://example.com/platform",
                "source_type": "test",
                "review_status": "reviewed",
                "evidence_grade": "reviewed",
                "owner_id": None,
            },
            {
                "knowledge_id": "platform-site-secondary",
                "version": "1.0",
                "title": "场馆面馆二手摘要",
                "content": "尚未独立复核",
                "scope": "platform",
                "stages": ["site_selection"],
                "topics": ["选址"],
                "source_url": "https://example.com/secondary",
                "source_type": "test",
                "review_status": "secondary",
                "evidence_grade": "secondary",
                "owner_id": None,
            },
            {
                "knowledge_id": "private-a",
                "version": "1.0",
                "title": "A用户麻辣烫历史",
                "content": "日销六百",
                "scope": "private",
                "stages": ["operating_loss"],
                "topics": ["麻辣烫"],
                "source_url": "private://video-a",
                "source_type": "user-upload",
                "review_status": "user-confirmed",
                "evidence_grade": "reviewed",
                "owner_id": "user-a",
            },
            {
                "knowledge_id": "private-b",
                "version": "1.0",
                "title": "B用户烧烤历史",
                "content": "日销五千",
                "scope": "private",
                "stages": ["operating_loss"],
                "topics": ["烧烤"],
                "source_url": "private://video-b",
                "source_type": "user-upload",
                "review_status": "user-confirmed",
                "evidence_grade": "reviewed",
                "owner_id": "user-b",
            },
        ]
        self.documents_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )
        self.index_path = self.root / "index.json"
        build_vector_index(
            documents_path=self.documents_path,
            output_path=self.index_path,
            embedder=FakeEmbedder(),
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_platform_vector_hit_has_stable_evidence_id(self) -> None:
        retriever = ScopedVectorRetriever(index_path=self.index_path, embedder=FakeEmbedder())
        hits = retriever.search("体育场馆里开面馆", scope="platform", min_score=0.5)
        self.assertEqual(hits[0].knowledge_id, "platform-site-1")
        self.assertEqual(hits[0].evidence_id, "rag:platform:platform-site-1:1.0")
        self.assertEqual(hits[0].retrieval_mode, "dense_vector")

    def test_evidence_grade_filter_excludes_secondary(self) -> None:
        retriever = ScopedVectorRetriever(index_path=self.index_path, embedder=FakeEmbedder())
        hits = retriever.search(
            "体育场馆里开面馆",
            scope="platform",
            min_score=0.5,
            top_k=10,
            minimum_evidence_grade="reviewed",
        )
        self.assertEqual({hit.knowledge_id for hit in hits}, {"platform-site-1"})

    def test_private_vector_search_is_owner_scoped(self) -> None:
        retriever = ScopedVectorRetriever(index_path=self.index_path, embedder=FakeEmbedder())
        hits = retriever.search("烧烤历史", scope="private", user_id="user-a", min_score=0.0, top_k=10)
        self.assertEqual({hit.knowledge_id for hit in hits}, {"private-a"})

    def test_successful_search_can_return_no_hit(self) -> None:
        retriever = ScopedVectorRetriever(index_path=self.index_path, embedder=FakeEmbedder())
        hits = retriever.search("烧烤流水", scope="platform", min_score=0.5)
        self.assertEqual(hits, [])

    def test_private_search_requires_user_id(self) -> None:
        retriever = ScopedVectorRetriever(index_path=self.index_path, embedder=FakeEmbedder())
        with self.assertRaises(PermissionError):
            retriever.search("历史", scope="private")

    def test_missing_index_is_unavailable_not_empty(self) -> None:
        with self.assertRaises(RetrievalServiceUnavailable):
            ScopedVectorRetriever(index_path=self.root / "missing.json", embedder=FakeEmbedder())

    def test_index_rejects_different_embedding_model(self) -> None:
        class OtherEmbedder(FakeEmbedder):
            model_name = "different"

        with self.assertRaises(RetrievalServiceUnavailable):
            ScopedVectorRetriever(index_path=self.index_path, embedder=OtherEmbedder())

    def test_lexical_fallback_is_explicitly_labeled(self) -> None:
        retriever = LexicalFallbackRetriever(self.documents_path)
        hits = retriever.search("场馆面馆选址", scope="platform")
        self.assertEqual(hits[0].retrieval_mode, "lexical_fallback")


if __name__ == "__main__":
    unittest.main()


