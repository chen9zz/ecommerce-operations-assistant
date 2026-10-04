"""Approved demo knowledge with explicit lexical and optional real LightRAG backends."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Evidence:
    id: str
    title: str
    content: str
    source: str
    version: str
    score: float = 0.0


def load_evidence(snapshot_id: str = "demo-v3") -> list[Evidence]:
    if snapshot_id != "demo-v3":
        raise ValueError("Only the approved demo-v3 snapshot is available")
    directory = Path(__file__).parent / "data" / "knowledge" / snapshot_id
    result = []
    for i in range(1, 7):
        path = directory / f"R{i}.md"
        content = path.read_text(encoding="utf-8").strip()
        result.append(
            Evidence(
                f"R{i}",
                content.splitlines()[0].lstrip("# "),
                content,
                f"commerceops/data/knowledge/{snapshot_id}/{path.name}",
                snapshot_id,
            )
        )
    return result


def _tokens(text: str) -> set[str]:
    # Chinese bigrams avoid a segmenter dependency; ASCII words/numbers stay whole.
    tokens = set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()))
    for span in re.findall(r"[\u3400-\u9fff]+", text):
        tokens.update(span[i : i + 2] for i in range(len(span) - 1))
    return tokens


def _validate_search(mode: str, limit: int) -> None:
    if mode not in {"mix", "local", "global", "hybrid", "naive"}:
        raise ValueError("Unsupported retrieval mode")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer between 1 and 50")


class LexicalRetriever:
    backend = "lexical-demo"

    def __init__(self, evidence: list[Evidence]):
        self.evidence = list(evidence)
        self._terms = [_tokens(e.title + " " + e.content.split("\n\n")[-1]) for e in evidence]

    async def search(self, query: str, mode: str = "mix", limit: int = 6) -> list[Evidence]:
        _validate_search(mode, limit)
        query_terms = _tokens(query.strip())
        scores = []
        for evidence, terms in zip(self.evidence, self._terms):
            shared = query_terms & terms
            if not shared:
                continue
            # Rare shared terms and title matches outrank generic 活动/优惠 matches.
            score = sum(
                math.log(1 + len(self.evidence) / sum(t in ts for ts in self._terms))
                * (2 if t in _tokens(evidence.title) else 1)
                for t in shared
            )
            scores.append(replace(evidence, score=round(score, 6)))
        return sorted(scores, key=lambda e: (-e.score, e.id))[:limit]


class LightRAGRetriever:
    """One process owns one fingerprinted demo-shop / demo-v3 graph directory.

    SDK imports are lazy so the offline product needs no LightRAG installation.
    Injecting an actual configured SDK instance also supports local providers.
    """

    backend = "lightrag"

    def __init__(
        self,
        evidence: list[Evidence],
        work_dir: Path,
        *,
        rag: Any = None,
        model_config: dict[str, Any] | None = None,
        sdk_factory=None,
    ):
        approved = load_evidence()
        if [asdict(replace(e, score=0)) for e in evidence] != [asdict(e) for e in approved]:
            raise ValueError("LightRAG accepts only the complete approved demo-v3 snapshot")
        self.evidence = list(evidence)
        self.work_dir = Path(work_dir)
        self.rag = rag
        self.model_config = model_config
        self._sdk_factory = sdk_factory
        self._lock = None
        self._ready = False
        self._initialized = False
        self._client = None
        index_config = {
            key: value for key, value in (model_config or {}).items() if key != "api_key"
        }
        self._fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "clauses": [asdict(e) for e in approved],
                    "index_config": index_config,
                    "format": 1,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    @staticmethod
    def _sdk_path(evidence: Evidence) -> str:
        # SDK strips directories. Encode owner + version in basename before ingestion.
        return f"commerceops-demo-shop-{evidence.version}-{evidence.id}.md"

    def _write_manifest(self, ready: bool) -> None:
        target = self.work_dir / "commerceops-manifest.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "owner": "commerceops/demo-shop",
                    "snapshot": "demo-v3",
                    "fingerprint": self._fingerprint,
                    "ready": ready,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(target)

    async def initialize(self) -> None:
        if self._initialized:
            return
        import fcntl

        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._lock = (self.work_dir / ".commerceops.lock").open("a+")
        try:
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("LightRAG workspace is in use") from exc
            manifest = self.work_dir / "commerceops-manifest.json"
            if manifest.exists():
                data = json.loads(manifest.read_text(encoding="utf-8"))
                if (data.get("owner"), data.get("snapshot"), data.get("fingerprint")) != (
                    "commerceops/demo-shop",
                    "demo-v3",
                    self._fingerprint,
                ):
                    raise RuntimeError("LightRAG workspace belongs to a stale or foreign snapshot")
                if not data.get("ready"):
                    # A killed ingest cannot silently become an approved complete index.
                    others = [
                        p
                        for p in self.work_dir.iterdir()
                        if p.name not in {".commerceops.lock", manifest.name}
                    ]
                    if others:
                        raise RuntimeError(
                            "Incomplete LightRAG workspace; use a new empty directory"
                        )
                self._ready = bool(data.get("ready"))
            elif any(p.name != ".commerceops.lock" for p in self.work_dir.iterdir()):
                raise RuntimeError("Refusing an unmanaged LightRAG workspace")
            else:
                self._write_manifest(False)
            if self.rag is None:
                self.rag = (
                    self._sdk_factory(self.work_dir) if self._sdk_factory else self._build_sdk()
                )
            await self.rag.initialize_storages()
            self._initialized = True
        except BaseException:
            await self.close()
            raise

    def _build_sdk(self):
        import httpx
        import numpy as np
        from lightrag import LightRAG
        from lightrag.utils import EmbeddingFunc

        if not self.model_config:
            raise ValueError("LightRAG model configuration is missing")
        cfg = self.model_config
        self._client = httpx.AsyncClient(
            base_url=cfg["base_url"].rstrip("/") + "/",
            timeout=90,
            headers={"Authorization": "Bearer " + cfg["api_key"]},
        )

        async def completion(prompt, system_prompt=None, history_messages=None, **kwargs):
            messages = [{"role": "system", "content": system_prompt}] if system_prompt else []
            messages += list(history_messages or []) + [{"role": "user", "content": prompt}]
            response = await self._client.post(
                "chat/completions",
                json={"model": cfg["llm_model"], "messages": messages, "temperature": 0},
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]

        async def embed(texts):
            response = await self._client.post(
                "embeddings", json={"model": cfg["embedding_model"], "input": texts}
            )
            response.raise_for_status()
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            vectors = np.asarray([row["embedding"] for row in rows], dtype=np.float32)
            if (
                vectors.shape != (len(texts), cfg["embedding_dim"])
                or not np.isfinite(vectors).all()
            ):
                raise ValueError("Embedding provider returned invalid dimensions or values")
            return vectors

        return LightRAG(
            working_dir=str(self.work_dir),
            workspace="demo-shop-demo-v3",
            llm_model_func=completion,
            llm_model_name=cfg["llm_model"],
            embedding_func=EmbeddingFunc(
                embedding_dim=cfg["embedding_dim"],
                max_token_size=8192,
                model_name=cfg["embedding_model"],
                func=embed,
            ),
        )

    async def ingest(self, *, curated_graph: bool = False) -> None:
        if not self._initialized:
            raise RuntimeError("Initialize the LightRAG retriever before ingest")
        if self._ready:
            return
        if curated_graph:
            # Explicit human-authored demo graph. No claim of LLM extraction quality.
            kg = {"chunks": [], "entities": [], "relationships": []}
            for e in self.evidence:
                kg["chunks"].append(
                    {"content": e.content, "source_id": e.id, "file_path": self._sdk_path(e)}
                )
                names = [e.title, f"{e.id} 自建模拟条款"]
                for name in names:
                    kg["entities"].append(
                        {
                            "entity_name": name,
                            "entity_type": "RULE",
                            "description": e.content,
                            "source_id": e.id,
                            "file_path": self._sdk_path(e),
                        }
                    )
                kg["relationships"].append(
                    {
                        "src_id": names[0],
                        "tgt_id": names[1],
                        "description": e.content,
                        "keywords": e.title,
                        "weight": 1.0,
                        "source_id": e.id,
                        "file_path": self._sdk_path(e),
                    }
                )
            await self.rag.ainsert_custom_kg(kg)
        else:
            await self.rag.ainsert(
                [e.content for e in self.evidence],
                ids=[f"demo-v3-{e.id}" for e in self.evidence],
                file_paths=[self._sdk_path(e) for e in self.evidence],
            )
            # ainsert returns a tracking ID even when individual documents fail.
            statuses = await self.rag.doc_status.get_by_ids(
                [f"demo-v3-{e.id}" for e in self.evidence]
            )
            if len(statuses) != len(self.evidence) or any(
                not row or row.get("status") != "processed" for row in statuses
            ):
                raise RuntimeError("LightRAG ingest did not process all approved documents")
        self._write_manifest(True)
        self._ready = True

    async def search(self, query: str, mode: str = "mix", limit: int = 6) -> list[Evidence]:
        _validate_search(mode, limit)
        if not query.strip():
            return []
        if not self._initialized or not self._ready:
            raise RuntimeError("LightRAG workspace is not initialized and ingested")
        from lightrag import QueryParam

        raw = await self.rag.aquery_data(
            query,
            param=QueryParam(
                mode=mode, top_k=max(12, limit), chunk_top_k=max(12, limit), enable_rerank=False
            ),
        )
        if raw.get("status") != "success":
            if raw.get("status") == "failure" and raw.get("message") in {
                "Query returned no results",
                "No relevant document chunks found.",
            }:
                return []
            raise RuntimeError("LightRAG retrieval did not succeed")
        approved = {self._sdk_path(e): e for e in self.evidence}
        results = {}
        # References alone and entity descriptions are not a verified original clause.
        for rank, chunk in enumerate(raw.get("data", {}).get("chunks", [])):
            evidence = approved.get(chunk.get("file_path"))
            if evidence is None or chunk.get("content", "").strip() != evidence.content:
                continue
            if evidence.id not in results:
                results[evidence.id] = replace(evidence, score=round(1 / (rank + 1), 6))
        return list(results.values())[:limit]

    async def close(self) -> None:
        try:
            if self._initialized and self.rag is not None:
                await self.rag.finalize_storages()
        finally:
            self._initialized = False
            try:
                if self._client is not None:
                    await self._client.aclose()
                    self._client = None
            finally:
                if self._lock is not None:
                    self._lock.close()
                    self._lock = None


def from_environment(work_dir: Path, evidence: list[Evidence]):
    backend = os.getenv("COMMERCEOPS_RETRIEVAL", "lexical-demo")
    if backend == "lexical-demo":
        return LexicalRetriever(evidence)
    if backend != "lightrag":
        raise ValueError("COMMERCEOPS_RETRIEVAL must be lexical-demo or lightrag")
    fields = {
        "base_url": "COMMERCEOPS_MODEL_BASE_URL",
        "api_key": "COMMERCEOPS_API_KEY",
        "llm_model": "COMMERCEOPS_LLM_MODEL",
        "embedding_model": "COMMERCEOPS_EMBEDDING_MODEL",
        "embedding_dim": "COMMERCEOPS_EMBEDDING_DIM",
    }
    missing = [env for env in fields.values() if not os.getenv(env)]
    if missing:
        raise ValueError("Missing configuration: " + ", ".join(missing))
    cfg = {key: os.environ[env] for key, env in fields.items()}
    cfg["embedding_dim"] = int(cfg["embedding_dim"])
    if cfg["embedding_dim"] < 1:
        raise ValueError("COMMERCEOPS_EMBEDDING_DIM must be positive")
    return LightRAGRetriever(evidence, Path(work_dir) / "lightrag-demo-v3", model_config=cfg)
