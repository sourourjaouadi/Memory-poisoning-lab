"""
Unified Memory Manager for the Memory Poisoning Lab.

Orchestrates both:
1. Semantic Memory (ChromaDB vector store)
2. Structured Memory (SQLite key/value facts store)

Every read and write is tagged with provenance metadata and logged to
structured JSONL for auditing and evaluation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from agent.logger import get_logger
from memory.schema import SemanticMemoryItem, StructuredFact
from memory.structured_store import SQLiteStructuredStore
from memory.vector_store import ChromaVectorStore, PINNED_EMBEDDING_MODEL_NAME


class MemoryManager:
    """
    Unified facade for the dual-layer memory system.
    """

    def __init__(
        self,
        sqlite_path: str = "data/memory.db",
        chroma_dir: str = "data/chroma",
        embedding_model_name: str = PINNED_EMBEDDING_MODEL_NAME,
    ) -> None:
        self.logger = get_logger("memory_manager")
        self.structured_store = SQLiteStructuredStore(db_path=sqlite_path)
        self.vector_store = ChromaVectorStore(
            persist_dir=chroma_dir,
            embedding_model_name=embedding_model_name,
        )

    def remember(
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
        Write a text entry to semantic memory with provenance metadata.
        Logs structured 'memory_write' event.
        """
        item = self.vector_store.add_memory(
            content=content,
            source=source,
            session_id=session_id,
            customer_id=customer_id,
            actor=actor,
            trust_tier=trust_tier,
            metadata=metadata,
        )

        self.logger.info(
            "memory_write",
            memory_type="semantic",
            memory_id=item.id,
            source=item.provenance.source,
            trust_tier=item.provenance.trust_tier,
            session_id=item.provenance.session_id,
            customer_id=customer_id,
            actor=item.provenance.actor,
            content_hash=item.provenance.content_hash,
            content_snippet=content[:80],
        )
        return item

    def record_fact(
        self,
        entity: str,
        attribute: str,
        value: str,
        source: str,
        session_id: str,
        actor: str = "user",
        trust_tier: str = "unclassified",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StructuredFact:
        """
        Write a discrete fact to structured memory with provenance metadata.
        Logs structured 'memory_write' event.
        """
        fact = self.structured_store.set_fact(
            entity=entity,
            attribute=attribute,
            value=value,
            source=source,
            session_id=session_id,
            actor=actor,
            trust_tier=trust_tier,
            metadata=metadata,
        )

        self.logger.info(
            "memory_write",
            memory_type="structured",
            memory_id=fact.id,
            entity=entity,
            attribute=attribute,
            value=value,
            source=fact.provenance.source,
            trust_tier=fact.provenance.trust_tier,
            session_id=fact.provenance.session_id,
            actor=fact.provenance.actor,
            content_hash=fact.provenance.content_hash,
        )
        return fact

    def recall_session(
        self,
        session_id: str,
        customer_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Recall memories for a given session and/or customer_id.

        ========================================================================
        CRITICAL ARCHITECTURAL NOTE: INDISCRIMINATE RECALL & STRICT IDENTITY
        ========================================================================
        This recall implementation performs a PLAIN session_id match and/or
        STRICT customer_id match ONLY.
        
        It does NOT perform semantic relevance scoring, topic similarity ranking,
        trust-weighting, defense filtering, or sanitization.
        
        All memories recorded under this session_id or customer_id—whether from
        legitimate tool outputs, past sessions, or potentially poisoned user
        inputs—are returned verbatim.
        
        This naive baseline is foundational for evaluating memory poisoning
        propagation before defenses are introduced in Phase 2.
        ========================================================================
        """
        facts_map: Dict[str, StructuredFact] = {}
        # 1. Fetch facts matching current session
        for f in self.structured_store.list_facts(session_id=session_id):
            facts_map[f.id] = f

        # 2. Fetch facts matching customer_id entity across sessions
        if customer_id:
            for f in self.structured_store.list_facts(entity=customer_id):
                facts_map[f.id] = f

        # 3. Fetch vector memories matching current session
        memories_map: Dict[str, SemanticMemoryItem] = {}
        for m in self.vector_store.get_by_session(session_id=session_id):
            memories_map[m.id] = m

        # 4. Fetch vector memories matching customer_id across previous sessions
        if customer_id:
            for m in self.vector_store.get_by_customer(customer_id=customer_id):
                memories_map[m.id] = m

        facts = list(facts_map.values())
        semantic_items = list(memories_map.values())

        self.logger.info(
            "memory_read",
            session_id=session_id,
            customer_id=customer_id or "",
            recalled_facts_count=len(facts),
            recalled_semantic_count=len(semantic_items),
        )

        return {
            "session_id": session_id,
            "customer_id": customer_id,
            "facts": facts,
            "semantic_memories": semantic_items,
        }

    def search_semantic(self, query: str, top_k: int = 5) -> List[SemanticMemoryItem]:
        """
        Semantic search over vector memory.
        Logs structured 'memory_search' event.
        """
        items = self.vector_store.search_semantic(query=query, top_k=top_k)
        self.logger.info(
            "memory_search",
            query=query,
            top_k=top_k,
            results_count=len(items),
        )
        return items

    def get_fact(self, entity: str, attribute: str) -> Optional[StructuredFact]:
        """Fetch a single fact by entity and attribute."""
        fact = self.structured_store.get_fact(entity, attribute)
        if fact:
            self.logger.info(
                "memory_read",
                memory_type="structured",
                entity=entity,
                attribute=attribute,
                found=True,
            )
        return fact
