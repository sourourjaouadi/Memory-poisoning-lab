"""
Vector Store wrapper using ChromaDB for persistent semantic memory.

Pinned Embedding Model:
  all-MiniLM-L6-v2 (384-dimensional dense embeddings).
  Implemented via Chroma's ONNXMiniLM_L6_V2 engine, with SentenceTransformer
  fallback. Running onnxruntime ensures local, reproducible, deterministic
  vector generation without requiring a CUDA GPU or third-party API credentials.

Every entry stored here includes full Provenance metadata.

Critical Phase 0/1 Architectural Note:
Recall is completely INDISCRIMINATE: memories matching the session or query
are returned verbatim without trust gating, filtering, or scoring.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

from memory.schema import Provenance, SemanticMemoryItem


PINNED_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
COLLECTION_NAME = "agent_semantic_memory"


def get_pinned_embedding_function(model_name: str = PINNED_EMBEDDING_MODEL_NAME):
    """
    Returns the pinned all-MiniLM-L6-v2 embedding function.
    Prefers ONNXMiniLM_L6_V2 for lightweight, fast execution.
    """
    try:
        return embedding_functions.ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
    except Exception:
        return embedding_functions.DefaultEmbeddingFunction()


class ChromaVectorStore:
    """
    Persistent ChromaDB wrapper with schema-enforced provenance metadata.
    Data is stored in `persist_dir` across process restarts and container reboots.
    """

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        embedding_model_name: str = PINNED_EMBEDDING_MODEL_NAME,
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_model_name = embedding_model_name

        self.embedding_fn = get_pinned_embedding_function(self.embedding_model_name)

        # Initialize persistent Chroma client
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=Settings(anonymized_telemetry=False),
        )

        # Get or create the unified memory collection
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self.embedding_fn,
            metadata={"description": "Persistent conversational & tool memory for research lab"},
        )

    def add_memory(
        self,
        content: str,
        source: str,
        session_id: str,
        customer_id: str = "",
        actor: str = "user",
        trust_tier: str = "unclassified",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SemanticMemoryItem:
        """
        Store a text memory entry with attached provenance.
        Flattens metadata to string-compatible keys required by Chroma.
        """
        entry_id = str(uuid.uuid4())
        meta = dict(metadata or {})
        if customer_id:
            meta["customer_id"] = customer_id

        item = SemanticMemoryItem.create(
            entry_id=entry_id,
            content=content,
            source=source,
            session_id=session_id,
            actor=actor,
            trust_tier=trust_tier,
            metadata=meta,
        )

        chroma_metadata: Dict[str, Any] = {
            "source": item.provenance.source,
            "timestamp": item.provenance.timestamp,
            "trust_tier": item.provenance.trust_tier,
            "session_id": item.provenance.session_id,
            "customer_id": customer_id,
            "actor": item.provenance.actor,
            "content_hash": item.provenance.content_hash,
            "extra_metadata_json": json.dumps(item.provenance.metadata),
        }

        self.collection.add(
            ids=[item.id],
            documents=[item.content],
            metadatas=[chroma_metadata],
        )
        return item

    def get_by_session(
        self,
        session_id: str,
        limit: int = 20,
    ) -> List[SemanticMemoryItem]:
        """
        Retrieve memories matching a plain session_id.

        ========================================================================
        CRITICAL ARCHITECTURAL NOTE: INDISCRIMINATE RECALL (Phase 0 / Phase 1)
        ========================================================================
        Recall here performs a plain session_id match. It does NOT filter by
        trust_tier, does NOT sanitize content, and does NOT weight entries by
        credibility. All entries stored for this session are recalled
        indiscriminately so subsequent poisoning attacks can be tested.
        ========================================================================
        """
        return self._query_exact(where={"session_id": session_id}, limit=limit)

    def get_by_customer(
        self,
        customer_id: str,
        limit: int = 20,
    ) -> List[SemanticMemoryItem]:
        """
        Retrieve memories matching a plain customer_id across sessions.

        ========================================================================
        CRITICAL ARCHITECTURAL NOTE: STRICT IDENTITY MATCH ONLY (Phase 1)
        ========================================================================
        Cross-session recall matches STRICTLY on exact customer_id.
        There is NO semantic similarity scoring, NO topic matching, and NO
        filtering based on 'how relevant' a memory seems to the current turn.
        ========================================================================
        """
        return self._query_exact(where={"customer_id": customer_id}, limit=limit)

    def _query_exact(self, where: Dict[str, Any], limit: int = 20) -> List[SemanticMemoryItem]:
        """Internal helper for exact metadata matching."""
        results = self.collection.get(
            where=where,
            limit=limit,
            include=["documents", "metadatas"],
        )

        items: List[SemanticMemoryItem] = []
        ids = results.get("ids") or []
        docs = results.get("documents") or []
        metadatas = results.get("metadatas") or []

        for entry_id, doc, meta in zip(ids, docs, metadatas):
            extra_meta = {}
            if meta and "extra_metadata_json" in meta:
                try:
                    extra_meta = json.loads(meta["extra_metadata_json"])
                except Exception:
                    extra_meta = {}

            prov = Provenance(
                source=str(meta.get("source", "unknown")),
                timestamp=str(meta.get("timestamp", "")),
                trust_tier=str(meta.get("trust_tier", "unclassified")),
                session_id=str(meta.get("session_id", "")),
                actor=str(meta.get("actor", "user")),
                content_hash=str(meta.get("content_hash", "")),
                metadata=extra_meta,
            )
            items.append(SemanticMemoryItem(id=entry_id, content=doc, provenance=prov))

        return items

    def search_semantic(
        self,
        query: str,
        top_k: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[SemanticMemoryItem]:
        """
        Search memories via embedding similarity using the pinned model.
        Returns top semantic neighbors indiscriminately.
        """
        query_kwargs: Dict[str, Any] = {
            "query_texts": [query],
            "n_results": top_k,
            "include": ["documents", "metadatas"],
        }
        if where:
            query_kwargs["where"] = where

        results = self.collection.query(**query_kwargs)

        items: List[SemanticMemoryItem] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        for entry_id, doc, meta in zip(ids, docs, metadatas):
            extra_meta = {}
            if meta and "extra_metadata_json" in meta:
                try:
                    extra_meta = json.loads(meta["extra_metadata_json"])
                except Exception:
                    extra_meta = {}

            prov = Provenance(
                source=str(meta.get("source", "unknown")),
                timestamp=str(meta.get("timestamp", "")),
                trust_tier=str(meta.get("trust_tier", "unclassified")),
                session_id=str(meta.get("session_id", "")),
                actor=str(meta.get("actor", "user")),
                content_hash=str(meta.get("content_hash", "")),
                metadata=extra_meta,
            )
            items.append(SemanticMemoryItem(id=entry_id, content=doc, provenance=prov))

        return items

    def count(self) -> int:
        """Return total count of stored items in collection."""
        return self.collection.count()
