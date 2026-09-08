"""
Data contracts and provenance schema for the Memory Poisoning Lab.

Every memory write in this lab (vector or structured) MUST carry provenance.
Provenance metadata tracks who originated the data, when, under what session,
and what trust tier applies.

In Phase 0, 'trust_tier' defaults to 'unclassified' and recall is completely
indiscriminate. In Phase 2, defense layers will rely on this exact schema to
gate or sanitize memories.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of text content for integrity and tamper tracking."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class Provenance(BaseModel):
    """
    Core Provenance record attached to every persistent memory entry.

    Fields:
      source: Identifies origin. Examples:
              - 'user_chat' (untrusted user prompt input)
              - 'tool_output:invoice_lookup' (tool return value)
              - 'tool_output:support_ticket_intake'
              - 'system_bootstrap' (initial seed data)
              - 'agent_inference' (deduced by the model)
      timestamp: ISO-8601 string in UTC timezone.
      trust_tier: Classification tier for defense research.
                  Values in Phase 0: 'unclassified' (hardcoded default).
                  Future tiers: 'untrusted', 'quarantined', 'verified_system', 'trusted_tool'.
      session_id: The conversation/workflow session ID where the write occurred.
      actor: The participant entity ('user', 'tool', 'system', 'assistant').
      content_hash: SHA-256 checksum of the stored text/value for integrity verification.
      metadata: Arbitrary dictionary for tool execution arguments or domain context.
    """
    source: str = Field(..., description="Origin of the memory item (e.g. user_chat, tool_output:<name>)")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trust_tier: str = Field(default="unclassified", description="Security trust tier (default 'unclassified' in Phase 0)")
    session_id: str = Field(..., description="ID of the conversation session that originated this entry")
    actor: str = Field(default="user", description="Actor creating this memory: 'user', 'tool', 'assistant', or 'system'")
    content_hash: str = Field(default="", description="SHA-256 hash of payload")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary extra context")

    def model_post_init(self, __context: Any) -> None:
        # If content_hash is not set manually, can be updated from text
        pass


class SemanticMemoryItem(BaseModel):
    """
    Represents an entry stored in the vector store (ChromaDB).
    Contains raw natural-language content plus provenance metadata.
    """
    id: str = Field(..., description="Unique UUID for this semantic entry")
    content: str = Field(..., description="Natural language text content to embed and store")
    provenance: Provenance = Field(..., description="Full provenance metadata")

    @classmethod
    def create(
        cls,
        entry_id: str,
        content: str,
        source: str,
        session_id: str,
        actor: str = "user",
        trust_tier: str = "unclassified",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SemanticMemoryItem":
        prov = Provenance(
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trust_tier=trust_tier,
            session_id=session_id,
            actor=actor,
            content_hash=compute_content_hash(content),
            metadata=metadata or {},
        )
        return cls(id=entry_id, content=content, provenance=prov)


class StructuredFact(BaseModel):
    """
    Represents a discrete fact/preference stored in the relational store (SQLite).
    Follows an Entity-Attribute-Value (EAV) model with strict provenance metadata.
    """
    id: str = Field(..., description="Unique UUID for this fact")
    entity: str = Field(..., description="Entity name or target, e.g. 'user', 'customer_42', 'system'")
    attribute: str = Field(..., description="Property key, e.g. 'preferred_name', 'billing_address', 'vip_status'")
    value: str = Field(..., description="Stored string value of the attribute")
    provenance: Provenance = Field(..., description="Full provenance metadata")

    @classmethod
    def create(
        cls,
        entry_id: str,
        entity: str,
        attribute: str,
        value: str,
        source: str,
        session_id: str,
        actor: str = "user",
        trust_tier: str = "unclassified",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "StructuredFact":
        prov = Provenance(
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            trust_tier=trust_tier,
            session_id=session_id,
            actor=actor,
            content_hash=compute_content_hash(f"{entity}:{attribute}:{value}"),
            metadata=metadata or {},
        )
        return cls(id=entry_id, entity=entity, attribute=attribute, value=value, provenance=prov)
