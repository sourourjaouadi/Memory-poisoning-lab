"""
Structured Store (SQLite) for discrete facts and preferences.

This store tracks high-confidence key/value facts such as user preferences,
entity attributes, or system configuration. Every stored fact is accompanied
by the full Provenance metadata schema.

Important Architectural Note for Phase 0/1:
Queries to this store do NOT apply trust-weighting or sanitization filters.
Records matching the target session or entity are retrieved indiscriminately.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.schema import Provenance, StructuredFact


class SQLiteStructuredStore:
    """
    SQLite-backed store for structured entity-attribute-value (EAV) facts.
    Guarantees persistence across agent and container restarts.
    """

    def __init__(self, db_path: str = "data/memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    id TEXT PRIMARY KEY,
                    entity TEXT NOT NULL,
                    attribute TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    trust_tier TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    UNIQUE(entity, attribute)
                );
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_session ON facts(session_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_facts_entity ON facts(entity);")
            conn.commit()

    def set_fact(
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
        Store or overwrite a discrete fact with full provenance.
        Uses INSERT OR REPLACE on (entity, attribute).
        """
        entry_id = str(uuid.uuid4())
        fact = StructuredFact.create(
            entry_id=entry_id,
            entity=entity,
            attribute=attribute,
            value=value,
            source=source,
            session_id=session_id,
            actor=actor,
            trust_tier=trust_tier,
            metadata=metadata,
        )

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO facts (
                    id, entity, attribute, value, source, timestamp,
                    trust_tier, session_id, actor, content_hash, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entity, attribute) DO UPDATE SET
                    id=excluded.id,
                    value=excluded.value,
                    source=excluded.source,
                    timestamp=excluded.timestamp,
                    trust_tier=excluded.trust_tier,
                    session_id=excluded.session_id,
                    actor=excluded.actor,
                    content_hash=excluded.content_hash,
                    metadata_json=excluded.metadata_json;
                """,
                (
                    fact.id,
                    fact.entity,
                    fact.attribute,
                    fact.value,
                    fact.provenance.source,
                    fact.provenance.timestamp,
                    fact.provenance.trust_tier,
                    fact.provenance.session_id,
                    fact.provenance.actor,
                    fact.provenance.content_hash,
                    json.dumps(fact.provenance.metadata),
                ),
            )
            conn.commit()
        return fact

    def get_fact(self, entity: str, attribute: str) -> Optional[StructuredFact]:
        """Retrieve a specific fact by entity and attribute."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM facts WHERE entity = ? AND attribute = ?",
                (entity, attribute),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_fact(row)

    def list_facts(
        self,
        entity: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> List[StructuredFact]:
        """
        Retrieve facts matching entity or session_id.

        NOTE ON INDISCRIMINATE RECALL (Phase 0/1 Requirement):
        This method intentionally performs plain matching with NO trust filtering,
        sanitization, or verification. All facts matching the criteria are returned
        verbatim, allowing memory poisoning research to evaluate downstream impact.
        """
        query = "SELECT * FROM facts WHERE 1=1"
        params: List[Any] = []

        if entity:
            query += " AND entity = ?"
            params.append(entity)
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)

        query += " ORDER BY timestamp ASC"

        with self._get_connection() as conn:
            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()
            return [self._row_to_fact(r) for r in rows]

    def delete_fact(self, entity: str, attribute: str) -> bool:
        """Delete a fact by entity and attribute."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM facts WHERE entity = ? AND attribute = ?",
                (entity, attribute),
            )
            conn.commit()
            return cur.rowcount > 0

    def _row_to_fact(self, row: sqlite3.Row) -> StructuredFact:
        metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
        prov = Provenance(
            source=row["source"],
            timestamp=row["timestamp"],
            trust_tier=row["trust_tier"],
            session_id=row["session_id"],
            actor=row["actor"],
            content_hash=row["content_hash"],
            metadata=metadata,
        )
        return StructuredFact(
            id=row["id"],
            entity=row["entity"],
            attribute=row["attribute"],
            value=row["value"],
            provenance=prov,
        )
