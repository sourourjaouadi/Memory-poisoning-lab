"""
Memory Inspection CLI Tool.

Enables direct human auditing and forensic inspection of persistent memory stores
(both ChromaDB vector store and SQLite structured store).

Inspect full provenance metadata:
  - source (e.g. user_chat, tool_output:update_payment_info)
  - timestamp (ISO-8601 UTC)
  - trust_tier (unclassified)
  - session_id & customer_id
  - entry_id
  - content_hash (SHA-256)

Usage examples:
  python inspect_memory.py
  python inspect_memory.py --session-id session_acme_01
  python inspect_memory.py --source tool_output:update_payment_info
  python inspect_memory.py --store vector
  python inspect_memory.py --store structured
  python inspect_memory.py --show <entry_id>
  python inspect_memory.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.config import AgentConfig
from memory.vector_store import ChromaVectorStore


def fetch_structured_entries(
    sqlite_path: str,
    session_id: Optional[str] = None,
    source: Optional[str] = None,
    trust_tier: Optional[str] = None,
    entry_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query SQLite structured facts with optional filters."""
    db_file = Path(sqlite_path)
    if not db_file.exists():
        return []

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM facts WHERE 1=1"
    params: List[Any] = []

    if entry_id:
        query += " AND id = ?"
        params.append(entry_id)
    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    if source:
        query += " AND source = ?"
        params.append(source)
    if trust_tier:
        query += " AND trust_tier = ?"
        params.append(trust_tier)

    query += " ORDER BY timestamp DESC"

    with conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    entries = []
    for r in rows:
        meta = json.loads(r["metadata_json"]) if r["metadata_json"] else {}
        entries.append({
            "store": "STRUCTURED (SQLite)",
            "entry_id": r["id"],
            "session_id": r["session_id"],
            "timestamp": r["timestamp"],
            "source": r["source"],
            "trust_tier": r["trust_tier"],
            "actor": r["actor"],
            "content_hash": r["content_hash"],
            "content": f"{r['entity']}.{r['attribute']} = {r['value']}",
            "entity": r["entity"],
            "attribute": r["attribute"],
            "value": r["value"],
            "metadata": meta,
        })
    return entries


def fetch_vector_entries(
    chroma_dir: str,
    embedding_model_name: str,
    session_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    source: Optional[str] = None,
    trust_tier: Optional[str] = None,
    entry_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query ChromaDB collection documents and metadatas with optional filters."""
    chroma_path = Path(chroma_dir)
    if not chroma_path.exists():
        return []

    store = ChromaVectorStore(persist_dir=chroma_dir, embedding_model_name=embedding_model_name)

    # If querying by specific entry ID:
    if entry_id:
        res = store.collection.get(ids=[entry_id], include=["documents", "metadatas"])
    else:
        # Chroma where filter
        where_clauses: List[Dict[str, Any]] = []
        if session_id:
            where_clauses.append({"session_id": session_id})
        if customer_id:
            where_clauses.append({"customer_id": customer_id})
        if source:
            where_clauses.append({"source": source})
        if trust_tier:
            where_clauses.append({"trust_tier": trust_tier})

        where_filter: Optional[Dict[str, Any]] = None
        if len(where_clauses) == 1:
            where_filter = where_clauses[0]
        elif len(where_clauses) > 1:
            where_filter = {"$and": where_clauses}

        res = store.collection.get(
            where=where_filter,
            include=["documents", "metadatas"],
        )

    entries = []
    ids = res.get("ids") or []
    docs = res.get("documents") or []
    metadatas = res.get("metadatas") or []

    for eid, doc, meta in zip(ids, docs, metadatas):
        extra = {}
        if meta and "extra_metadata_json" in meta:
            try:
                extra = json.loads(meta["extra_metadata_json"])
            except Exception:
                extra = {}

        entries.append({
            "store": "VECTOR (ChromaDB)",
            "entry_id": eid,
            "session_id": meta.get("session_id", "N/A"),
            "customer_id": meta.get("customer_id", ""),
            "timestamp": meta.get("timestamp", "N/A"),
            "source": meta.get("source", "N/A"),
            "trust_tier": meta.get("trust_tier", "unclassified"),
            "actor": meta.get("actor", "user"),
            "content_hash": meta.get("content_hash", ""),
            "content": doc,
            "metadata": extra,
        })
    # Sort newest first
    entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return entries


def render_single_entry(entry: Dict[str, Any]) -> None:
    """Print complete unabridged forensic breakdown of a single memory entry."""
    print("=" * 78)
    print(f"  [ENTRY VIEW] MEMORY RECORD — ID: {entry['entry_id']}")
    print("=" * 78)
    print(f"  Store Type:    {entry['store']}")
    print(f"  Session ID:    {entry['session_id']}")
    if entry.get("customer_id"):
        print(f"  Customer ID:   {entry['customer_id']}")
    print(f"  Source Origin: {entry['source']}")
    print(f"  Trust Tier:    {entry['trust_tier']}")
    print(f"  Actor:         {entry['actor']}")
    print(f"  Timestamp:     {entry['timestamp']}")
    print(f"  SHA-256 Hash:  {entry['content_hash']}")
    print("-" * 78)
    print("  RAW CONTENT PAYLOAD:")
    print(entry['content'])
    print("-" * 78)
    if entry.get("metadata"):
        print("  ATTACHED PROVENANCE METADATA:")
        print(json.dumps(entry['metadata'], indent=2))
    print("=" * 78 + "\n")


def render_entries_table(entries: List[Dict[str, Any]], limit: int = 50) -> None:
    """Print readable tabular list of entries with key provenance fields."""
    displayed = entries[:limit]
    print("=" * 110)
    print(f" {'STORE':<10} | {'SOURCE':<30} | {'TRUST':<12} | {'SESSION':<16} | {'CONTENT SNIPPET':<32}")
    print("=" * 110)

    for e in displayed:
        store_label = "VEC" if "VECTOR" in e["store"] else "STRUCT"
        source = e["source"][:30]
        trust = e["trust_tier"][:12]
        session = e["session_id"][:16]
        snippet = e["content"].replace("\n", " ")[:32]
        print(f" {store_label:<10} | {source:<30} | {trust:<12} | {session:<16} | {snippet:<32}")
        print(f"   -> ID: {e['entry_id']} | Hash: {e['content_hash'][:16]}... | Time: {e['timestamp']}")
        print("-" * 110)

    print(f"Showing {len(displayed)} of {len(entries)} matching entries.")
    if len(entries) > limit:
        print(f"(Use --limit {len(entries)} to view all)")
    print("=" * 110 + "\n")


def main() -> None:
    # Reconfigure stdout for UTF-8 on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Forensic Memory Inspector for Memory Poisoning Lab",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--store", choices=["all", "vector", "structured"], default="all", help="Target memory store")
    parser.add_argument("--session-id", default=None, help="Filter by session ID")
    parser.add_argument("--customer-id", default=None, help="Filter by customer ID")
    parser.add_argument("--source", default=None, help="Filter by provenance source (e.g. 'user_chat', 'tool_output:update_payment_info')")
    parser.add_argument("--trust-tier", default=None, help="Filter by trust tier (e.g. 'unclassified')")
    parser.add_argument("--show", "--entry-id", dest="entry_id", default=None, help="View full details for a specific entry ID")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of entries to list")
    parser.add_argument("--json", action="store_true", help="Output raw JSON array")
    parser.add_argument("--db-path", default=None, help="Override SQLite database path")
    parser.add_argument("--chroma-dir", default=None, help="Override ChromaDB persist directory")

    args = parser.parse_args()

    config = AgentConfig()
    db_path = args.db_path or config.sqlite_db_path
    chroma_dir = args.chroma_dir or config.chroma_persist_dir

    all_entries: List[Dict[str, Any]] = []

    # Fetch from SQLite structured store
    if args.store in ("all", "structured"):
        all_entries.extend(fetch_structured_entries(
            sqlite_path=db_path,
            session_id=args.session_id,
            source=args.source,
            trust_tier=args.trust_tier,
            entry_id=args.entry_id,
        ))

    # Fetch from ChromaDB vector store
    if args.store in ("all", "vector"):
        all_entries.extend(fetch_vector_entries(
            chroma_dir=chroma_dir,
            embedding_model_name=config.embedding_model_name,
            session_id=args.session_id,
            customer_id=args.customer_id,
            source=args.source,
            trust_tier=args.trust_tier,
            entry_id=args.entry_id,
        ))

    if args.json:
        print(json.dumps(all_entries, indent=2))
        sys.exit(0)

    if args.entry_id:
        if not all_entries:
            print(f"[-] No memory entry found with ID: {args.entry_id}")
            sys.exit(1)
        render_single_entry(all_entries[0])
        sys.exit(0)

    # Reconfigure stdout for UTF-8 on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Summary header
    print("\n" + "=" * 80)
    print("  [MEMORY INSPECTION AUDIT] - MEMORY POISONING LAB")
    print("=" * 80)
    print(f"  Target Stores:   {args.store.upper()}")
    print(f"  SQLite Store:    {db_path}")
    print(f"  ChromaDB Store:  {chroma_dir}")
    if args.session_id:
        print(f"  Filter Session:  {args.session_id}")
    if args.customer_id:
        print(f"  Filter Customer: {args.customer_id}")
    if args.source:
        print(f"  Filter Source:   {args.source}")
    if args.trust_tier:
        print(f"  Filter Trust:    {args.trust_tier}")
    print(f"  Total Matching:  {len(all_entries)} records")
    print("=" * 80 + "\n")

    if not all_entries:
        print("  (No memory entries found matching filters)\n")
        sys.exit(0)

    render_entries_table(all_entries, limit=args.limit)


if __name__ == "__main__":
    main()
