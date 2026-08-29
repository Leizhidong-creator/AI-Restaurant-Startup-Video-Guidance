import json

import pytest

from yongge_online.db.session import Database
from yongge_online.knowledge.importer import (
    import_platform_file,
    load_platform_documents,
)
from yongge_online.knowledge.platform import (
    DatabasePlatformKnowledgeRetriever,
    PlatformKnowledgeService,
)
from yongge_online.knowledge.schemas import PlatformKnowledgeUpsert


@pytest.mark.asyncio
async def test_platform_knowledge_is_global_reviewed_and_filterable(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'platform.db'}")
    await database.create_schema()
    try:
        async with database.session() as session:
            service = PlatformKnowledgeService(session)
            await service.upsert_many(
                [
                    PlatformKnowledgeUpsert(
                        id="platform-rule-1",
                        source_type="expert_video",
                        source_id="video-1",
                        source_uri="https://example.test/video-1",
                        kind="rule",
                        content="奶茶店选址首先验证门头可见性和目标时段客流。",
                        tags=["选址", "门头"],
                        applicable_categories=["奶茶"],
                        business_stages=["planning"],
                        regions=["武汉"],
                        risk_level="medium",
                        review_status="reviewed",
                    ),
                    PlatformKnowledgeUpsert(
                        id="platform-draft-1",
                        source_type="article",
                        source_id="draft-1",
                        kind="rule",
                        content="未经审核的奶茶选址建议。",
                        applicable_categories=["奶茶"],
                        business_stages=["planning"],
                        regions=["武汉"],
                        risk_level="unknown",
                        review_status="draft",
                    ),
                    PlatformKnowledgeUpsert(
                        id="platform-rule-2",
                        source_type="expert_video",
                        source_id="video-2",
                        kind="rule",
                        content="火锅店需要重点核验排烟和消防条件。",
                        applicable_categories=["火锅"],
                        business_stages=["planning"],
                        regions=["武汉"],
                        risk_level="high",
                        review_status="reviewed",
                    ),
                ]
            )
            await session.commit()

            retriever = DatabasePlatformKnowledgeRetriever(session)
            hits = await retriever.search(
                query="奶茶选址门头",
                limit=5,
                category="奶茶",
                stage="planning",
                region="武汉",
            )

            assert [hit.id for hit in hits] == ["platform-rule-1"]
            assert hits[0].scope == "platform"
            assert hits[0].source_type == "expert_video"
            assert hits[0].source_id == "video-1"
            assert hits[0].review_status == "reviewed"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_platform_knowledge_upsert_preserves_stable_business_id(tmp_path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'upsert.db'}")
    await database.create_schema()
    try:
        async with database.session() as session:
            service = PlatformKnowledgeService(session)
            original = PlatformKnowledgeUpsert(
                id="platform-case-1",
                source_type="expert_video",
                source_id="video-9",
                kind="case",
                content="原始案例内容",
                review_status="reviewed",
            )
            await service.upsert_many([original])
            await service.upsert_many(
                [original.model_copy(update={"content": "复核后的案例内容"})]
            )
            await session.commit()

            items = await service.list_all()
            assert len(items) == 1
            assert items[0].id == "platform-case-1"
            assert items[0].content == "复核后的案例内容"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_imports_decision_core_jsonl_with_versioned_evidence_id(tmp_path) -> None:
    source = tmp_path / "platform.jsonl"
    source.write_text(
        json.dumps(
            {
                "knowledge_id": "method-site-001",
                "version": "2.0",
                "title": "选址先核验目标时段",
                "content": "签约前必须核验目标时段客流和门头可见性。",
                "scope": "platform",
                "stages": ["planned_opening", "site_selection"],
                "topics": ["选址", "客流"],
                "source_url": "https://example.test/source",
                "source_type": "expert-video",
                "review_status": "internal_reviewed_2026-07-21",
                "source_locator": "video:1200-8600",
                "published_at": "2026-07-01",
                "evidence_grade": "reviewed",
                "applicability": ["奶茶店筹备"],
                "limitations": ["不能代替实际客流统计"],
                "reviewed_by": "project-review",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    entries = load_platform_documents(source)

    assert len(entries) == 1
    assert entries[0].id == "rag:platform:method-site-001:2.0"
    assert entries[0].knowledge_id == "method-site-001"
    assert entries[0].version == "2.0"
    assert entries[0].evidence_grade == "reviewed"
    assert entries[0].business_stages == ["planned_opening", "site_selection"]

    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'import.db'}")
    await database.create_schema()
    try:
        async with database.session() as session:
            await PlatformKnowledgeService(session).upsert_many(entries)
            await session.commit()
            hits = await DatabasePlatformKnowledgeRetriever(session).search(
                query="选址客流门头",
                limit=3,
                stage="planned_opening",
            )
            assert [hit.id for hit in hits] == [
                "rag:platform:method-site-001:2.0"
            ]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_import_platform_file_creates_schema_and_persists_entries(tmp_path) -> None:
    source = tmp_path / "one.jsonl"
    source.write_text(
        json.dumps(
            {
                "knowledge_id": "case-1",
                "version": "1.0",
                "title": "真实案例",
                "content": "真实、可追溯的案例内容。",
                "scope": "platform",
                "stages": [],
                "topics": ["案例"],
                "source_url": "https://example.test/case-1",
                "source_type": "expert-video",
                "review_status": "reviewed",
                "evidence_grade": "reviewed",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'command.db'}"

    imported = await import_platform_file(database_url, source)

    assert imported == 1
    database = Database(database_url)
    try:
        async with database.session() as session:
            items = await PlatformKnowledgeService(session).list_all()
            assert [item.id for item in items] == ["rag:platform:case-1:1.0"]
    finally:
        await database.dispose()


