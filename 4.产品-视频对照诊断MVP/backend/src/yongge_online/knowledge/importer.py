import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from yongge_online.db.session import Database
from yongge_online.knowledge.platform import PlatformKnowledgeService
from yongge_online.knowledge.schemas import PlatformKnowledgeUpsert


def load_platform_documents(path: str | Path) -> list[PlatformKnowledgeUpsert]:
    source = Path(path)
    entries: list[PlatformKnowledgeUpsert] = []
    seen_ids: set[str] = set()
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                document: dict[str, Any] = json.loads(line)
                if document.get("scope") != "platform":
                    raise ValueError("scope must be platform")
                knowledge_id = str(document["knowledge_id"])
                version = str(document["version"])
                evidence_id = f"rag:platform:{knowledge_id}:{version}"
                if evidence_id in seen_ids:
                    raise ValueError(f"duplicate evidence ID: {evidence_id}")
                seen_ids.add(evidence_id)
                entries.append(
                    PlatformKnowledgeUpsert(
                        id=evidence_id,
                        knowledge_id=knowledge_id,
                        version=version,
                        title=document.get("title"),
                        source_type=str(document["source_type"]),
                        source_id=str(
                            document.get("source_locator") or knowledge_id
                        ),
                        source_uri=document.get("source_url"),
                        source_locator=document.get("source_locator"),
                        published_at=document.get("published_at"),
                        kind=str(document.get("kind") or "knowledge"),
                        content=str(document["content"]),
                        tags=[str(item) for item in document.get("topics", [])],
                        applicable_categories=[
                            str(item) for item in document.get("categories", [])
                        ],
                        business_stages=[
                            str(item) for item in document.get("stages", [])
                        ],
                        regions=[str(item) for item in document.get("regions", [])],
                        applicability=[
                            str(item) for item in document.get("applicability", [])
                        ],
                        limitations=[
                            str(item) for item in document.get("limitations", [])
                        ],
                        risk_level=str(document.get("risk_level") or "unknown"),
                        review_status=str(document.get("review_status") or "draft"),
                        evidence_grade=str(document.get("evidence_grade") or "draft"),
                        reviewed_by=document.get("reviewed_by"),
                    )
                )
            except (KeyError, TypeError, json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"invalid platform knowledge at line {line_number}: {exc}"
                ) from exc
    return entries


async def import_platform_file(database_url: str, path: str | Path) -> int:
    entries = load_platform_documents(path)
    database = Database(database_url)
    await database.create_schema()
    try:
        async with database.session() as session:
            await PlatformKnowledgeService(session).upsert_many(entries)
            await session.commit()
    finally:
        await database.dispose()
    return len(entries)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import decision_core platform.jsonl into the backend knowledge store."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--database-url", required=True)
    arguments = parser.parse_args()
    count = asyncio.run(import_platform_file(arguments.database_url, arguments.input))
    print(f"imported {count} platform knowledge entries")


