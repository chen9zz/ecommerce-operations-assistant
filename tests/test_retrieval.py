import asyncio
import importlib.util

import pytest


def module():
    assert importlib.util.find_spec("commerceops.retrieval"), "Retrieval module is not implemented"
    from commerceops import retrieval

    return retrieval


def test_chinese_retrieval_ranks_specific_clause_and_rejects_unrelated():
    r = module()
    evidence = r.load_evidence()
    retriever = r.LexicalRetriever(evidence)
    assert retriever.backend == "lexical-demo"
    assert asyncio.run(retriever.search("清仓商品参加户外九折吗"))[0].id == "R1"
    assert asyncio.run(retriever.search("新客满350减30优惠券"))[0].id == "R2"
    assert asyncio.run(retriever.search("退货退款怎么办"))[0].id == "R5"
    assert asyncio.run(retriever.search("运费包邮规则"))[0].id == "R6"
    assert asyncio.run(retriever.search("量子纠缠与黑洞辐射")) == []
    assert asyncio.run(retriever.search("  ")) == []
    assert len(asyncio.run(retriever.search("优惠活动", limit=1))) == 1


def test_snapshot_and_knowledge_are_explicit():
    r = module()
    evidence = r.load_evidence()
    assert {e.id for e in evidence} == {"R1", "R2", "R3", "R4", "R5", "R6"}
    assert all(e.version == "demo-v3" and "模拟" in e.content for e in evidence)
    assert all(e.source.startswith("commerceops/data/knowledge/demo-v3/") for e in evidence)
    with pytest.raises(ValueError):
        r.load_evidence("../../foreign")


def sdk_result(chunks):
    return {
        "status": "success",
        "message": "Query executed successfully",
        "data": {
            "entities": [],
            "relationships": [],
            "chunks": chunks,
            "references": [
                {"reference_id": str(i + 1), "file_path": c["file_path"]}
                for i, c in enumerate(chunks)
            ],
        },
        "metadata": {
            "query_mode": "mix",
            "keywords": {"high_level": ["优惠"], "low_level": ["新客"]},
            "processing_info": {
                "total_entities_found": 0,
                "total_relations_found": 0,
                "entities_after_truncation": 0,
                "relations_after_truncation": 0,
                "merged_chunks_count": len(chunks),
                "final_chunks_count": len(chunks),
            },
        },
    }


class SDKDouble:
    def __init__(self, result):
        self.result = result
        self.ingests = 0
        self.closed = False
        self.doc_status = self
        self.documents = {}

    async def initialize_storages(self):
        pass

    async def finalize_storages(self):
        self.closed = True

    async def ainsert(self, input, ids, file_paths):
        self.ingests += 1
        assert len(input) == len(ids) == len(file_paths) == 6
        assert file_paths == [f"commerceops-demo-shop-demo-v3-R{i}.md" for i in range(1, 7)]
        from dataclasses import asdict

        from lightrag.base import DocProcessingStatus, DocStatus

        for text, doc_id, file_path in zip(input, ids, file_paths):
            self.documents[doc_id] = asdict(
                DocProcessingStatus(
                    content_summary=text[:100],
                    content_length=len(text),
                    file_path=file_path,
                    status=DocStatus.PROCESSED,
                    created_at="2026-10-01T00:00:00+08:00",
                    updated_at="2026-10-01T00:00:00+08:00",
                    chunks_count=1,
                    chunks_list=["test-chunk"],
                )
            )

    async def get_by_ids(self, ids):
        return [self.documents.get(doc_id) for doc_id in ids]

    async def aquery_data(self, query, param):
        assert param.mode == "mix" and param.enable_rerank is False
        return self.result


def test_adapter_maps_only_exact_approved_evidence_and_lifecycle(tmp_path):
    r = module()
    evidence = r.load_evidence()
    e = evidence[1]
    chunks = [
        {
            "content": e.content,
            "file_path": "commerceops-demo-shop-demo-v3-R2.md",
            "chunk_id": "good",
            "reference_id": "1",
        },
        {
            "content": "stale changed policy",
            "file_path": "commerceops-demo-shop-demo-v3-R1.md",
            "chunk_id": "stale",
            "reference_id": "2",
        },
        {
            "content": e.content,
            "file_path": "another-shop/R2.md",
            "chunk_id": "foreign",
            "reference_id": "3",
        },
        {
            "content": e.content,
            "file_path": "commerceops-demo-shop-demo-v3-R2.md",
            "chunk_id": "duplicate",
            "reference_id": "4",
        },
    ]
    sdk = SDKDouble(sdk_result(chunks))
    adapter = r.LightRAGRetriever(evidence, tmp_path / "index", rag=sdk)

    async def run():
        await adapter.initialize()
        await adapter.ingest()
        await adapter.ingest()
        results = await adapter.search("新客优惠券")
        assert [v.id for v in results] == ["R2"]
        assert results[0].content == e.content
        await adapter.close()

    asyncio.run(run())
    assert sdk.ingests == 1 and sdk.closed


def test_adapter_rejects_foreign_workspace_and_concurrent_owner(tmp_path):
    r = module()
    directory = tmp_path / "index"
    directory.mkdir()
    (directory / "foreign.json").write_text("{}")

    async def foreign():
        with pytest.raises(RuntimeError, match="unmanaged"):
            await r.LightRAGRetriever(r.load_evidence(), directory, rag=SDKDouble({})).initialize()

    asyncio.run(foreign())
    clean = tmp_path / "clean"

    async def locked():
        first = r.LightRAGRetriever(r.load_evidence(), clean, rag=SDKDouble({}))
        second = r.LightRAGRetriever(r.load_evidence(), clean, rag=SDKDouble({}))
        await first.initialize()
        try:
            with pytest.raises(RuntimeError, match="in use"):
                await second.initialize()
        finally:
            await first.close()

    asyncio.run(locked())


def test_sdk_failure_never_silently_falls_back(tmp_path):
    r = module()
    adapter = r.LightRAGRetriever(
        r.load_evidence(),
        tmp_path / "index",
        rag=SDKDouble({"status": "failure", "message": "store unavailable", "data": {}}),
    )

    async def run():
        await adapter.initialize()
        await adapter.ingest()
        try:
            with pytest.raises(RuntimeError, match="retrieval"):
                await adapter.search("优惠券")
            assert adapter.backend == "lightrag"
        finally:
            await adapter.close()

    asyncio.run(run())


def test_environment_defaults_offline_and_rejects_incomplete_model_config(tmp_path, monkeypatch):
    r = module()
    monkeypatch.delenv("COMMERCEOPS_RETRIEVAL", raising=False)
    assert r.from_environment(tmp_path, r.load_evidence()).backend == "lexical-demo"
    monkeypatch.setenv("COMMERCEOPS_RETRIEVAL", "lightrag")
    for name in [
        "COMMERCEOPS_MODEL_BASE_URL",
        "COMMERCEOPS_API_KEY",
        "COMMERCEOPS_LLM_MODEL",
        "COMMERCEOPS_EMBEDDING_MODEL",
        "COMMERCEOPS_EMBEDDING_DIM",
    ]:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="COMMERCEOPS_"):
        r.from_environment(tmp_path, r.load_evidence())


def test_failed_document_ingest_never_marks_index_ready(tmp_path):
    r = module()
    sdk = SDKDouble(sdk_result([]))

    class FailedStatus:
        async def get_by_ids(self, ids):
            return [
                {
                    "status": "failed",
                    "content_summary": "mock document",
                    "content_length": 10,
                    "created_at": "2026-10-01T00:00:00+08:00",
                    "updated_at": "2026-10-01T00:00:00+08:00",
                    "file_path": "commerceops-demo-shop-demo-v3-R1.md",
                    "chunks_count": 0,
                    "error": "model unavailable",
                    "metadata": {},
                }
                for _ in ids
            ]

    sdk.doc_status = FailedStatus()
    adapter = r.LightRAGRetriever(r.load_evidence(), tmp_path / "index", rag=sdk)

    async def run():
        await adapter.initialize()
        try:
            with pytest.raises(RuntimeError, match="ingest"):
                await adapter.ingest()
            with pytest.raises(RuntimeError, match="not initialized and ingested"):
                await adapter.search("新客满减")
        finally:
            await adapter.close()

    asyncio.run(run())


def test_stale_manifest_fails_closed(tmp_path):
    import json

    r = module()
    directory = tmp_path / "index"

    async def run():
        first = r.LightRAGRetriever(r.load_evidence(), directory, rag=SDKDouble({}))
        await first.initialize()
        await first.close()
        path = directory / "commerceops-manifest.json"
        data = json.loads(path.read_text())
        data["fingerprint"] = "outdated-corpus"
        path.write_text(json.dumps(data))
        second = r.LightRAGRetriever(r.load_evidence(), directory, rag=SDKDouble({}))
        with pytest.raises(RuntimeError, match="stale or foreign"):
            await second.initialize()

    asyncio.run(run())


def test_changed_embedding_configuration_requires_new_index(tmp_path):
    r = module()
    config = {
        "base_url": "https://provider.test/v1",
        "api_key": "secret-not-in-manifest",
        "llm_model": "llm-a",
        "embedding_model": "embed-a",
        "embedding_dim": 128,
    }
    directory = tmp_path / "index"

    async def run():
        first = r.LightRAGRetriever(
            r.load_evidence(), directory, rag=SDKDouble({}), model_config=config
        )
        await first.initialize()
        await first.ingest()
        await first.close()
        assert "secret-not-in-manifest" not in (directory / "commerceops-manifest.json").read_text()
        second = r.LightRAGRetriever(
            r.load_evidence(),
            directory,
            rag=SDKDouble({}),
            model_config={**config, "embedding_model": "embed-b"},
        )
        with pytest.raises(RuntimeError, match="stale or foreign"):
            await second.initialize()

    asyncio.run(run())


def test_real_sdk_no_results_is_empty_evidence(tmp_path):
    r = module()
    adapter = r.LightRAGRetriever(
        r.load_evidence(),
        tmp_path / "index",
        rag=SDKDouble(
            {
                "status": "failure",
                "message": "No relevant document chunks found.",
                "data": {},
                "metadata": {"query_mode": "mix"},
            }
        ),
    )

    async def run():
        await adapter.initialize()
        await adapter.ingest()
        try:
            assert await adapter.search("量子纠缠与黑洞辐射") == []
        finally:
            await adapter.close()

    asyncio.run(run())
