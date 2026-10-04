"""Real SDK smoke test with deterministic vectors, NOT a model quality benchmark.

Run from project root: python scripts/check_lightrag.py
Temporary isolated index; no model/network calls; no upstream files changed.
"""

import asyncio
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc, Tokenizer

from commerceops.retrieval import LightRAGRetriever, load_evidence


class CharacterTokenizer:
    """Test-only tokenizer avoids downloading tiktoken encoding tables."""

    def encode(self, text):
        return [ord(c) for c in text]

    def decode(self, tokens):
        return "".join(chr(c) for c in tokens)


async def deterministic_embedding(texts):
    vectors = np.zeros((len(texts), 128), dtype=np.float32)
    for index, text in enumerate(texts):
        terms = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]{2}", text.lower())
        for term in terms:
            bucket = int.from_bytes(hashlib.sha256(term.encode()).digest()[:4], "big") % 128
            vectors[index, bucket] += 1
        norm = np.linalg.norm(vectors[index])
        if norm:
            vectors[index] /= norm
    return vectors


async def deterministic_keywords(prompt, **kwargs):
    # Replaces only the model, never the SDK retrieval implementation.
    return json.dumps(
        {
            "high_level_keywords": ["优惠", "新客满减"],
            "low_level_keywords": ["新客", "优惠券", "350"],
        },
        ensure_ascii=False,
    )


def build_sdk(directory):
    return LightRAG(
        working_dir=str(directory),
        workspace="commerceops-smoke",
        tokenizer=Tokenizer("test-character", CharacterTokenizer()),
        embedding_func=EmbeddingFunc(
            embedding_dim=128,
            max_token_size=8192,
            model_name="deterministic-test-only",
            func=deterministic_embedding,
        ),
        llm_model_func=deterministic_keywords,
        cosine_better_than_threshold=-1.0,
    )


async def main():
    with tempfile.TemporaryDirectory(prefix="commerceops-lightrag-smoke-") as directory:
        adapter = LightRAGRetriever(load_evidence(), Path(directory), sdk_factory=build_sdk)
        await adapter.initialize()
        try:
            await adapter.ingest(curated_graph=True)
            result = await adapter.rag.aquery_data(
                "新客满350减30优惠券",
                param=QueryParam(
                    mode="mix",
                    top_k=12,
                    chunk_top_k=12,
                    enable_rerank=False,
                    hl_keywords=["优惠", "新客满减"],
                    ll_keywords=["新客", "优惠券", "350"],
                ),
            )
            assert result["status"] == "success", result
            assert result["data"]["entities"], "Real SDK graph returned no entities"
            assert result["data"]["relationships"], "Real SDK graph returned no relationships"
            assert result["data"]["chunks"], "Real SDK returned no evidence chunks"
            evidence = await adapter.search("新客满350减30优惠券", mode="mix")
            assert "R2" in {e.id for e in evidence}, result["data"]["chunks"]
            assert all(e.version == "demo-v3" for e in evidence)
            print(
                json.dumps(
                    {
                        "passed": True,
                        "backend": adapter.backend,
                        "model": "deterministic test doubles; no quality claim",
                        "sdk_mode": result["metadata"]["query_mode"],
                        "entities": len(result["data"]["entities"]),
                        "relationships": len(result["data"]["relationships"]),
                        "chunks": len(result["data"]["chunks"]),
                        "mapped_evidence_ids": [e.id for e in evidence],
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            await adapter.close()


if __name__ == "__main__":
    asyncio.run(main())
