from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import OpenAICompatibleEmbeddingProvider, build_vector_index


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local platform vector index.")
    parser.add_argument("--data", default=str(ROOT / "knowledge" / "platform.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "knowledge" / "platform.index.json"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    )
    parser.add_argument("--model", default="text-embedding-v4")
    parser.add_argument("--dimensions", type=int, default=1024)
    args = parser.parse_args()

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        parser.error("DASHSCOPE_API_KEY is required; do not write the key into this project")
    provider = OpenAICompatibleEmbeddingProvider(
        api_key=api_key,
        base_url=args.base_url,
        model_name=args.model,
        dimensions=args.dimensions,
    )
    payload = build_vector_index(
        documents_path=args.data,
        output_path=args.output,
        embedder=provider,
    )
    print(
        f"built {payload['document_count']} documents with "
        f"{payload['embedding_model']} ({payload['embedding_dimensions']}d)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


